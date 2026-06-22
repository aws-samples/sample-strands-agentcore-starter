#!/bin/bash
# CDK Destroy Script for AgentCore Chat Application
# This script destroys all CDK stacks in reverse dependency order.
#
# Usage: ./destroy-all.sh [options]
#   --region <region>    AWS region (default: us-east-1)
#   --profile <profile>  AWS CLI profile to use
#   --yes                Auto-confirm all prompts (DANGEROUS)
#   --dry-run            Show what would be destroyed without destroying
#   -h, --help           Show this help message

# Note: We don't use 'set -e' because we want to continue cleanup even if some operations fail

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
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Default configuration
AWS_REGION="${AWS_REGION:-us-east-1}"
AWS_PROFILE=""
AUTO_YES=false
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
        --yes|-y)
            AUTO_YES=true
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        -h|--help)
            echo "Usage: ./destroy-all.sh [options]"
            echo ""
            echo "Options:"
            echo "  --region <region>    AWS region (default: us-east-1)"
            echo "  --profile <profile>  AWS CLI profile to use"
            echo "  --yes                Auto-confirm all prompts (DANGEROUS)"
            echo "  --dry-run            Show what would be destroyed without destroying"
            echo "  -h, --help           Show this help message"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

echo -e "${RED}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${RED}║     AgentCore Chat Application - CDK DESTROY               ║${NC}"
echo -e "${RED}╚════════════════════════════════════════════════════════════╝${NC}"
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
    echo -e "${CYAN}DRY RUN MODE - No resources will be destroyed${NC}"
    echo ""
fi

# Confirmation prompt
if [ "$AUTO_YES" != true ] && [ "$DRY_RUN" != true ]; then
    echo -e "${RED}WARNING: This will permanently delete all CDK-managed resources!${NC}"
    echo ""
    echo -e "${YELLOW}The following stacks will be destroyed:${NC}"
    cd "$SCRIPT_DIR"
    npx cdk list 2>/dev/null || echo "  (Unable to list stacks)"
    echo ""
    echo -e "${YELLOW}Are you sure you want to continue? (type 'yes' to confirm)${NC}"
    read -r CONFIRM
    if [ "$CONFIRM" != "yes" ]; then
        echo "Destroy cancelled."
        exit 0
    fi
fi

# Change to CDK directory
cd "$SCRIPT_DIR"

APP_NAME="${APP_NAME:-htmx-chatapp}"

# ============================================================================
# STEP 0: Clean up CloudWatch Logs Deliveries (must be deleted before sources)
# ============================================================================
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Step 0: Clean up CloudWatch Logs Deliveries${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}Deleting deliveries before sources to avoid dependency errors...${NC}"

if [ "$DRY_RUN" = true ]; then
    echo -e "${CYAN}[DRY RUN] Would delete CloudWatch Logs deliveries${NC}"
