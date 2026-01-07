#!/bin/bash
# Quick deploy script for ChatApp code changes (no infrastructure changes)
# This bypasses CDK and directly uploads code, builds, and deploys.
#
# Supports both ECS Express Gateway and Lambda Function URL deployments.
#
# Usage: ./deploy.sh [options]
#   --region <region>    AWS region (default: us-east-1)
#   --profile <profile>  AWS CLI profile to use
#   --target <target>    Deployment target: ecs, lambda, or both (default: ecs)
#   --skip-build         Skip CodeBuild, just force redeployment
#   --wait               Wait for deployment to complete
#   -h, --help           Show this help message
#
# Examples:
#   ./deploy.sh --target ecs              # Deploy to ECS only
#   ./deploy.sh --target lambda           # Deploy to Lambda only
#   ./deploy.sh --target both             # Deploy to both ECS and Lambda
#   ./deploy.sh --target lambda --wait    # Deploy to Lambda and wait

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
TARGET="ecs"
SKIP_BUILD=false
WAIT=false
APP_NAME="htmx-chatapp"

# ECS configuration
ECS_SERVICE_NAME="htmx-chatapp-express"
ECS_CODEBUILD_PROJECT="${APP_NAME}-chatapp-ecs-build"

# Lambda configuration
LAMBDA_FUNCTION_NAME="htmx-chatapp-lambda"
LAMBDA_CODEBUILD_PROJECT="${APP_NAME}-chatapp-lambda-build"

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
        --target)
            TARGET="$2"
            if [[ ! "$TARGET" =~ ^(ecs|lambda|both)$ ]]; then
                echo -e "${RED}Error: Invalid target '$TARGET'. Must be: ecs, lambda, or both${NC}"
                exit 1
            fi
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
            echo "  --target <target>    Deployment target: ecs, lambda, or both (default: ecs)"
            echo "  --skip-build         Skip CodeBuild, just force redeployment"
            echo "  --wait               Wait for deployment to complete"
            echo "  -h, --help           Show this help message"
            echo ""
            echo "Examples:"
            echo "  ./deploy.sh --target ecs              # Deploy to ECS only"
            echo "  ./deploy.sh --target lambda           # Deploy to Lambda only"
            echo "  ./deploy.sh --target both             # Deploy to both"
            echo "  ./deploy.sh --target lambda --wait    # Deploy to Lambda and wait"
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
echo "  Target: $TARGET"
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

# Function to run CodeBuild and wait for completion
run_codebuild() {
    local project_name="$1"
    local display_name="$2"
    
    echo ""
    echo -e "${CYAN}Triggering CodeBuild for ${display_name}...${NC}"
    BUILD_ID=$(aws codebuild start-build \
        --project-name "$project_name" \
        --region "$AWS_REGION" \
        --query 'build.id' \
        --output text 2>/dev/null || echo "")
    
    if [ -z "$BUILD_ID" ]; then
        echo -e "${RED}✗ Failed to start CodeBuild for ${display_name}. Project may not exist.${NC}"
        echo -e "${YELLOW}  Hint: Run CDK deploy with --ingress ${TARGET} first to create infrastructure.${NC}"
        return 1
    fi
    
    echo -e "${GREEN}✓ CodeBuild started: $BUILD_ID${NC}"
    
    echo -e "${CYAN}Waiting for ${display_name} build to complete...${NC}"
    
    while true; do
        BUILD_STATUS=$(aws codebuild batch-get-builds \
            --ids "$BUILD_ID" \
            --region "$AWS_REGION" \
            --query 'builds[0].buildStatus' \
            --output text)
        
        case $BUILD_STATUS in
            SUCCEEDED)
                echo -e "${GREEN}✓ ${display_name} build succeeded${NC}"
                return 0
                ;;
            FAILED|FAULT|STOPPED|TIMED_OUT)
                echo -e "${RED}✗ ${display_name} build failed with status: $BUILD_STATUS${NC}"
                echo "View logs: https://${AWS_REGION}.console.aws.amazon.com/codesuite/codebuild/projects/${project_name}/build/${BUILD_ID}"
                return 1
                ;;
            *)
                echo -n "."
                sleep 10
                ;;
        esac
    done
}

