#!/bin/bash
# Set up AWS Cognito User Pool for HTMX ChatApp
# Usage: ./setup-cognito.sh [--yes]
#
# Options:
#   --yes    Auto-confirm all prompts (non-interactive mode)
#
# This script creates:
# - Cognito User Pool with email sign-in (admin-only user creation)
# - User Pool Client with USER_PASSWORD_AUTH for direct login
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
APP_NAME="htmx-chatapp"
POOL_NAME="${APP_NAME}-users"

echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║           Cognito Setup for HTMX ChatApp                   ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${YELLOW}Configuration:${NC}"
echo "  Region: $AWS_REGION"
echo ""

# Step 1: Create User Pool
echo -e "${YELLOW}Step 1: Creating Cognito User Pool...${NC}"

# Check if pool already exists
EXISTING_POOL=$(aws cognito-idp list-user-pools --max-results 60 --region "$AWS_REGION" \
    --query "UserPools[?Name=='$POOL_NAME'].Id" --output text 2>/dev/null || echo "")

if [ -n "$EXISTING_POOL" ]; then
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

# Step 2: Create Admin group
echo -e "\n${YELLOW}Step 2: Creating Admin group...${NC}"

ADMIN_GROUP_NAME="Admin"

# Check if group already exists
EXISTING_GROUP=$(aws cognito-idp get-group \
    --user-pool-id "$USER_POOL_ID" \
    --group-name "$ADMIN_GROUP_NAME" \
    --region "$AWS_REGION" \
    --query 'Group.GroupName' \
    --output text 2>/dev/null || echo "")

if [ -n "$EXISTING_GROUP" ] && [ "$EXISTING_GROUP" != "None" ]; then
    echo -e "${GREEN}Admin group already exists${NC}"
else
    aws cognito-idp create-group \
        --user-pool-id "$USER_POOL_ID" \
        --group-name "$ADMIN_GROUP_NAME" \
        --description "Administrators with access to usage analytics dashboard" \
        --region "$AWS_REGION" > /dev/null
    echo -e "${GREEN}Created Admin group${NC}"
fi

# Step 3: Create User Pool Client (with USER_PASSWORD_AUTH for direct login)
echo -e "\n${YELLOW}Step 3: Creating User Pool Client...${NC}"

CLIENT_NAME="${APP_NAME}-client"

# Check if client already exists
EXISTING_CLIENT=$(aws cognito-idp list-user-pool-clients --user-pool-id "$USER_POOL_ID" --region "$AWS_REGION" \
    --query "UserPoolClients[?ClientName=='$CLIENT_NAME'].ClientId" --output text 2>/dev/null || echo "")

# Token validity settings (8 hours for access/ID tokens, 30 days for refresh)
ACCESS_TOKEN_VALIDITY=480  # 8 hours in minutes
ID_TOKEN_VALIDITY=480      # 8 hours in minutes
REFRESH_TOKEN_VALIDITY=30  # 30 days

if [ -n "$EXISTING_CLIENT" ]; then
    echo -e "${GREEN}Client already exists: $EXISTING_CLIENT${NC}"
    CLIENT_ID="$EXISTING_CLIENT"
    
    # Get client secret
    CLIENT_SECRET=$(aws cognito-idp describe-user-pool-client \
        --user-pool-id "$USER_POOL_ID" \
        --client-id "$CLIENT_ID" \
        --region "$AWS_REGION" \
        --query 'UserPoolClient.ClientSecret' \
        --output text)
    
    # Update client to ensure USER_PASSWORD_AUTH is enabled and set token validity
    echo -e "${YELLOW}Updating client settings (auth flows, 8-hour token validity)...${NC}"
    aws cognito-idp update-user-pool-client \
        --user-pool-id "$USER_POOL_ID" \
        --client-id "$CLIENT_ID" \
        --region "$AWS_REGION" \
        --explicit-auth-flows "ALLOW_REFRESH_TOKEN_AUTH" "ALLOW_USER_PASSWORD_AUTH" \
        --access-token-validity "$ACCESS_TOKEN_VALIDITY" \
        --id-token-validity "$ID_TOKEN_VALIDITY" \
        --refresh-token-validity "$REFRESH_TOKEN_VALIDITY" \
        --token-validity-units "AccessToken=minutes,IdToken=minutes,RefreshToken=days" \
        > /dev/null
    echo -e "${GREEN}Client updated with 8-hour session timeout${NC}"
