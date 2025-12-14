#!/bin/bash
# Set up DynamoDB table for guardrail violations
# Usage: ./setup-guardrail-dynamodb.sh [--yes]
#
# Options:
#   --yes    Auto-confirm all prompts (non-interactive mode)
#
# This script creates:
# - DynamoDB table for storing guardrail violation records
# - GSI on session_id for session-based lookups
#
# After running, update your .env file with the table name.

set -e

# Disable AWS CLI pager
export AWS_PAGER=""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Parse arguments
AUTO_YES=false
while [[ $# -gt 0 ]]; do
    case $1 in
        --yes|-y)
            AUTO_YES=true
            shift
            ;;
        *)
            shift
            ;;
    esac
done

# Configuration
AWS_REGION="${AWS_REGION:-us-east-1}"
TABLE_NAME="${GUARDRAIL_TABLE_NAME:-agentcore-guardrail-violations}"

echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║         DynamoDB Setup for Guardrail Violations            ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${YELLOW}Configuration:${NC}"
echo "  Region: $AWS_REGION"
echo "  Table Name: $TABLE_NAME"
echo ""

# Step 1: Check if table already exists
echo -e "${YELLOW}Step 1: Checking for existing table...${NC}"

TABLE_EXISTS=$(aws dynamodb describe-table \
    --table-name "$TABLE_NAME" \
    --region "$AWS_REGION" \
    --query 'Table.TableName' \
    --output text 2>/dev/null || echo "")

if [ -n "$TABLE_EXISTS" ]; then
    echo -e "${GREEN}Table already exists: $TABLE_NAME${NC}"
    
    # Get table ARN for output
    TABLE_ARN=$(aws dynamodb describe-table \
        --table-name "$TABLE_NAME" \
        --region "$AWS_REGION" \
        --query 'Table.TableArn' \
        --output text)
else
    # Step 2: Create DynamoDB table
    echo -e "\n${YELLOW}Step 2: Creating DynamoDB table...${NC}"

    # Create table with user_id as partition key and timestamp as sort key
    # Include GSI on session_id for session-based lookups
    TABLE_ARN=$(aws dynamodb create-table \
        --table-name "$TABLE_NAME" \
        --region "$AWS_REGION" \
        --attribute-definitions \
            AttributeName=user_id,AttributeType=S \
            AttributeName=timestamp,AttributeType=S \
            AttributeName=session_id,AttributeType=S \
        --key-schema \
            AttributeName=user_id,KeyType=HASH \
            AttributeName=timestamp,KeyType=RANGE \
        --global-secondary-indexes \
            "[
                {
                    \"IndexName\": \"session-index\",
                    \"KeySchema\": [
                        {\"AttributeName\": \"session_id\", \"KeyType\": \"HASH\"},
                        {\"AttributeName\": \"timestamp\", \"KeyType\": \"RANGE\"}
                    ],
                    \"Projection\": {\"ProjectionType\": \"ALL\"}
                }
            ]" \
        --billing-mode PAY_PER_REQUEST \
        --query 'TableDescription.TableArn' \
        --output text)
    
    echo -e "${GREEN}Created table: $TABLE_NAME${NC}"
    
    # Wait for table to become active
    echo -e "${YELLOW}Waiting for table to become active...${NC}"
    aws dynamodb wait table-exists \
        --table-name "$TABLE_NAME" \
        --region "$AWS_REGION"
    echo -e "${GREEN}Table is now active${NC}"
fi

# Step 3: Update IAM task role to allow DynamoDB access
echo -e "\n${YELLOW}Step 3: Updating IAM task role for DynamoDB access...${NC}"

TASK_ROLE_NAME="htmx-chatapp-task-role"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# Check if task role exists
if aws iam get-role --role-name "$TASK_ROLE_NAME" 2>/dev/null; then
    # Create inline policy for DynamoDB guardrail access
    DYNAMODB_POLICY="{
      \"Version\": \"2012-10-17\",
      \"Statement\": [
        {
          \"Sid\": \"DynamoDBGuardrailAccess\",
          \"Effect\": \"Allow\",
          \"Action\": [
            \"dynamodb:PutItem\",
            \"dynamodb:GetItem\",
            \"dynamodb:Query\",
            \"dynamodb:Scan\",
            \"dynamodb:BatchWriteItem\"
          ],
          \"Resource\": [
            \"arn:aws:dynamodb:$AWS_REGION:$ACCOUNT_ID:table/$TABLE_NAME\",
            \"arn:aws:dynamodb:$AWS_REGION:$ACCOUNT_ID:table/$TABLE_NAME/index/*\"
          ]
        }
      ]
    }"
    
    aws iam put-role-policy \
        --role-name "$TASK_ROLE_NAME" \
        --policy-name "DynamoDBGuardrailAccess" \
        --policy-document "$DYNAMODB_POLICY"
    
    echo -e "${GREEN}Updated task role with DynamoDB guardrail permissions${NC}"
else
    echo -e "${YELLOW}Task role not found. Run setup-iam.sh first, then re-run this script.${NC}"
fi

# Step 4: Output configuration
echo ""
echo -e "${GREEN}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║         DynamoDB Guardrail Setup Complete!                 ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${BLUE}Table Details:${NC}"
echo "  Table Name: $TABLE_NAME"
echo "  Table ARN: $TABLE_ARN"
echo "  Partition Key: user_id (String)"
echo "  Sort Key: timestamp (String)"
echo "  GSI: session-index (session_id, timestamp)"
echo ""
echo -e "${BLUE}Add this value to your .env file:${NC}"
echo ""
echo "GUARDRAIL_TABLE_NAME=${TABLE_NAME}"
echo ""
echo -e "${YELLOW}Next Steps:${NC}"
echo "1. Update your chatapp/.env file with GUARDRAIL_TABLE_NAME"
echo "2. Run ./deploy/create-secrets.sh to update AWS secrets"
echo ""

# Optionally update .env file
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHATAPP_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$CHATAPP_DIR/.env"

if [ -f "$ENV_FILE" ]; then
    if [ "$AUTO_YES" = true ]; then
        REPLY="y"
    else
        echo -e "${YELLOW}Would you like to update $ENV_FILE automatically? (y/n)${NC}"
        read -r REPLY
    fi
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        if grep -q "^GUARDRAIL_TABLE_NAME=" "$ENV_FILE"; then
            sed -i.bak "s|^GUARDRAIL_TABLE_NAME=.*|GUARDRAIL_TABLE_NAME=${TABLE_NAME}|" "$ENV_FILE"
        else
            echo "GUARDRAIL_TABLE_NAME=${TABLE_NAME}" >> "$ENV_FILE"
        fi
        rm -f "$ENV_FILE.bak"
        echo -e "${GREEN}.env file updated!${NC}"
    fi
fi