else
    # Get all deliveries and delete them
    DELIVERY_IDS=$(aws logs describe-deliveries --region "$AWS_REGION" --query 'deliveries[*].id' --output text 2>/dev/null || echo "")
    
    if [ -n "$DELIVERY_IDS" ] && [ "$DELIVERY_IDS" != "None" ]; then
        for DELIVERY_ID in $DELIVERY_IDS; do
            echo -e "${YELLOW}Deleting delivery: $DELIVERY_ID${NC}"
            aws logs delete-delivery --id "$DELIVERY_ID" --region "$AWS_REGION" 2>/dev/null || true
        done
        echo -e "${GREEN}Deliveries deleted${NC}"
    else
        echo -e "${GREEN}No deliveries found to delete${NC}"
    fi
    
    # Also delete delivery sources (they may block deletion too)
    DELIVERY_SOURCES=$(aws logs describe-delivery-sources --region "$AWS_REGION" --query 'deliverySources[*].name' --output text 2>/dev/null || echo "")
    
    if [ -n "$DELIVERY_SOURCES" ] && [ "$DELIVERY_SOURCES" != "None" ]; then
        for SOURCE_NAME in $DELIVERY_SOURCES; do
            echo -e "${YELLOW}Deleting delivery source: $SOURCE_NAME${NC}"
            aws logs delete-delivery-source --name "$SOURCE_NAME" --region "$AWS_REGION" 2>/dev/null || true
        done
        echo -e "${GREEN}Delivery sources deleted${NC}"
    else
        echo -e "${GREEN}No delivery sources found to delete${NC}"
    fi
    
    # Delete delivery destinations too
    DELIVERY_DESTS=$(aws logs describe-delivery-destinations --region "$AWS_REGION" --query 'deliveryDestinations[*].name' --output text 2>/dev/null || echo "")
    
    if [ -n "$DELIVERY_DESTS" ] && [ "$DELIVERY_DESTS" != "None" ]; then
        for DEST_NAME in $DELIVERY_DESTS; do
            echo -e "${YELLOW}Deleting delivery destination: $DEST_NAME${NC}"
            aws logs delete-delivery-destination --name "$DEST_NAME" --region "$AWS_REGION" 2>/dev/null || true
        done
        echo -e "${GREEN}Delivery destinations deleted${NC}"
    else
        echo -e "${GREEN}No delivery destinations found to delete${NC}"
    fi
fi

echo ""

