#!/bin/bash
# Set up Amazon Bedrock Guardrail for content filtering
# Usage: ./setup-guardrail.sh [--yes]
#
# Options:
#   --yes    Auto-confirm all prompts (non-interactive mode)
#
# This script creates:
# - Bedrock guardrail with content filters for hate, violence, sexual, insults, misconduct
# - Filter strengths set to MEDIUM for balanced detection
# - Guardrail version for production use
#
# After running, update your .env file with the output values.

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
GUARDRAIL_NAME="${GUARDRAIL_NAME:-agentcore-chatapp-guardrail}"

echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║         Bedrock Guardrail Setup for ChatApp                ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${YELLOW}Configuration:${NC}"
echo "  Region: $AWS_REGION"
echo "  Guardrail Name: $GUARDRAIL_NAME"
echo ""

# Step 1: Check if guardrail already exists
echo -e "${YELLOW}Step 1: Checking for existing guardrail...${NC}"

EXISTING_GUARDRAIL=$(aws bedrock list-guardrails \
    --region "$AWS_REGION" \
    --query "guardrails[?name=='$GUARDRAIL_NAME'].id | [0]" \
    --output text 2>/dev/null || echo "")

# Trim whitespace and check for valid ID
EXISTING_GUARDRAIL=$(echo "$EXISTING_GUARDRAIL" | tr -d '[:space:]')

if [ -n "$EXISTING_GUARDRAIL" ] && [ "$EXISTING_GUARDRAIL" != "None" ] && [ "$EXISTING_GUARDRAIL" != "null" ]; then
    echo -e "${GREEN}Guardrail already exists: $EXISTING_GUARDRAIL${NC}"
    GUARDRAIL_ID="$EXISTING_GUARDRAIL"
    
    # Get the latest published version (not DRAFT)
    GUARDRAIL_VERSION=$(aws bedrock list-guardrails \
        --guardrail-identifier "$EXISTING_GUARDRAIL" \
        --region "$AWS_REGION" \
        --query "guardrails[?version!='DRAFT'].version | [0]" \
        --output text 2>/dev/null || echo "")
    
    # If no published version exists, create one
    if [ -z "$GUARDRAIL_VERSION" ] || [ "$GUARDRAIL_VERSION" = "None" ] || [ "$GUARDRAIL_VERSION" = "null" ]; then
        echo -e "${YELLOW}No published version found, creating version 1...${NC}"
        GUARDRAIL_VERSION=$(aws bedrock create-guardrail-version \
            --guardrail-identifier "$GUARDRAIL_ID" \
            --description "Published version" \
            --region "$AWS_REGION" \
            --query 'version' \
            --output text)
        echo -e "${GREEN}Created guardrail version: $GUARDRAIL_VERSION${NC}"
    else
        echo -e "${YELLOW}Using published version: $GUARDRAIL_VERSION${NC}"
    fi
