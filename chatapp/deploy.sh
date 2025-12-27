#!/bin/bash
# Quick deploy script for ChatApp code changes (no infrastructure changes)
# This bypasses CDK and directly uploads code, builds, and deploys to ECS.
#
# Usage: ./deploy.sh [options]
#   --region <region>    AWS region (default: us-east-1)
#   --profile <profile>  AWS CLI profile to use
#   --skip-build         Skip CodeBuild, just force ECS redeployment
#   --wait               Wait for deployment to complete
#   -h, --help           Show this help message

set -e

# Disable AWS CLI pager
export AWS_PAGER=""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# Defaults
AWS_REGION="${AWS_REGION:-us-east-1}"
AWS_PROFILE=""
SKIP_BUILD=false
WAIT=false
APP_NAME="htmx-chatapp"
SERVICE_NAME="htmx-chatapp-express"
CODEBUILD_PROJECT="${APP_NAME}-chatapp-build"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --region)
            AWS_REGION="$2"
            shift 2
            ;;
        --profile)
            AWS_PROFILE="$2"
            shift 2
            ;;
        --skip-build)
            SKIP_BUILD=true
            shift
            ;;
        --wait)
            WAIT=true
            shift
            ;;
        -h|--help)
            echo "Usage: ./deploy.sh [options]"
            echo ""
            echo "Quick deploy for ChatApp code changes (no infrastructure changes)"
            echo ""
            echo "Options:"
            echo "  --region <region>    AWS region (default: us-east-1)"
            echo "  --profile <profile>  AWS CLI profile to use"
            echo "  --skip-build         Skip CodeBuild, just force ECS redeployment"
            echo "  --wait               Wait for deployment to complete"
            echo "  -h, --help           Show this help message"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

# Set AWS profile if provided
if [ -n "$AWS_PROFILE" ]; then
    export AWS_PROFILE
    echo -e "${YELLOW}Using AWS Profile: $AWS_PROFILE${NC}"
fi

# Get AWS account ID
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text 2>/dev/null || echo "")
if [ -z "$AWS_ACCOUNT_ID" ]; then
    echo -e "${RED}Error: Could not get AWS account ID. Check your AWS credentials.${NC}"
    exit 1
fi

# Construct S3 bucket name
S3_BUCKET="${APP_NAME}-chatapp-source-${AWS_ACCOUNT_ID}-${AWS_REGION}"

echo -e "${CYAN}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║           ChatApp Quick Deploy                             ║${NC}"
echo -e "${CYAN}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${YELLOW}Configuration:${NC}"
echo "  AWS Account: $AWS_ACCOUNT_ID"
echo "  AWS Region: $AWS_REGION"
echo "  S3 Bucket: $S3_BUCKET"
echo "  Skip Build: $SKIP_BUILD"
echo ""

# Get script directory and chatapp directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHATAPP_DIR="$SCRIPT_DIR"

# Step 1: Upload code to S3
echo -e "${CYAN}Step 1: Uploading code to S3...${NC}"
aws s3 sync "$CHATAPP_DIR" "s3://${S3_BUCKET}/chatapp-source/" \
    --exclude ".venv/*" \
    --exclude "venv/*" \
    --exclude "__pycache__/*" \
    --exclude "*.pyc" \
    --exclude ".git/*" \
    --exclude "node_modules/*" \
    --exclude ".env" \
    --exclude "*.egg-info/*" \
    --exclude ".pytest_cache/*" \
    --exclude ".mypy_cache/*" \
    --exclude ".ruff_cache/*" \
    --exclude "deploy/*" \
    --exclude "*.log" \
    --exclude ".DS_Store" \
    --exclude "tests/*" \
    --region "$AWS_REGION" \
    --delete

echo -e "${GREEN}✓ Code uploaded to S3${NC}"

if [ "$SKIP_BUILD" = false ]; then
    # Step 2: Trigger CodeBuild
    echo ""
    echo -e "${CYAN}Step 2: Triggering CodeBuild...${NC}"
    BUILD_ID=$(aws codebuild start-build \
        --project-name "$CODEBUILD_PROJECT" \
        --region "$AWS_REGION" \
        --query 'build.id' \
        --output text)
    
    echo -e "${GREEN}✓ CodeBuild started: $BUILD_ID${NC}"
    
    # Step 3: Wait for build to complete
    echo ""
    echo -e "${CYAN}Step 3: Waiting for build to complete...${NC}"
    
    while true; do
        BUILD_STATUS=$(aws codebuild batch-get-builds \
            --ids "$BUILD_ID" \
            --region "$AWS_REGION" \
            --query 'builds[0].buildStatus' \
            --output text)
        
        case $BUILD_STATUS in
            SUCCEEDED)
                echo -e "${GREEN}✓ Build succeeded${NC}"
                break
                ;;
            FAILED|FAULT|STOPPED|TIMED_OUT)
                echo -e "${RED}✗ Build failed with status: $BUILD_STATUS${NC}"
                echo "View logs: https://${AWS_REGION}.console.aws.amazon.com/codesuite/codebuild/projects/${CODEBUILD_PROJECT}/build/${BUILD_ID}"
                exit 1
                ;;
            *)
                echo -n "."
                sleep 10
                ;;
        esac
    done
fi

# Step 4: Force ECS deployment
echo ""
echo -e "${CYAN}Step 4: Forcing ECS deployment...${NC}"
aws ecs update-service \
    --cluster default \
    --service "$SERVICE_NAME" \
    --force-new-deployment \
    --region "$AWS_REGION" \
    --query 'service.serviceName' \
    --output text > /dev/null

echo -e "${GREEN}✓ ECS deployment triggered${NC}"

if [ "$WAIT" = true ]; then
    echo ""
    echo -e "${CYAN}Waiting for deployment to stabilize...${NC}"
    aws ecs wait services-stable \
        --cluster default \
        --services "$SERVICE_NAME" \
        --region "$AWS_REGION"
    echo -e "${GREEN}✓ Deployment complete${NC}"
fi

# Get service URL
echo ""
SERVICE_ARN=$(aws ecs list-services \
    --cluster default \
    --region "$AWS_REGION" \
    --query "serviceArns[?contains(@, '${SERVICE_NAME}')]" \
    --output text 2>/dev/null | head -1 || echo "")

if [ -n "$SERVICE_ARN" ]; then
    SERVICE_URL=$(aws ecs describe-express-gateway-service \
        --service-arn "$SERVICE_ARN" \
        --region "$AWS_REGION" \
        --query 'service.activeConfigurations[0].ingressPaths[0].endpoint' \
        --output text 2>/dev/null || echo "")
    
    if [ -n "$SERVICE_URL" ] && [ "$SERVICE_URL" != "None" ]; then
        echo -e "${GREEN}Application URL: https://${SERVICE_URL}${NC}"
    fi
fi

echo ""
echo -e "${GREEN}Deploy complete!${NC}"