# ============================================================================
# STEP 1: Destroy all CDK stacks
# ============================================================================
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Step 1: Destroy all CDK stacks${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# CDK will handle the reverse dependency order automatically
# Stacks are destroyed in reverse order:
# 1. ChatApp (depends on Foundation, Agent)
# 2. Agent (depends on Bedrock)
# 3. Foundation, Bedrock (no dependencies)

if [ "$DRY_RUN" = true ]; then
    echo -e "${CYAN}[DRY RUN] Would destroy all stacks with: cdk destroy --all --force${NC}"
    echo ""
    echo -e "${YELLOW}Stacks that would be destroyed:${NC}"
    npx cdk list 2>/dev/null || echo "  (Unable to list stacks)"
else
    echo -e "${YELLOW}Destroying all stacks (this may take 10-15 minutes)...${NC}"
    echo ""
    echo -e "${YELLOW}Stack destruction order:${NC}"
    echo "  1. ${APP_NAME}-ChatApp (ECS Express Mode)"
    echo "  2. ${APP_NAME}-Agent (ECR, CodeBuild, Runtime, Observability)"
    echo "  3. ${APP_NAME}-Bedrock (Guardrail, Knowledge Base, Memory)"
    echo "  4. ${APP_NAME}-Foundation (Cognito, DynamoDB, IAM, Secrets)"
    echo ""
    
    # Destroy all stacks with force flag (no confirmation prompts)
    # CDK will handle the reverse dependency order automatically
    npx cdk destroy --all --force
    
    echo -e "${GREEN}All CDK stacks destroyed${NC}"
fi

# ============================================================================
# STEP 2: Clean up any remaining resources
# ============================================================================
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Step 2: Clean up remaining resources${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# Note: ECR repositories are now managed by CDK and deleted automatically

# Delete the ECS Express Gateway service.
# CloudFormation deletion of AWS::ECS::ExpressGatewayService does not always
# remove the underlying service, and a leftover service blocks a future
# redeploy with: "Resource of type 'AWS::ECS::ExpressGatewayService' ...
# already exists." So delete it explicitly here.
echo -e "${YELLOW}Cleaning up ECS Express Gateway service...${NC}"
if [ "$DRY_RUN" = true ]; then
    echo -e "${CYAN}[DRY RUN] Would delete ECS Express Gateway service '${APP_NAME}-express' if present${NC}"
else
    EXPRESS_SVC_ARN=$(aws ecs list-services \
        --cluster default \
        --region "$AWS_REGION" \
        --query "serviceArns[?contains(@, '${APP_NAME}-express')]" \
        --output text 2>/dev/null | head -1 || echo "")
    if [ -n "$EXPRESS_SVC_ARN" ] && [ "$EXPRESS_SVC_ARN" != "None" ]; then
        aws ecs delete-express-gateway-service \
            --service-arn "$EXPRESS_SVC_ARN" \
            --region "$AWS_REGION" >/dev/null 2>&1 \
            && echo -e "${GREEN}Deleted ECS Express Gateway service: ${EXPRESS_SVC_ARN}${NC}" \
            || echo -e "${YELLOW}Could not delete express service (may already be gone): ${EXPRESS_SVC_ARN}${NC}"
    else
        echo -e "${GREEN}No ECS Express Gateway service found to delete${NC}"
    fi
fi

# Clean up CloudWatch log groups left behind by deleted stacks.
# CDK-declared log groups and Lambda-auto-created log groups can survive a
# stack delete; if they have fixed names they then block a future deploy's
# change set (e.g. /aws/lambda/${APP_NAME}-ecs-build-waiter-provider). All
# stacks are already destroyed at this point, so prefix-based bulk deletion
# of app-owned groups is safe.
echo -e "${YELLOW}Cleaning up CloudWatch log groups...${NC}"

LOG_GROUP_PREFIXES=(
    "/aws/lambda/${APP_NAME}"
    "/ecs/${APP_NAME}"
    "/aws/vendedlogs/bedrock-agentcore"
    "/aws/bedrock-agentcore/runtimes"
)

for PREFIX in "${LOG_GROUP_PREFIXES[@]}"; do
    if [ "$DRY_RUN" = true ]; then
        echo -e "${CYAN}[DRY RUN] Would delete log groups with prefix: $PREFIX${NC}"
        continue
    fi
    LOG_GROUP_NAMES=$(aws logs describe-log-groups \
        --log-group-name-prefix "$PREFIX" \
        --region "$AWS_REGION" \
        --query 'logGroups[].logGroupName' \
        --output text 2>/dev/null || echo "")
    for LOG_GROUP in $LOG_GROUP_NAMES; do
        [ -z "$LOG_GROUP" ] && continue
        aws logs delete-log-group --log-group-name "$LOG_GROUP" --region "$AWS_REGION" 2>/dev/null \
            && echo -e "${GREEN}Deleted log group: $LOG_GROUP${NC}" || true
    done
done

# Clean up CDK outputs file
if [ -f "cdk-outputs.json" ]; then
    if [ "$DRY_RUN" = true ]; then
        echo -e "${CYAN}[DRY RUN] Would delete cdk-outputs.json${NC}"
    else
        rm -f cdk-outputs.json
        echo -e "${GREEN}Deleted cdk-outputs.json${NC}"
    fi
fi

# ============================================================================
# COMPLETE
# ============================================================================
echo ""
echo -e "${GREEN}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║           CDK Destroy Complete!                            ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""

if [ "$DRY_RUN" = true ]; then
    echo -e "${CYAN}This was a DRY RUN - no resources were actually destroyed.${NC}"
    echo -e "${CYAN}Run without --dry-run to perform actual cleanup.${NC}"
else
    echo -e "${CYAN}Summary of destroyed resources:${NC}"
    echo "  - ChatApp (ECS Express Mode, ECR, CodeBuild, S3 source bucket)"
    echo "  - Agent (ECR, CodeBuild, CfnRuntime, Observability)"
    echo "  - Bedrock (Guardrail, Knowledge Base, Memory)"
    echo "  - Foundation (Cognito, DynamoDB, IAM roles, Secrets)"
    echo "  - CloudWatch log groups"
    echo ""
    echo -e "${YELLOW}Note: Some resources may take a few minutes to fully delete.${NC}"
    echo ""
    echo -e "${YELLOW}To redeploy, run:${NC}"
    echo "  ./deploy-all.sh --region $AWS_REGION"
fi