else
    # Step 2: Create Bedrock guardrail with content filters
    echo -e "\n${YELLOW}Step 2: Creating Bedrock guardrail...${NC}"

    # Content policy configuration with MEDIUM filter strengths
    # Filters: HATE, VIOLENCE, SEXUAL, INSULTS, MISCONDUCT
    CONTENT_POLICY_CONFIG='{
        "filtersConfig": [
            {
                "type": "HATE",
                "inputStrength": "MEDIUM",
                "outputStrength": "MEDIUM",
                "inputModalities": ["TEXT"],
                "outputModalities": ["TEXT"]
            },
            {
                "type": "VIOLENCE",
                "inputStrength": "MEDIUM",
                "outputStrength": "MEDIUM",
                "inputModalities": ["TEXT"],
                "outputModalities": ["TEXT"]
            },
            {
                "type": "SEXUAL",
                "inputStrength": "MEDIUM",
                "outputStrength": "MEDIUM",
                "inputModalities": ["TEXT"],
                "outputModalities": ["TEXT"]
            },
            {
                "type": "INSULTS",
                "inputStrength": "MEDIUM",
                "outputStrength": "MEDIUM",
                "inputModalities": ["TEXT"],
                "outputModalities": ["TEXT"]
            },
            {
                "type": "MISCONDUCT",
                "inputStrength": "MEDIUM",
                "outputStrength": "MEDIUM",
                "inputModalities": ["TEXT"],
                "outputModalities": ["TEXT"]
            }
        ]
    }'

    # Create the guardrail
    GUARDRAIL_RESULT=$(aws bedrock create-guardrail \
        --name "$GUARDRAIL_NAME" \
        --description "Content filtering guardrail for AgentCore ChatApp - shadow mode evaluation" \
        --region "$AWS_REGION" \
        --content-policy-config "$CONTENT_POLICY_CONFIG" \
        --blocked-input-messaging "Your message could not be processed due to content policy restrictions." \
        --blocked-outputs-messaging "The response could not be provided due to content policy restrictions." \
        --query '[guardrailId, version]' \
        --output text)
    
    GUARDRAIL_ID=$(echo "$GUARDRAIL_RESULT" | awk '{print $1}')
    DRAFT_VERSION=$(echo "$GUARDRAIL_RESULT" | awk '{print $2}')
    
    echo -e "${GREEN}Created guardrail: $GUARDRAIL_ID (draft version: $DRAFT_VERSION)${NC}"
    
    # Step 3: Create a guardrail version for production use
    echo -e "\n${YELLOW}Step 3: Creating guardrail version...${NC}"
    
    GUARDRAIL_VERSION=$(aws bedrock create-guardrail-version \
        --guardrail-identifier "$GUARDRAIL_ID" \
        --description "Initial version with MEDIUM content filters for hate, violence, sexual, insults, misconduct" \
        --region "$AWS_REGION" \
        --query 'version' \
        --output text)
    
    echo -e "${GREEN}Created guardrail version: $GUARDRAIL_VERSION${NC}"
fi

# Step 4: Get guardrail ARN for IAM policy
echo -e "\n${YELLOW}Step 4: Getting guardrail details...${NC}"

GUARDRAIL_ARN=$(aws bedrock get-guardrail \
    --guardrail-identifier "$GUARDRAIL_ID" \
    --guardrail-version "$GUARDRAIL_VERSION" \
    --region "$AWS_REGION" \
    --query 'guardrailArn' \
    --output text)

echo -e "${GREEN}Guardrail ARN: $GUARDRAIL_ARN${NC}"

# Step 5: Update IAM task role to allow Bedrock guardrail access
echo -e "\n${YELLOW}Step 5: Updating IAM task role for Bedrock guardrail access...${NC}"

TASK_ROLE_NAME="htmx-chatapp-task-role"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# Check if task role exists
if aws iam get-role --role-name "$TASK_ROLE_NAME" 2>/dev/null; then
    # Create inline policy for Bedrock guardrail access
    BEDROCK_GUARDRAIL_POLICY="{
      \"Version\": \"2012-10-17\",
      \"Statement\": [
        {
          \"Sid\": \"BedrockGuardrailAccess\",
          \"Effect\": \"Allow\",
          \"Action\": [
            \"bedrock:ApplyGuardrail\",
            \"bedrock:GetGuardrail\"
          ],
          \"Resource\": [
            \"arn:aws:bedrock:*:$ACCOUNT_ID:guardrail/$GUARDRAIL_ID\"
          ]
        }
      ]
    }"
    
    aws iam put-role-policy \
        --role-name "$TASK_ROLE_NAME" \
        --policy-name "BedrockGuardrailAccess" \
        --policy-document "$BEDROCK_GUARDRAIL_POLICY"
    
    echo -e "${GREEN}Updated task role with Bedrock guardrail permissions${NC}"
else
    echo -e "${YELLOW}Task role not found. Run setup-iam.sh first, then re-run this script.${NC}"
fi

