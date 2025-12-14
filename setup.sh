#!/bin/bash
# Deployment script for AgentCore Chat Application
# This script orchestrates the complete deployment process:
#   1. Set up Bedrock Guardrail
#   2. Deploy agent (creates runtime + memory with guardrail)
#   2b. Set up observability (X-Ray, CloudWatch)
#   3. Set up Cognito authentication
#   4. Set up DynamoDB tables (usage, feedback, guardrails)
#   5. Set up IAM roles
#   6. Create secrets in AWS Secrets Manager
#   7. Deploy chatapp to ECS
#
# Usage: ./setup.sh [--skip-agent] [--skip-chatapp] [--region <region>]

set -e

# Disable AWS CLI pager
export AWS_PAGER=""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENT_DIR="$SCRIPT_DIR/agent"
CHATAPP_DIR="$SCRIPT_DIR/chatapp"

# Default configuration
AWS_REGION="${AWS_REGION:-us-east-1}"
SKIP_AGENT=false
SKIP_CHATAPP=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-agent)
            SKIP_AGENT=true
            shift
            ;;
        --skip-chatapp)
            SKIP_CHATAPP=true
            shift
            ;;
        --region)
            AWS_REGION="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: ./setup.sh [options]"
            echo ""
            echo "Options:"
            echo "  --region <region>         AWS region (default: us-east-1)"
            echo "  --skip-agent              Skip agent deployment (use existing)"
            echo "  --skip-chatapp            Skip chatapp deployment"
            echo "  -h, --help                Show this help message"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

echo -e "${CYAN}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║     AgentCore Chat Application Deployment                  ║${NC}"
echo -e "${CYAN}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""

AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text 2>/dev/null || echo "unknown")

echo -e "${YELLOW}Configuration:${NC}"
echo "  AWS Account: $AWS_ACCOUNT_ID"
echo "  AWS Region: $AWS_REGION"
echo "  Skip Agent: $SKIP_AGENT"
echo "  Skip ChatApp: $SKIP_CHATAPP"
echo ""

# Export region for sub-scripts
export AWS_REGION

