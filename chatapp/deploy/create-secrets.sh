#!/bin/bash
# Create AWS Secrets Manager secret for HTMX ChatApp
# Usage: ./create-secrets.sh

set -e

# Disable AWS CLI pager
export AWS_PAGER=""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

SECRET_NAME="htmx-chatapp/config"
AWS_REGION="${AWS_REGION:-us-east-1}"

echo -e "${YELLOW}Creating secrets for HTMX ChatApp...${NC}"

# Determine script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHATAPP_DIR="$(dirname "$SCRIPT_DIR")"

# Check if .env file exists
if [ ! -f "$CHATAPP_DIR/.env" ]; then
    echo -e "${RED}Error: .env file not found in chatapp directory${NC}"
    echo "Expected location: $CHATAPP_DIR/.env"
    echo "Please create a .env file with the required configuration"
    exit 1
fi

# Source the .env file
source "$CHATAPP_DIR/.env"

# Validate required variables
required_vars=(
    "COGNITO_USER_POOL_ID"
    "COGNITO_CLIENT_ID"
    "COGNITO_CLIENT_SECRET"
    "AGENTCORE_RUNTIME_ARN"
    "MEMORY_ID"
    "USAGE_TABLE_NAME"
    "FEEDBACK_TABLE_NAME"
    "GUARDRAIL_TABLE_NAME"
)

for var in "${required_vars[@]}"; do
    if [ -z "${!var}" ]; then
        echo -e "${RED}Error: Required variable $var is not set${NC}"
        exit 1
    fi
done

# Set defaults
AWS_REGION="${AWS_REGION:-us-east-1}"
APP_URL="${APP_URL:-}"

# Check if secret already exists
if aws secretsmanager describe-secret --secret-id "$SECRET_NAME" --region "$AWS_REGION" 2>/dev/null; then
    echo -e "${YELLOW}Secret already exists. Updating...${NC}"
    
    aws secretsmanager put-secret-value \
        --secret-id "$SECRET_NAME" \
        --region "$AWS_REGION" \
        --secret-string "{
            \"cognito_user_pool_id\": \"$COGNITO_USER_POOL_ID\",
            \"cognito_client_id\": \"$COGNITO_CLIENT_ID\",
            \"cognito_client_secret\": \"$COGNITO_CLIENT_SECRET\",
            \"agentcore_runtime_arn\": \"$AGENTCORE_RUNTIME_ARN\",
            \"memory_id\": \"$MEMORY_ID\",
            \"aws_region\": \"$AWS_REGION\",
            \"app_url\": \"$APP_URL\",
            \"usage_table_name\": \"$USAGE_TABLE_NAME\",
            \"feedback_table_name\": \"$FEEDBACK_TABLE_NAME\",
            \"guardrail_table_name\": \"$GUARDRAIL_TABLE_NAME\",
            \"guardrail_id\": \"${GUARDRAIL_ID:-}\",
            \"guardrail_version\": \"${GUARDRAIL_VERSION:-DRAFT}\"
        }"
    
    echo -e "${GREEN}Secret updated successfully!${NC}"
else
    echo -e "${YELLOW}Creating new secret...${NC}"
    
    aws secretsmanager create-secret \
        --name "$SECRET_NAME" \
        --region "$AWS_REGION" \
        --description "Configuration for HTMX ChatApp" \
        --secret-string "{
            \"cognito_user_pool_id\": \"$COGNITO_USER_POOL_ID\",
            \"cognito_client_id\": \"$COGNITO_CLIENT_ID\",
            \"cognito_client_secret\": \"$COGNITO_CLIENT_SECRET\",
            \"agentcore_runtime_arn\": \"$AGENTCORE_RUNTIME_ARN\",
            \"memory_id\": \"$MEMORY_ID\",
            \"aws_region\": \"$AWS_REGION\",
            \"app_url\": \"$APP_URL\",
            \"usage_table_name\": \"$USAGE_TABLE_NAME\",
            \"feedback_table_name\": \"$FEEDBACK_TABLE_NAME\",
            \"guardrail_table_name\": \"$GUARDRAIL_TABLE_NAME\",
            \"guardrail_id\": \"${GUARDRAIL_ID:-}\",
            \"guardrail_version\": \"${GUARDRAIL_VERSION:-DRAFT}\"
        }"
    
    echo -e "${GREEN}Secret created successfully!${NC}"
fi

echo ""
echo -e "${GREEN}Secret ARN:${NC}"
aws secretsmanager describe-secret --secret-id "$SECRET_NAME" --region "$AWS_REGION" --query 'ARN' --output text