# Step 6: Output configuration
echo ""
echo -e "${GREEN}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║         Bedrock Guardrail Setup Complete!                  ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${BLUE}Guardrail Details:${NC}"
echo "  Guardrail ID: $GUARDRAIL_ID"
echo "  Guardrail Version: $GUARDRAIL_VERSION"
echo "  Guardrail ARN: $GUARDRAIL_ARN"
echo ""
echo -e "${BLUE}Content Filters (all at MEDIUM strength):${NC}"
echo "  - HATE, VIOLENCE, SEXUAL, INSULTS, MISCONDUCT"
echo ""

# Only show manual instructions if not in auto mode
if [ "$AUTO_YES" = false ]; then
    echo -e "${BLUE}Add these values to your .env files:${NC}"
    echo ""
    echo "# Agent .env (agent/.env)"
    echo "GUARDRAIL_ID=${GUARDRAIL_ID}"
    echo "GUARDRAIL_VERSION=${GUARDRAIL_VERSION}"
    echo "GUARDRAIL_ENABLED=true"
    echo ""
    echo "# ChatApp .env (chatapp/.env)"
    echo "GUARDRAIL_ID=${GUARDRAIL_ID}"
    echo "GUARDRAIL_VERSION=${GUARDRAIL_VERSION}"
    echo "GUARDRAIL_ENABLED=true"
    echo ""
    echo -e "${YELLOW}Next Steps:${NC}"
    echo "1. Update your agent/.env file with GUARDRAIL_ID, GUARDRAIL_VERSION, GUARDRAIL_ENABLED"
    echo "2. Update your chatapp/.env file with the same values"
    echo "3. Run ./deploy/create-secrets.sh to update AWS secrets"
    echo "4. Redeploy the agent and chatapp to apply changes"
    echo ""
else
    echo -e "${GREEN}Guardrail config will be automatically applied by setup.sh${NC}"
    echo ""
fi

# Optionally update .env files
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHATAPP_DIR="$(dirname "$SCRIPT_DIR")"
AGENT_DIR="$(dirname "$CHATAPP_DIR")/agent"
CHATAPP_ENV_FILE="$CHATAPP_DIR/.env"
AGENT_ENV_FILE="$AGENT_DIR/.env"

update_env_file() {
    local ENV_FILE="$1"
    local FILE_NAME="$2"
    
    if [ -f "$ENV_FILE" ]; then
        if [ "$AUTO_YES" = true ]; then
            REPLY="y"
        else
            echo -e "${YELLOW}Would you like to update $FILE_NAME automatically? (y/n)${NC}"
            read -r REPLY
        fi
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            # Update or add GUARDRAIL_ID
            if grep -q "^GUARDRAIL_ID=" "$ENV_FILE"; then
                sed -i.bak "s|^GUARDRAIL_ID=.*|GUARDRAIL_ID=${GUARDRAIL_ID}|" "$ENV_FILE"
            else
                echo "GUARDRAIL_ID=${GUARDRAIL_ID}" >> "$ENV_FILE"
            fi
            
            # Update or add GUARDRAIL_VERSION
            if grep -q "^GUARDRAIL_VERSION=" "$ENV_FILE"; then
                sed -i.bak "s|^GUARDRAIL_VERSION=.*|GUARDRAIL_VERSION=${GUARDRAIL_VERSION}|" "$ENV_FILE"
            else
                echo "GUARDRAIL_VERSION=${GUARDRAIL_VERSION}" >> "$ENV_FILE"
            fi
            
            # Update or add GUARDRAIL_ENABLED
            if grep -q "^GUARDRAIL_ENABLED=" "$ENV_FILE"; then
                sed -i.bak "s|^GUARDRAIL_ENABLED=.*|GUARDRAIL_ENABLED=true|" "$ENV_FILE"
            else
                echo "GUARDRAIL_ENABLED=true" >> "$ENV_FILE"
            fi
            
            rm -f "$ENV_FILE.bak"
            echo -e "${GREEN}$FILE_NAME updated!${NC}"
        fi
    fi
}

update_env_file "$CHATAPP_ENV_FILE" "chatapp/.env"
update_env_file "$AGENT_ENV_FILE" "agent/.env"
