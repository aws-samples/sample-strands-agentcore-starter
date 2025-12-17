#!/bin/bash
# CDK Deployment Script for AgentCore Chat Application
# This script deploys all CDK stacks in the correct dependency order.
# All Docker builds are handled by AWS CodeBuild - no local Docker required.
#
# Usage: ./deploy-all.sh [options]
#   --region <region>    AWS region (default: us-east-1)
#   --profile <profile>  AWS CLI profile to use
#   --dry-run            Show what would be deployed without deploying
#   -h, --help           Show this help message

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

# Default configuration
AWS_REGION="${AWS_REGION:-us-east-1}"
AWS_PROFILE=""
DRY_RUN=false

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
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        -h|--help)
            echo "Usage: ./deploy-all.sh [options]"
            echo ""
            echo "Options:"
            echo "  --region <region>    AWS region (default: us-east-1)"
            echo "  --profile <profile>  AWS CLI profile to use"
            echo "  --dry-run            Show what would be deployed without deploying"
            echo "  -h, --help           Show this help message"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

echo -e "${CYAN}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║     AgentCore Chat Application - CDK Deployment            ║${NC}"
echo -e "${CYAN}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Set AWS profile if provided
if [ -n "$AWS_PROFILE" ]; then
    export AWS_PROFILE
    echo -e "${YELLOW}Using AWS Profile: $AWS_PROFILE${NC}"
fi

# Get AWS account ID
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text 2>/dev/null || echo "unknown")
if [ "$AWS_ACCOUNT_ID" = "unknown" ]; then
    echo -e "${RED}Error: Could not get AWS account ID. Check your AWS credentials.${NC}"
    exit 1
fi

# Export environment variables for CDK
export AWS_REGION
export CDK_DEFAULT_REGION="$AWS_REGION"
export CDK_DEFAULT_ACCOUNT="$AWS_ACCOUNT_ID"

echo -e "${YELLOW}Configuration:${NC}"
echo "  AWS Account: $AWS_ACCOUNT_ID"
echo "  AWS Region: $AWS_REGION"
echo "  Dry Run: $DRY_RUN"
echo ""

if [ "$DRY_RUN" = true ]; then
    echo -e "${CYAN}DRY RUN MODE - No resources will be deployed${NC}"
    echo ""
fi

# Change to CDK directory
cd "$SCRIPT_DIR"

APP_NAME="htmx-chatapp"