else
    # Create client with USER_PASSWORD_AUTH for direct login (no hosted UI needed)
    CLIENT_RESULT=$(aws cognito-idp create-user-pool-client \
        --user-pool-id "$USER_POOL_ID" \
        --client-name "$CLIENT_NAME" \
        --region "$AWS_REGION" \
        --generate-secret \
        --explicit-auth-flows "ALLOW_REFRESH_TOKEN_AUTH" "ALLOW_USER_PASSWORD_AUTH" \
        --access-token-validity "$ACCESS_TOKEN_VALIDITY" \
        --id-token-validity "$ID_TOKEN_VALIDITY" \
        --refresh-token-validity "$REFRESH_TOKEN_VALIDITY" \
        --token-validity-units "AccessToken=minutes,IdToken=minutes,RefreshToken=days" \
        --query 'UserPoolClient.[ClientId,ClientSecret]' \
        --output text)
    
    CLIENT_ID=$(echo "$CLIENT_RESULT" | awk '{print $1}')
    CLIENT_SECRET=$(echo "$CLIENT_RESULT" | awk '{print $2}')
    echo -e "${GREEN}Created client with 8-hour session timeout: $CLIENT_ID${NC}"
fi

# Step 4: Output configuration
echo ""
echo -e "${GREEN}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║           Cognito Setup Complete!                          ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${BLUE}Add these values to your .env file:${NC}"
echo ""
echo "COGNITO_USER_POOL_ID=${USER_POOL_ID}"
echo "COGNITO_CLIENT_ID=${CLIENT_ID}"
echo "COGNITO_CLIENT_SECRET=${CLIENT_SECRET}"
echo ""
echo -e "${YELLOW}Next Steps:${NC}"
echo "1. Update your chatapp/.env file with the values above"
echo "2. Create a user: ./deploy/create-user.sh <email> [password] [--admin]"
echo "3. Run ./deploy/create-secrets.sh to store config in AWS"
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
        # Update or add values
        if grep -q "^COGNITO_USER_POOL_ID=" "$ENV_FILE"; then
            sed -i.bak "s|^COGNITO_USER_POOL_ID=.*|COGNITO_USER_POOL_ID=${USER_POOL_ID}|" "$ENV_FILE"
        else
            echo "COGNITO_USER_POOL_ID=${USER_POOL_ID}" >> "$ENV_FILE"
        fi
        
        if grep -q "^COGNITO_CLIENT_ID=" "$ENV_FILE"; then
            sed -i.bak "s|^COGNITO_CLIENT_ID=.*|COGNITO_CLIENT_ID=${CLIENT_ID}|" "$ENV_FILE"
        else
            echo "COGNITO_CLIENT_ID=${CLIENT_ID}" >> "$ENV_FILE"
        fi
        
        if grep -q "^COGNITO_CLIENT_SECRET=" "$ENV_FILE"; then
            sed -i.bak "s|^COGNITO_CLIENT_SECRET=.*|COGNITO_CLIENT_SECRET=${CLIENT_SECRET}|" "$ENV_FILE"
        else
            echo "COGNITO_CLIENT_SECRET=${CLIENT_SECRET}" >> "$ENV_FILE"
        fi
        
        # Remove old COGNITO_DOMAIN if present
        sed -i.bak '/^COGNITO_DOMAIN=/d' "$ENV_FILE"
        
        rm -f "$ENV_FILE.bak"
        echo -e "${GREEN}.env file updated!${NC}"
    fi
fi
