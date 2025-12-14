#!/bin/bash
# Create a user in Cognito User Pool
# Usage: ./create-user.sh <email> [password] [--admin]
#
# Options:
#   --admin    Add user to Admin group (grants access to admin dashboard)

set -e

# Disable AWS CLI pager
export AWS_PAGER=""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

AWS_REGION="${AWS_REGION:-us-east-1}"
APP_NAME="htmx-chatapp"
POOL_NAME="${APP_NAME}-users"
ADMIN_GROUP_NAME="Admin"

# Parse arguments
EMAIL=""
PASSWORD=""
IS_ADMIN=false

for arg in "$@"; do
    case $arg in
        --admin)
            IS_ADMIN=true
            ;;
        -*)
            echo -e "${RED}Unknown option: $arg${NC}"
            exit 1
            ;;
        *)
            if [ -z "$EMAIL" ]; then
                EMAIL="$arg"
            elif [ -z "$PASSWORD" ]; then
                PASSWORD="$arg"
            fi
            ;;
    esac
done

# Check arguments
if [ -z "$EMAIL" ]; then
    echo -e "${RED}Usage: ./create-user.sh <email> [password] [--admin]${NC}"
    echo "  email    - User's email address"
    echo "  password - Optional password (will prompt if not provided)"
    echo "  --admin  - Add user to Admin group"
    exit 1
fi

# Get User Pool ID
USER_POOL_ID=$(aws cognito-idp list-user-pools --max-results 60 --region "$AWS_REGION" \
    --query "UserPools[?Name=='$POOL_NAME'].Id" --output text)

if [ -z "$USER_POOL_ID" ]; then
    echo -e "${RED}Error: User Pool '$POOL_NAME' not found${NC}"
    echo "Run ./setup-cognito.sh first"
    exit 1
fi

echo -e "${YELLOW}Creating user in Cognito...${NC}"
echo "User Pool: $USER_POOL_ID"
echo "Email: $EMAIL"

# Prompt for password if not provided
if [ -z "$PASSWORD" ]; then
    echo -e "${YELLOW}Enter password (min 8 chars, uppercase, lowercase, number):${NC}"
    read -s PASSWORD
    echo ""
fi

# Create user with admin privileges (no email verification needed)
aws cognito-idp admin-create-user \
    --user-pool-id "$USER_POOL_ID" \
    --username "$EMAIL" \
    --user-attributes Name=email,Value="$EMAIL" Name=email_verified,Value=true \
    --message-action SUPPRESS \
    --region "$AWS_REGION" > /dev/null

# Set permanent password
aws cognito-idp admin-set-user-password \
    --user-pool-id "$USER_POOL_ID" \
    --username "$EMAIL" \
    --password "$PASSWORD" \
    --permanent \
    --region "$AWS_REGION"

# Add to Admin group if requested
if [ "$IS_ADMIN" = true ]; then
    echo -e "${YELLOW}Adding user to Admin group...${NC}"
    aws cognito-idp admin-add-user-to-group \
        --user-pool-id "$USER_POOL_ID" \
        --username "$EMAIL" \
        --group-name "$ADMIN_GROUP_NAME" \
        --region "$AWS_REGION"
    echo -e "${GREEN}User added to Admin group${NC}"
fi

echo -e "${GREEN}User created successfully!${NC}"
echo ""
echo "Email: $EMAIL"
if [ "$IS_ADMIN" = true ]; then
    echo "Role: Administrator (can access /admin dashboard)"
else
    echo "Role: Regular user"
fi
echo "You can now log in to the application."
