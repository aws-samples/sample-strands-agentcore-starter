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

APP_NAME="htmx-chatapp"

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

# Clean up CloudWatch log groups that may have been created outside CDK
echo -e "${YELLOW}Cleaning up CloudWatch log groups...${NC}"

LOG_GROUPS=(
    "/ecs/${APP_NAME}-express"
    "/aws/bedrock-agentcore/runtimes"
)

for LOG_GROUP in "${LOG_GROUPS[@]}"; do
    if [ "$DRY_RUN" = true ]; then
        echo -e "${CYAN}[DRY RUN] Would check and delete log group: $LOG_GROUP${NC}"
    else
        # Check if log group exists and delete it
        if aws logs describe-log-groups --log-group-name-prefix "$LOG_GROUP" --region "$AWS_REGION" --query 'logGroups[0]' --output text 2>/dev/null | grep -q "$LOG_GROUP"; then
            aws logs delete-log-group --log-group-name "$LOG_GROUP" --region "$AWS_REGION" 2>/dev/null || true
            echo -e "${GREEN}Deleted log group: $LOG_GROUP${NC}"
        fi
    fi
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