# Function to deploy to ECS
deploy_ecs() {
    echo ""
    echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
    echo -e "${CYAN}  Deploying to ECS Express Gateway${NC}"
    echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
    
    if [ "$SKIP_BUILD" = false ]; then
        run_codebuild "$ECS_CODEBUILD_PROJECT" "ECS" || return 1
    fi
    
    echo ""
    echo -e "${CYAN}Forcing ECS deployment...${NC}"
    aws ecs update-service \
        --cluster default \
        --service "$ECS_SERVICE_NAME" \
        --force-new-deployment \
        --region "$AWS_REGION" \
        --query 'service.serviceName' \
        --output text > /dev/null 2>&1 || {
            echo -e "${RED}✗ Failed to update ECS service. Service may not exist.${NC}"
            return 1
        }
    
    echo -e "${GREEN}✓ ECS deployment triggered${NC}"
    
    if [ "$WAIT" = true ]; then
        echo ""
        echo -e "${CYAN}Waiting for ECS deployment to stabilize...${NC}"
        aws ecs wait services-stable \
            --cluster default \
            --services "$ECS_SERVICE_NAME" \
            --region "$AWS_REGION"
        echo -e "${GREEN}✓ ECS deployment complete${NC}"
    fi
    
    # Get ECS service URL
    SERVICE_ARN=$(aws ecs list-services \
        --cluster default \
        --region "$AWS_REGION" \
        --query "serviceArns[?contains(@, '${ECS_SERVICE_NAME}')]" \
        --output text 2>/dev/null | head -1 || echo "")
    
    if [ -n "$SERVICE_ARN" ]; then
        SERVICE_URL=$(aws ecs describe-express-gateway-service \
            --service-arn "$SERVICE_ARN" \
            --region "$AWS_REGION" \
            --query 'service.activeConfigurations[0].ingressPaths[0].endpoint' \
            --output text 2>/dev/null || echo "")
        
        if [ -n "$SERVICE_URL" ] && [ "$SERVICE_URL" != "None" ]; then
            echo -e "${GREEN}ECS URL: https://${SERVICE_URL}${NC}"
        fi
    fi
}

# Function to deploy to Lambda
deploy_lambda() {
    echo ""
    echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
    echo -e "${CYAN}  Deploying to Lambda Function URL${NC}"
    echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
    
    if [ "$SKIP_BUILD" = false ]; then
        run_codebuild "$LAMBDA_CODEBUILD_PROJECT" "Lambda" || return 1
    fi
    
    echo ""
    echo -e "${CYAN}Updating Lambda function...${NC}"
    
    # Get ECR repository URI
    ECR_REPO_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${APP_NAME}"
    
    # Determine image tag based on deployment mode
    # Check if both ECS and Lambda are deployed (both mode uses different tags)
    ECS_EXISTS=$(aws ecs describe-services \
        --cluster default \
        --services "$ECS_SERVICE_NAME" \
        --region "$AWS_REGION" \
        --query 'services[0].status' \
        --output text 2>/dev/null || echo "")
    
    if [ "$ECS_EXISTS" = "ACTIVE" ] && [ "$TARGET" != "lambda" ]; then
        IMAGE_TAG="lambda-latest"
    else
        IMAGE_TAG="latest"
    fi
    
    # Update Lambda function with new image
    aws lambda update-function-code \
        --function-name "$LAMBDA_FUNCTION_NAME" \
        --image-uri "${ECR_REPO_URI}:${IMAGE_TAG}" \
        --region "$AWS_REGION" \
        --query 'FunctionName' \
        --output text > /dev/null 2>&1 || {
            echo -e "${RED}✗ Failed to update Lambda function. Function may not exist.${NC}"
            echo -e "${YELLOW}  Hint: Run CDK deploy with --ingress furl first to create infrastructure.${NC}"
            return 1
        }
    
    echo -e "${GREEN}✓ Lambda function update triggered${NC}"
    
    if [ "$WAIT" = true ]; then
        echo ""
        echo -e "${CYAN}Waiting for Lambda function update to complete...${NC}"
        aws lambda wait function-updated \
            --function-name "$LAMBDA_FUNCTION_NAME" \
            --region "$AWS_REGION"
        echo -e "${GREEN}✓ Lambda function update complete${NC}"
    fi
    
    # Get Lambda Function URL
    FUNCTION_URL=$(aws lambda get-function-url-config \
        --function-name "$LAMBDA_FUNCTION_NAME" \
        --region "$AWS_REGION" \
        --query 'FunctionUrl' \
        --output text 2>/dev/null || echo "")
    
    if [ -n "$FUNCTION_URL" ] && [ "$FUNCTION_URL" != "None" ]; then
        echo -e "${GREEN}Lambda URL: ${FUNCTION_URL}${NC}"
    fi
}

# Execute deployments based on target
DEPLOY_SUCCESS=true

case $TARGET in
    ecs)
        deploy_ecs || DEPLOY_SUCCESS=false
        ;;
    lambda)
        deploy_lambda || DEPLOY_SUCCESS=false
        ;;
    both)
        deploy_ecs || DEPLOY_SUCCESS=false
        deploy_lambda || DEPLOY_SUCCESS=false
        ;;
esac

echo ""
if [ "$DEPLOY_SUCCESS" = true ]; then
    echo -e "${GREEN}╔════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║           Deploy Complete!                                 ║${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════════════════════════╝${NC}"
else
    echo -e "${RED}╔════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${RED}║           Deploy completed with errors                     ║${NC}"
    echo -e "${RED}╚════════════════════════════════════════════════════════════╝${NC}"
    exit 1
fi
