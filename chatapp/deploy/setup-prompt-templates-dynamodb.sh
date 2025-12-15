#!/bin/bash
# Set up DynamoDB table for prompt templates
# Usage: ./setup-prompt-templates-dynamodb.sh [--yes]
#
# Options:
#   --yes    Auto-confirm all prompts (non-interactive mode)
#
# This script creates:
# - DynamoDB table for storing prompt templates
# - Seeds a default template
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
TABLE_NAME="${PROMPT_TEMPLATES_TABLE_NAME:-agentcore-prompt-templates}"

echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║         DynamoDB Setup for Prompt Templates                ║${NC}"
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

    # Create table with template_id as partition key (simple key schema)
    TABLE_ARN=$(aws dynamodb create-table \
        --table-name "$TABLE_NAME" \
        --region "$AWS_REGION" \
        --attribute-definitions \
            AttributeName=template_id,AttributeType=S \
        --key-schema \
            AttributeName=template_id,KeyType=HASH \
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

# Step 3: Seed default template if it doesn't exist
echo -e "\n${YELLOW}Step 3: Checking for default template...${NC}"

CURRENT_TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

DEFAULT_EXISTS=$(aws dynamodb get-item \
    --table-name "$TABLE_NAME" \
    --region "$AWS_REGION" \
    --key '{"template_id": {"S": "default-capabilities"}}' \
    --query 'Item.template_id.S' \
    --output text 2>/dev/null || echo "")

if [ "$DEFAULT_EXISTS" = "default-capabilities" ]; then
    echo -e "${GREEN}Default template already exists${NC}"
else
    echo -e "${YELLOW}Seeding default template...${NC}"
    
    aws dynamodb put-item \
        --table-name "$TABLE_NAME" \
        --region "$AWS_REGION" \
        --item "{
            \"template_id\": {\"S\": \"default-capabilities\"},
            \"title\": {\"S\": \"Capabilities\"},
            \"description\": {\"S\": \"How the agent can help\"},
            \"prompt_detail\": {\"S\": \"How can you help me?\"},
            \"created_at\": {\"S\": \"$CURRENT_TIMESTAMP\"},
            \"updated_at\": {\"S\": \"$CURRENT_TIMESTAMP\"}
        }"
    
    echo -e "${GREEN}Default template seeded successfully${NC}"
fi


# Step 4: Update IAM task role to allow DynamoDB access
echo -e "\n${YELLOW}Step 4: Updating IAM task role for DynamoDB access...${NC}"

TASK_ROLE_NAME="htmx-chatapp-task-role"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# Check if task role exists
if aws iam get-role --role-name "$TASK_ROLE_NAME" 2>/dev/null; then
    # Create inline policy for DynamoDB prompt templates access
    DYNAMODB_POLICY="{
      \"Version\": \"2012-10-17\",
      \"Statement\": [
        {
          \"Sid\": \"DynamoDBPromptTemplatesAccess\",
          \"Effect\": \"Allow\",
          \"Action\": [
            \"dynamodb:PutItem\",
            \"dynamodb:GetItem\",
            \"dynamodb:UpdateItem\",
            \"dynamodb:DeleteItem\",
            \"dynamodb:Query\",
            \"dynamodb:Scan\"
          ],
          \"Resource\": [
            \"arn:aws:dynamodb:$AWS_REGION:$ACCOUNT_ID:table/$TABLE_NAME\"
          ]
        }
      ]
    }"
    
    aws iam put-role-policy \
        --role-name "$TASK_ROLE_NAME" \
        --policy-name "DynamoDBPromptTemplatesAccess" \
        --policy-document "$DYNAMODB_POLICY"
    
    echo -e "${GREEN}Updated task role with DynamoDB prompt templates permissions${NC}"
else
    echo -e "${YELLOW}Task role not found. Run setup-iam.sh first, then re-run this script.${NC}"
fi

# Step 5: Output configuration
echo ""
echo -e "${GREEN}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║         DynamoDB Prompt Templates Setup Complete!          ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${BLUE}Table Details:${NC}"
echo "  Table Name: $TABLE_NAME"
echo "  Table ARN: $TABLE_ARN"
echo "  Partition Key: template_id (String)"
echo ""
echo -e "${BLUE}Add this value to your .env file:${NC}"
echo ""
echo "PROMPT_TEMPLATES_TABLE_NAME=${TABLE_NAME}"
echo ""
echo -e "${YELLOW}Next Steps:${NC}"
echo "1. Update your chatapp/.env file with PROMPT_TEMPLATES_TABLE_NAME"
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
        if grep -q "^PROMPT_TEMPLATES_TABLE_NAME=" "$ENV_FILE"; then
            sed -i.bak "s|^PROMPT_TEMPLATES_TABLE_NAME=.*|PROMPT_TEMPLATES_TABLE_NAME=${TABLE_NAME}|" "$ENV_FILE"
        else
            echo "PROMPT_TEMPLATES_TABLE_NAME=${TABLE_NAME}" >> "$ENV_FILE"
        fi
        rm -f "$ENV_FILE.bak"
        echo -e "${GREEN}.env file updated!${NC}"
    fi
fi