# ============================================================================
# STEP 1: Install dependencies and build
# ============================================================================
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Step 1: Install dependencies and build${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

if [ ! -d "node_modules" ]; then
    echo -e "${YELLOW}Installing npm dependencies...${NC}"
    npm install
fi

echo -e "${YELLOW}Building TypeScript...${NC}"
npm run build

echo -e "${GREEN}Build complete${NC}"

# ============================================================================
# STEP 2: Bootstrap CDK (if needed)
# ============================================================================
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Step 2: Bootstrap CDK (if needed)${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# Check if CDK is bootstrapped
BOOTSTRAP_STACK=$(aws cloudformation describe-stacks \
    --stack-name CDKToolkit \
    --region "$AWS_REGION" \
    --query 'Stacks[0].StackStatus' \
    --output text 2>/dev/null || echo "NOT_FOUND")

if [ "$BOOTSTRAP_STACK" = "NOT_FOUND" ]; then
    echo -e "${YELLOW}CDK not bootstrapped. Running cdk bootstrap...${NC}"
    if [ "$DRY_RUN" != true ]; then
        npx cdk bootstrap "aws://$AWS_ACCOUNT_ID/$AWS_REGION"
    else
        echo -e "${CYAN}[DRY RUN] Would run: cdk bootstrap aws://$AWS_ACCOUNT_ID/$AWS_REGION${NC}"
    fi
else
    echo -e "${GREEN}CDK already bootstrapped${NC}"
fi

# ============================================================================
# STEP 2b: Ensure ECS service-linked role exists
# ============================================================================
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Step 2b: Ensure ECS service-linked role exists${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# Create ECS service-linked role if it doesn't exist (required for new AWS accounts)
if [ "$DRY_RUN" != true ]; then
    if aws iam create-service-linked-role --aws-service-name ecs.amazonaws.com 2>/dev/null; then
        echo -e "${GREEN}ECS service-linked role created${NC}"
    else
        echo -e "${GREEN}ECS service-linked role already exists${NC}"
    fi
else
    echo -e "${CYAN}[DRY RUN] Would ensure ECS service-linked role exists${NC}"
fi

# ============================================================================
# STEP 3: Synthesize CloudFormation templates
# ============================================================================
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Step 3: Synthesize CloudFormation templates${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

echo -e "${YELLOW}Synthesizing stacks...${NC}"
npx cdk synth --quiet

echo -e "${GREEN}Synthesis complete${NC}"

# ============================================================================
# STEP 4: Deploy Foundation stack (no dependencies)
# ============================================================================
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Step 4: Deploy Foundation stack${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# Consolidated stack deployment order:
# Phase 1: Foundation (no dependencies)
# Phase 2: Bedrock (depends on Foundation for secret updates)
# Phase 3: Agent (depends on Bedrock, Foundation) - includes CodeBuild for agent image
# Phase 4: ChatApp (depends on Foundation, Agent) - includes CodeBuild for chatapp image

if [ "$DRY_RUN" = true ]; then
    echo -e "${CYAN}[DRY RUN] Would deploy Foundation stack${NC}"
    echo ""
    echo -e "${YELLOW}Stacks that would be deployed:${NC}"
    npx cdk list
else
    echo -e "${YELLOW}Deploying Foundation stack...${NC}"
    echo ""
    
    npx cdk deploy \
        "${APP_NAME}-Foundation" \
        --require-approval never
    
    echo -e "${GREEN}Foundation stack deployed${NC}"
fi

# ============================================================================
# STEP 4b: Deploy Bedrock stack (depends on Foundation)
# ============================================================================
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Step 4b: Deploy Bedrock stack${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

if [ "$DRY_RUN" != true ]; then
    echo -e "${YELLOW}Deploying Bedrock stack...${NC}"
    echo ""
    
    npx cdk deploy \
        "${APP_NAME}-Bedrock" \
        --require-approval never
    
    echo -e "${GREEN}Bedrock stack deployed${NC}"
else
    echo -e "${CYAN}[DRY RUN] Would deploy Bedrock stack${NC}"
fi

# ============================================================================
# STEP 5: Deploy Agent stack (depends on Bedrock)
# ============================================================================
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Step 5: Deploy Agent stack${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

if [ "$DRY_RUN" != true ]; then
    echo -e "${YELLOW}Deploying Agent stack...${NC}"
    echo ""
    
    npx cdk deploy \
        "${APP_NAME}-Agent" \
        --require-approval never
    
    echo -e "${GREEN}Agent stack deployed${NC}"
else
    echo -e "${CYAN}[DRY RUN] Would deploy Agent stack${NC}"
fi

# ============================================================================
# STEP 6: Deploy ChatApp stack (depends on Foundation, Agent)
# Note: ChatApp stack includes CodeBuild for building the Docker image
# ============================================================================
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Step 7: Deploy ChatApp stack${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

if [ "$DRY_RUN" != true ]; then
    echo -e "${YELLOW}Deploying ChatApp stack (includes CodeBuild for Docker image)...${NC}"
    echo ""
    
    npx cdk deploy \
        "${APP_NAME}-ChatApp" \
        --require-approval never --outputs-file cdk-outputs.json
    
    echo -e "${GREEN}ChatApp stack deployed${NC}"
else
    echo -e "${CYAN}[DRY RUN] Would deploy ChatApp stack${NC}"
fi

# ============================================================================
# STEP 7: Display outputs and next steps
# ============================================================================
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Deployment Summary${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

if [ "$DRY_RUN" != true ]; then
    echo ""
    echo -e "${BLUE}AWS Account:${NC} $AWS_ACCOUNT_ID"
    echo -e "${BLUE}Region:${NC} $AWS_REGION"
    echo ""
    echo -e "${BLUE}Deployed Stacks:${NC}"
    echo "  1. ${APP_NAME}-Foundation (Cognito, DynamoDB, IAM, Secrets)"
    echo "  2. ${APP_NAME}-Bedrock (Guardrail, Knowledge Base, Memory)"
    echo "  3. ${APP_NAME}-Agent (ECR, CodeBuild, Runtime, Observability)"
    echo "  4. ${APP_NAME}-ChatApp (ECS Express Mode)"
    
    # Get the real service URL from ECS Express Mode API
    ECS_SERVICE_NAME="htmx-chatapp-express"
    SERVICE_URL=""
    
    echo ""
    echo -e "${YELLOW}Fetching service URL from ECS Express Mode...${NC}"
    
    # Get the service ARN first
    SERVICE_ARN=$(aws ecs list-services \
        --cluster default \
        --region "$AWS_REGION" \
        --query "serviceArns[?contains(@, '${ECS_SERVICE_NAME}')]" \
        --output text 2>/dev/null | head -1 || echo "")
    
    # Use describe-express-gateway-service to get the actual endpoint URL
    if [ -n "$SERVICE_ARN" ] && [ "$SERVICE_ARN" != "None" ]; then
        # Wait for URL to be available (up to 60 seconds)
        for i in {1..12}; do
            SERVICE_INFO=$(aws ecs describe-express-gateway-service \
                --service-arn "$SERVICE_ARN" \
                --region "$AWS_REGION" 2>/dev/null || echo "")
            
            if [ -n "$SERVICE_INFO" ]; then
                SERVICE_URL=$(echo "$SERVICE_INFO" | jq -r '.service.activeConfigurations[0].ingressPaths[0].endpoint // empty' 2>/dev/null || echo "")
                
                if [ -n "$SERVICE_URL" ]; then
                    break
                fi
            fi
            echo -n "."
            sleep 5
        done
        echo ""
    fi
    
    # Display URL or fallback message
    if [ -n "$SERVICE_URL" ]; then
        echo ""
        echo -e "${GREEN}Application URL:${NC} https://$SERVICE_URL"
    else
        echo -e "${YELLOW}Note: URL not yet available. Service may still be initializing.${NC}"
        echo -e "${YELLOW}Get the URL with:${NC}"
        echo "  aws ecs describe-express-gateway-service --service-arn \"$SERVICE_ARN\" --region $AWS_REGION --query 'service.activeConfigurations[0].ingressPaths[0].endpoint' --output text"
    fi
    
    echo ""
    echo -e "${CYAN}╔════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║           CDK Deployment Complete!                         ║${NC}"
    echo -e "${CYAN}╚════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${YELLOW}⚠️  Note: ECS deployments take 4-6 minutes to become fully available.${NC}"
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    echo -e "${YELLOW}Next Steps:${NC}"
    echo "  1. Create a user: cd ../chatapp/deploy && ./create-user.sh <email> <password> --admin"
    echo "  2. Wait for ECS service to be healthy (check AWS Console)"
    if [ -n "$SERVICE_URL" ]; then
        echo "  3. Access the application URL: https://$SERVICE_URL"
    else
        echo "  3. Get the URL once available using the command above"
    fi
    echo ""
    echo -e "${YELLOW}Useful Commands:${NC}"
    echo "  View stack outputs:  cat cdk-outputs.json"
    echo "  Update a stack:      npx cdk deploy <StackName>"
    echo "  Destroy all stacks:  ./destroy-all.sh"
    echo ""
else
    echo -e "${CYAN}DRY RUN complete. No resources were deployed.${NC}"
    echo "Run without --dry-run to perform actual deployment."
fi