# ============================================================================
# STEP 1: Set up Bedrock Guardrail
# ============================================================================
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Step 1: Set up Bedrock Guardrail${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

cd "$CHATAPP_DIR/deploy"

if [ -f "./setup-guardrail.sh" ]; then
    ./setup-guardrail.sh --yes
    
    # Extract guardrail ID for agent deployment
    GUARDRAIL_NAME="agentcore-chatapp-guardrail"
    GUARDRAIL_ID=$(aws bedrock list-guardrails --region "$AWS_REGION" \
        --query "guardrails[?name=='$GUARDRAIL_NAME'].id | [0]" --output text 2>/dev/null || echo "")
    
    if [ -n "$GUARDRAIL_ID" ] && [ "$GUARDRAIL_ID" != "None" ] && [ "$GUARDRAIL_ID" != "null" ]; then
        # Get the latest published version (not DRAFT)
        GUARDRAIL_VERSION=$(aws bedrock list-guardrails \
            --guardrail-identifier "$GUARDRAIL_ID" \
            --region "$AWS_REGION" \
            --query "guardrails[?version!='DRAFT'].version | [0]" --output text 2>/dev/null || echo "")
        
        # Default to 1 if no published version found (shouldn't happen since setup-guardrail.sh creates one)
        if [ -z "$GUARDRAIL_VERSION" ] || [ "$GUARDRAIL_VERSION" = "None" ] || [ "$GUARDRAIL_VERSION" = "null" ]; then
            GUARDRAIL_VERSION="1"
        fi
        
        echo -e "${GREEN}Guardrail ready: $GUARDRAIL_ID (version: $GUARDRAIL_VERSION)${NC}"
        export GUARDRAIL_ID
        export GUARDRAIL_VERSION
    fi
else
    echo -e "${YELLOW}Guardrail setup script not found, skipping${NC}"
fi

cd "$SCRIPT_DIR"

# ============================================================================
# STEP 2: Deploy Agent (creates runtime + memory)
# ============================================================================
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Step 2: Deploy Agent${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

if [ "$SKIP_AGENT" = true ]; then
    echo -e "${YELLOW}Skipping agent deployment (--skip-agent)${NC}"
else
    if [ ! -d "$AGENT_DIR" ]; then
        echo -e "${RED}Error: Agent directory not found at $AGENT_DIR${NC}"
        exit 1
    fi
    
    cd "$AGENT_DIR"
    
    # Check if agentcore CLI is available
    if ! command -v agentcore &> /dev/null; then
        echo -e "${RED}Error: agentcore CLI not found${NC}"
        echo "Install with: pip install bedrock-agentcore"
        exit 1
    fi
    
    echo -e "${YELLOW}Deploying agent with agentcore launch...${NC}"
    ./deploy.sh
    
    cd "$SCRIPT_DIR"
fi

# Extract values from agent config
AGENT_CONFIG="$AGENT_DIR/.bedrock_agentcore.yaml"
if [ ! -f "$AGENT_CONFIG" ]; then
    echo -e "${RED}Error: Agent config not found at $AGENT_CONFIG${NC}"
    echo "Please deploy the agent first or check the path"
    exit 1
fi

echo -e "${YELLOW}Extracting configuration from agent deployment...${NC}"

# Parse YAML values (using grep/sed for portability)
AGENTCORE_RUNTIME_ARN=$(grep "agent_arn:" "$AGENT_CONFIG" | head -1 | sed 's/.*agent_arn: //' | tr -d ' ')
MEMORY_ID=$(grep "memory_id:" "$AGENT_CONFIG" | head -1 | sed 's/.*memory_id: //' | tr -d ' ')
AGENT_REGION=$(grep "region:" "$AGENT_CONFIG" | head -1 | sed 's/.*region: //' | tr -d ' ')

# Use agent region if not explicitly set
if [ -n "$AGENT_REGION" ]; then
    AWS_REGION="$AGENT_REGION"
    export AWS_REGION
fi

echo -e "${GREEN}Extracted from agent config:${NC}"
echo "  Runtime ARN: $AGENTCORE_RUNTIME_ARN"
echo "  Memory ID: $MEMORY_ID"
echo "  Region: $AWS_REGION"

if [ -z "$AGENTCORE_RUNTIME_ARN" ] || [ -z "$MEMORY_ID" ]; then
    echo -e "${RED}Error: Could not extract runtime ARN or memory ID from agent config${NC}"
    exit 1
fi

# ============================================================================
# STEP 2b: Set up Observability (X-Ray, CloudWatch)
# ============================================================================
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Step 2b: Set up Observability${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

OBSERVABILITY_SCRIPT="$AGENT_DIR/deploy/setup-observability.sh"
if [ -f "$OBSERVABILITY_SCRIPT" ]; then
    cd "$AGENT_DIR/deploy"
    ./setup-observability.sh --region "$AWS_REGION"
    cd "$SCRIPT_DIR"
else
    echo -e "${YELLOW}Observability script not found at $OBSERVABILITY_SCRIPT${NC}"
fi

# ============================================================================
# STEP 3: Set up Cognito
# ============================================================================
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Step 3: Set up Cognito Authentication${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

cd "$CHATAPP_DIR/deploy"

# Run setup-cognito.sh but capture output instead of interactive prompts
echo -e "${YELLOW}Creating Cognito User Pool...${NC}"

APP_NAME="htmx-chatapp"
POOL_NAME="${APP_NAME}-users"

# Check if pool already exists
EXISTING_POOL=$(aws cognito-idp list-user-pools --max-results 60 --region "$AWS_REGION" \
    --query "UserPools[?Name=='$POOL_NAME'].Id" --output text 2>/dev/null || echo "")

if [ -n "$EXISTING_POOL" ] && [ "$EXISTING_POOL" != "None" ]; then
    echo -e "${GREEN}User Pool already exists: $EXISTING_POOL${NC}"
    USER_POOL_ID="$EXISTING_POOL"
else
    USER_POOL_ID=$(aws cognito-idp create-user-pool \
        --pool-name "$POOL_NAME" \
        --region "$AWS_REGION" \
        --auto-verified-attributes email \
        --username-attributes email \
        --username-configuration CaseSensitive=false \
        --policies "PasswordPolicy={MinimumLength=8,RequireUppercase=true,RequireLowercase=true,RequireNumbers=true,RequireSymbols=false}" \
        --admin-create-user-config "AllowAdminCreateUserOnly=true" \
        --query 'UserPool.Id' \
        --output text)
    echo -e "${GREEN}Created User Pool: $USER_POOL_ID${NC}"
fi

# Create/get client
CLIENT_NAME="${APP_NAME}-client"
EXISTING_CLIENT=$(aws cognito-idp list-user-pool-clients --user-pool-id "$USER_POOL_ID" --region "$AWS_REGION" \
    --query "UserPoolClients[?ClientName=='$CLIENT_NAME'].ClientId" --output text 2>/dev/null || echo "")

if [ -n "$EXISTING_CLIENT" ] && [ "$EXISTING_CLIENT" != "None" ]; then
    echo -e "${GREEN}Client already exists: $EXISTING_CLIENT${NC}"
    CLIENT_ID="$EXISTING_CLIENT"
    CLIENT_SECRET=$(aws cognito-idp describe-user-pool-client \
        --user-pool-id "$USER_POOL_ID" \
        --client-id "$CLIENT_ID" \
        --region "$AWS_REGION" \
        --query 'UserPoolClient.ClientSecret' \
        --output text)
    
    # Ensure USER_PASSWORD_AUTH is enabled
    aws cognito-idp update-user-pool-client \
        --user-pool-id "$USER_POOL_ID" \
        --client-id "$CLIENT_ID" \
        --region "$AWS_REGION" \
        --explicit-auth-flows "ALLOW_REFRESH_TOKEN_AUTH" "ALLOW_USER_PASSWORD_AUTH" \
        > /dev/null
else
    CLIENT_RESULT=$(aws cognito-idp create-user-pool-client \
        --user-pool-id "$USER_POOL_ID" \
        --client-name "$CLIENT_NAME" \
        --region "$AWS_REGION" \
        --generate-secret \
        --explicit-auth-flows "ALLOW_REFRESH_TOKEN_AUTH" "ALLOW_USER_PASSWORD_AUTH" \
        --query 'UserPoolClient.[ClientId,ClientSecret]' \
        --output text)
    
    CLIENT_ID=$(echo "$CLIENT_RESULT" | awk '{print $1}')
    CLIENT_SECRET=$(echo "$CLIENT_RESULT" | awk '{print $2}')
    echo -e "${GREEN}Created client: $CLIENT_ID${NC}"
fi

COGNITO_USER_POOL_ID="$USER_POOL_ID"
COGNITO_CLIENT_ID="$CLIENT_ID"
COGNITO_CLIENT_SECRET="$CLIENT_SECRET"

# Create Admin group if it doesn't exist
ADMIN_GROUP_NAME="Admin"
EXISTING_GROUP=$(aws cognito-idp get-group \
    --user-pool-id "$USER_POOL_ID" \
    --group-name "$ADMIN_GROUP_NAME" \
    --region "$AWS_REGION" \
    --query 'Group.GroupName' \
    --output text 2>/dev/null || echo "")

if [ -z "$EXISTING_GROUP" ] || [ "$EXISTING_GROUP" = "None" ]; then
    aws cognito-idp create-group \
        --user-pool-id "$USER_POOL_ID" \
        --group-name "$ADMIN_GROUP_NAME" \
        --description "Administrators with access to usage analytics dashboard" \
        --region "$AWS_REGION" > /dev/null
    echo -e "${GREEN}Created Admin group${NC}"
else
    echo -e "${GREEN}Admin group already exists${NC}"
fi

echo -e "${GREEN}Cognito setup complete${NC}"

# ============================================================================
# STEP 4: Set up DynamoDB Tables
# ============================================================================
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Step 4: Set up DynamoDB Tables${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

echo -e "${YELLOW}Creating usage analytics table...${NC}"
./setup-dynamodb.sh --yes

echo -e "${YELLOW}Creating feedback table...${NC}"
./setup-feedback-dynamodb.sh --yes

echo -e "${YELLOW}Creating guardrail violations table...${NC}"
./setup-guardrail-dynamodb.sh --yes

# ============================================================================
# STEP 5: Set up IAM Roles
# ============================================================================
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Step 5: Set up IAM Roles${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

./setup-iam.sh

# ============================================================================
# STEP 6: Configure Environment and Secrets
# ============================================================================
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Step 6: Configure Environment and Secrets${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

ENV_FILE="$CHATAPP_DIR/.env"

# Create or update .env file
echo -e "${YELLOW}Updating $ENV_FILE...${NC}"

# Create .env if it doesn't exist
if [ ! -f "$ENV_FILE" ]; then
    cp "$CHATAPP_DIR/.env.example" "$ENV_FILE" 2>/dev/null || touch "$ENV_FILE"
fi

# Function to update or add env var
update_env() {
    local key="$1"
    local value="$2"
    # Remove existing line and append new one (safer than sed with special chars)
    grep -v "^${key}=" "$ENV_FILE" > "$ENV_FILE.tmp" 2>/dev/null || true
    mv "$ENV_FILE.tmp" "$ENV_FILE"
    echo "${key}=${value}" >> "$ENV_FILE"
}

update_env "COGNITO_USER_POOL_ID" "$COGNITO_USER_POOL_ID"
update_env "COGNITO_CLIENT_ID" "$COGNITO_CLIENT_ID"
update_env "COGNITO_CLIENT_SECRET" "$COGNITO_CLIENT_SECRET"
update_env "AGENTCORE_RUNTIME_ARN" "$AGENTCORE_RUNTIME_ARN"
update_env "MEMORY_ID" "$MEMORY_ID"
update_env "AWS_REGION" "$AWS_REGION"

# Add DynamoDB table names
update_env "USAGE_TABLE_NAME" "agentcore-usage-records"
update_env "FEEDBACK_TABLE_NAME" "agentcore-feedback"
update_env "GUARDRAIL_TABLE_NAME" "agentcore-guardrail-violations"

# Add Guardrail config (set in Step 1)
if [ -n "$GUARDRAIL_ID" ] && [ "$GUARDRAIL_ID" != "None" ] && [ "$GUARDRAIL_ID" != "null" ]; then
    update_env "GUARDRAIL_ID" "$GUARDRAIL_ID"
    update_env "GUARDRAIL_VERSION" "${GUARDRAIL_VERSION:-1}"
    echo -e "${GREEN}Guardrail config added to .env${NC}"
fi

# Remove old COGNITO_DOMAIN if present
sed -i.bak '/^COGNITO_DOMAIN=/d' "$ENV_FILE" 2>/dev/null || true
rm -f "$ENV_FILE.bak"

echo -e "${GREEN}.env file updated${NC}"

# Create secrets
echo -e "${YELLOW}Creating AWS Secrets Manager secret...${NC}"
./create-secrets.sh

# ============================================================================
# STEP 7: Deploy ChatApp
# ============================================================================
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Step 7: Deploy ChatApp to ECS${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

if [ "$SKIP_CHATAPP" = true ]; then
    echo -e "${YELLOW}Skipping chatapp deployment (--skip-chatapp)${NC}"
else
    cd "$CHATAPP_DIR"
    # Capture SERVICE_URL from deploy.sh output
    DEPLOY_OUTPUT=$(./deploy.sh | tee /dev/tty)
    SERVICE_URL=$(echo "$DEPLOY_OUTPUT" | grep "^DEPLOY_SERVICE_URL=" | cut -d'=' -f2)
fi

# ============================================================================
# COMPLETE
# ============================================================================
echo ""
echo -e "${BLUE}AWS Account:${NC} $AWS_ACCOUNT_ID"
echo -e "${BLUE}Region:${NC} $AWS_REGION"
echo ""
echo -e "${BLUE}AgentCore Runtime:${NC} $AGENTCORE_RUNTIME_ARN"
echo -e "${BLUE}AgentCore Memory:${NC} $MEMORY_ID"
echo -e "${BLUE}Cognito User Pool:${NC} $COGNITO_USER_POOL_ID"

if [ -n "$SERVICE_URL" ]; then
    echo ""
    echo -e "${BLUE}Application URL:${NC} $SERVICE_URL"
fi

echo ""
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}⚠️  Note: ECS deployments take 4-6 minutes to become fully available.${NC}"
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "${YELLOW}Next Steps:${NC}"
echo "  1. Create a user: cd chatapp/deploy && ./create-user.sh <username> <password> --admin"
if [ -n "$SERVICE_URL" ]; then
    echo "  2. Access: $SERVICE_URL"
else
    echo "  2. Access the Express Mode URL shown above"
fi
echo "  3. Log in with your user once the app is available"
echo ""

echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN} $SERVICE_URL ${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
