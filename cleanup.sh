#!/bin/bash
# Master cleanup script for AgentCore Chat Application
# This script removes all AWS resources created by setup.sh and deploy scripts:
#   1. ECS Express Mode service and related resources
#   2. ECR repository and images
#   3. Secrets Manager secret
#   4. IAM roles and policies
#   5. DynamoDB tables (usage, feedback, guardrails)
#   6. Bedrock Guardrail
#   7. Cognito User Pool
#   8. CloudWatch resources (log groups)
#   9. AgentCore agent and memory
#
# Usage: ./cleanup.sh [options]
#   --yes              Auto-confirm all prompts (DANGEROUS - will delete everything)
#   --skip-agent       Skip agent/memory deletion
#   --skip-chatapp     Skip chatapp resources deletion
#   --region <region>  AWS region (default: us-east-1)
#   --dry-run          Show what would be deleted without actually deleting

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
AGENT_DIR="$SCRIPT_DIR/agent"
CHATAPP_DIR="$SCRIPT_DIR/chatapp"

# Default configuration
AWS_REGION="${AWS_REGION:-us-east-1}"
AUTO_YES=false
SKIP_AGENT=false
SKIP_CHATAPP=false
DRY_RUN=false

# Resource names (must match setup scripts)
APP_NAME="htmx-chatapp"
EXPRESS_SERVICE_NAME="htmx-chatapp-express"
COGNITO_POOL_NAME="${APP_NAME}-users"
USAGE_TABLE_NAME="agentcore-usage-records"
FEEDBACK_TABLE_NAME="agentcore-feedback"
GUARDRAIL_TABLE_NAME="agentcore-guardrail-violations"
GUARDRAIL_NAME="agentcore-chatapp-guardrail"
SECRET_NAME="htmx-chatapp/config"
EXECUTION_ROLE_NAME="htmx-chatapp-execution-role"
TASK_ROLE_NAME="htmx-chatapp-task-role"
INFRA_ROLE_NAME="ecsInfrastructureRoleForExpressServices"
AGENT_NAME="chat_app"
MEMORY_NAME="=chat_app_mem"

while [[ $# -gt 0 ]]; do
    case $1 in
        --yes|-y)
            AUTO_YES=true
            shift
            ;;
        --skip-agent)
            SKIP_AGENT=true
            shift
            ;;
        --skip-chatapp)
            SKIP_CHATAPP=true
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --region)
            AWS_REGION="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: ./cleanup.sh [options]"
            echo ""
            echo "Options:"
            echo "  --yes              Auto-confirm all prompts (DANGEROUS)"
            echo "  --skip-agent       Skip agent/memory deletion"
            echo "  --skip-chatapp     Skip chatapp resources deletion"
            echo "  --region <region>  AWS region (default: us-east-1)"
            echo "  --dry-run          Show what would be deleted without deleting"
            echo "  -h, --help         Show this help message"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

echo -e "${RED}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${RED}║     AgentCore Chat Application - CLEANUP                   ║${NC}"
echo -e "${RED}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""

AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text 2>/dev/null || echo "unknown")

echo -e "${YELLOW}Configuration:${NC}"
echo "  AWS Account: $AWS_ACCOUNT_ID"
echo "  AWS Region: $AWS_REGION"
echo "  Skip Agent: $SKIP_AGENT"
echo "  Skip ChatApp: $SKIP_CHATAPP"
echo "  Dry Run: $DRY_RUN"
echo ""

if [ "$DRY_RUN" = true ]; then
    echo -e "${CYAN}DRY RUN MODE - No resources will be deleted${NC}"
    echo ""
fi

# Confirmation prompt
if [ "$AUTO_YES" != true ] && [ "$DRY_RUN" != true ]; then
    echo -e "${RED}WARNING: This will permanently delete all resources!${NC}"
    echo -e "${YELLOW}Are you sure you want to continue? (type 'yes' to confirm)${NC}"
    read -r CONFIRM
    if [ "$CONFIRM" != "yes" ]; then
        echo "Cleanup cancelled."
        exit 0
    fi
fi

# Helper function for dry run
run_cmd() {
    if [ "$DRY_RUN" = true ]; then
        echo -e "${CYAN}[DRY RUN] Would execute: $*${NC}"
        return 0
    else
        "$@"
    fi
}

# Export region for sub-commands
export AWS_REGION


# ============================================================================
# STEP 1: Delete ECS Express Mode Service
# ============================================================================
if [ "$SKIP_CHATAPP" != true ]; then
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}Step 1: Delete ECS Express Mode Service${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

    SERVICE_ARN=$(aws ecs list-services \
        --cluster default \
        --region "$AWS_REGION" \
        --query "serviceArns[?contains(@, '${EXPRESS_SERVICE_NAME}')]" \
        --output text 2>/dev/null | head -1 || echo "")

    if [ -n "$SERVICE_ARN" ] && [ "$SERVICE_ARN" != "None" ]; then
        echo -e "${YELLOW}Deleting Express Mode service: $SERVICE_ARN${NC}"
        run_cmd aws ecs delete-express-gateway-service \
            --service-arn "$SERVICE_ARN" \
            --region "$AWS_REGION" \
            --no-cli-pager 2>/dev/null || echo -e "${YELLOW}Service deletion initiated${NC}"
        echo -e "${GREEN}Express Mode service deleted${NC}"
    else
        echo -e "${YELLOW}No Express Mode service found${NC}"
    fi
fi

# ============================================================================
# STEP 2: Delete ECR Repository
# ============================================================================
if [ "$SKIP_CHATAPP" != true ]; then
    echo ""
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}Step 2: Delete ECR Repository${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

    if aws ecr describe-repositories --repository-names "$APP_NAME" --region "$AWS_REGION" > /dev/null 2>&1; then
        echo -e "${YELLOW}Deleting ECR repository: $APP_NAME${NC}"
        run_cmd aws ecr delete-repository \
            --repository-name "$APP_NAME" \
            --region "$AWS_REGION" \
            --force
        echo -e "${GREEN}ECR repository deleted${NC}"
    else
        echo -e "${YELLOW}ECR repository not found${NC}"
    fi
fi

# ============================================================================
# STEP 3: Delete Secrets Manager Secret
# ============================================================================
if [ "$SKIP_CHATAPP" != true ]; then
    echo ""
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}Step 3: Delete Secrets Manager Secret${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

    if aws secretsmanager describe-secret --secret-id "$SECRET_NAME" --region "$AWS_REGION" > /dev/null 2>&1; then
        echo -e "${YELLOW}Deleting secret: $SECRET_NAME${NC}"
        run_cmd aws secretsmanager delete-secret \
            --secret-id "$SECRET_NAME" \
            --region "$AWS_REGION" \
            --force-delete-without-recovery
        echo -e "${GREEN}Secret deleted${NC}"
    else
        echo -e "${YELLOW}Secret not found${NC}"
    fi
fi

# ============================================================================
# STEP 4: Delete DynamoDB Tables
# ============================================================================
if [ "$SKIP_CHATAPP" != true ]; then
    echo ""
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}Step 4: Delete DynamoDB Tables${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

    for TABLE_NAME in "$USAGE_TABLE_NAME" "$FEEDBACK_TABLE_NAME" "$GUARDRAIL_TABLE_NAME"; do
        if aws dynamodb describe-table --table-name "$TABLE_NAME" --region "$AWS_REGION" > /dev/null 2>&1; then
            echo -e "${YELLOW}Deleting DynamoDB table: $TABLE_NAME${NC}"
            run_cmd aws dynamodb delete-table \
                --table-name "$TABLE_NAME" \
                --region "$AWS_REGION"
            echo -e "${GREEN}Table $TABLE_NAME deleted${NC}"
        else
            echo -e "${YELLOW}Table $TABLE_NAME not found${NC}"
        fi
    done
fi

# ============================================================================
# STEP 5: Delete Bedrock Guardrail
# ============================================================================
if [ "$SKIP_CHATAPP" != true ]; then
    echo ""
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}Step 5: Delete Bedrock Guardrail${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

    GUARDRAIL_ID=$(aws bedrock list-guardrails \
        --region "$AWS_REGION" \
        --query "guardrails[?name=='$GUARDRAIL_NAME'].id | [0]" \
        --output text 2>/dev/null || echo "")

    if [ -n "$GUARDRAIL_ID" ] && [ "$GUARDRAIL_ID" != "None" ] && [ "$GUARDRAIL_ID" != "null" ]; then
        echo -e "${YELLOW}Deleting Bedrock guardrail: $GUARDRAIL_ID${NC}"
        run_cmd aws bedrock delete-guardrail \
            --guardrail-identifier "$GUARDRAIL_ID" \
            --region "$AWS_REGION"
        echo -e "${GREEN}Guardrail deleted${NC}"
    else
        echo -e "${YELLOW}Guardrail not found${NC}"
    fi
fi

# ============================================================================
# STEP 6: Delete Cognito User Pool
# ============================================================================
if [ "$SKIP_CHATAPP" != true ]; then
    echo ""
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}Step 6: Delete Cognito User Pool${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

    USER_POOL_ID=$(aws cognito-idp list-user-pools --max-results 60 --region "$AWS_REGION" \
        --query "UserPools[?Name=='$COGNITO_POOL_NAME'].Id" --output text 2>/dev/null || echo "")

    if [ -n "$USER_POOL_ID" ] && [ "$USER_POOL_ID" != "None" ]; then
        # First delete the domain if it exists
        DOMAIN=$(aws cognito-idp describe-user-pool \
            --user-pool-id "$USER_POOL_ID" \
            --region "$AWS_REGION" \
            --query 'UserPool.Domain' \
            --output text 2>/dev/null || echo "")
        
        if [ -n "$DOMAIN" ] && [ "$DOMAIN" != "None" ]; then
            echo -e "${YELLOW}Deleting Cognito domain: $DOMAIN${NC}"
            run_cmd aws cognito-idp delete-user-pool-domain \
                --domain "$DOMAIN" \
                --user-pool-id "$USER_POOL_ID" \
                --region "$AWS_REGION" 2>/dev/null || true
        fi

        echo -e "${YELLOW}Deleting Cognito User Pool: $USER_POOL_ID${NC}"
        run_cmd aws cognito-idp delete-user-pool \
            --user-pool-id "$USER_POOL_ID" \
            --region "$AWS_REGION"
        echo -e "${GREEN}Cognito User Pool deleted${NC}"
    else
        echo -e "${YELLOW}Cognito User Pool not found${NC}"
    fi
fi


# ============================================================================
# STEP 7: Delete IAM Roles and Policies
# ============================================================================
if [ "$SKIP_CHATAPP" != true ]; then
    echo ""
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}Step 7: Delete IAM Roles${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

    # Delete execution role
    if aws iam get-role --role-name "$EXECUTION_ROLE_NAME" > /dev/null 2>&1; then
        echo -e "${YELLOW}Deleting execution role: $EXECUTION_ROLE_NAME${NC}"
        
        # Detach managed policies
        ATTACHED_POLICIES=$(aws iam list-attached-role-policies \
            --role-name "$EXECUTION_ROLE_NAME" \
            --query 'AttachedPolicies[*].PolicyArn' \
            --output text 2>/dev/null || echo "")
        
        for POLICY_ARN in $ATTACHED_POLICIES; do
            if [ -n "$POLICY_ARN" ]; then
                run_cmd aws iam detach-role-policy \
                    --role-name "$EXECUTION_ROLE_NAME" \
                    --policy-arn "$POLICY_ARN" 2>/dev/null || echo -e "${YELLOW}  Warning: Could not detach policy $POLICY_ARN${NC}"
            fi
        done
        
        # Delete inline policies
        INLINE_POLICIES=$(aws iam list-role-policies \
            --role-name "$EXECUTION_ROLE_NAME" \
            --query 'PolicyNames' \
            --output text 2>/dev/null || echo "")
        
        for POLICY_NAME in $INLINE_POLICIES; do
            if [ -n "$POLICY_NAME" ]; then
                run_cmd aws iam delete-role-policy \
                    --role-name "$EXECUTION_ROLE_NAME" \
                    --policy-name "$POLICY_NAME" 2>/dev/null || echo -e "${YELLOW}  Warning: Could not delete inline policy $POLICY_NAME${NC}"
            fi
        done
        
        if run_cmd aws iam delete-role --role-name "$EXECUTION_ROLE_NAME" 2>&1; then
            echo -e "${GREEN}Execution role deleted${NC}"
        else
            echo -e "${RED}Failed to delete execution role (may require elevated permissions)${NC}"
        fi
    else
        echo -e "${YELLOW}Execution role not found${NC}"
    fi

    # Delete task role
    if aws iam get-role --role-name "$TASK_ROLE_NAME" > /dev/null 2>&1; then
        echo -e "${YELLOW}Deleting task role: $TASK_ROLE_NAME${NC}"
        
        # Detach managed policies
        ATTACHED_POLICIES=$(aws iam list-attached-role-policies \
            --role-name "$TASK_ROLE_NAME" \
            --query 'AttachedPolicies[*].PolicyArn' \
            --output text 2>/dev/null || echo "")
        
        for POLICY_ARN in $ATTACHED_POLICIES; do
            if [ -n "$POLICY_ARN" ]; then
                run_cmd aws iam detach-role-policy \
                    --role-name "$TASK_ROLE_NAME" \
                    --policy-arn "$POLICY_ARN" 2>/dev/null || echo -e "${YELLOW}  Warning: Could not detach policy $POLICY_ARN${NC}"
            fi
        done
        
        # Delete inline policies
        INLINE_POLICIES=$(aws iam list-role-policies \
            --role-name "$TASK_ROLE_NAME" \
            --query 'PolicyNames' \
            --output text 2>/dev/null || echo "")
        
        for POLICY_NAME in $INLINE_POLICIES; do
            if [ -n "$POLICY_NAME" ]; then
                run_cmd aws iam delete-role-policy \
                    --role-name "$TASK_ROLE_NAME" \
                    --policy-name "$POLICY_NAME" 2>/dev/null || echo -e "${YELLOW}  Warning: Could not delete inline policy $POLICY_NAME${NC}"
            fi
        done
        
        if run_cmd aws iam delete-role --role-name "$TASK_ROLE_NAME" 2>&1; then
            echo -e "${GREEN}Task role deleted${NC}"
        else
            echo -e "${RED}Failed to delete task role (may require elevated permissions)${NC}"
        fi
    else
        echo -e "${YELLOW}Task role not found${NC}"
    fi

    # Delete infrastructure role (shared, only delete if no other services use it)
    if aws iam get-role --role-name "$INFRA_ROLE_NAME" > /dev/null 2>&1; then
        echo -e "${YELLOW}Note: Infrastructure role '$INFRA_ROLE_NAME' exists${NC}"
        echo -e "${YELLOW}This role may be shared by other ECS Express services.${NC}"
        
        if [ "$AUTO_YES" = true ]; then
            DELETE_INFRA="y"
        else
            echo -e "${YELLOW}Delete infrastructure role? (y/n)${NC}"
            read -r DELETE_INFRA
        fi
        
        if [[ $DELETE_INFRA =~ ^[Yy]$ ]]; then
            # Detach managed policies
            ATTACHED_POLICIES=$(aws iam list-attached-role-policies \
                --role-name "$INFRA_ROLE_NAME" \
                --query 'AttachedPolicies[*].PolicyArn' \
                --output text 2>/dev/null || echo "")
            
            for POLICY_ARN in $ATTACHED_POLICIES; do
                if [ -n "$POLICY_ARN" ]; then
                    run_cmd aws iam detach-role-policy \
                        --role-name "$INFRA_ROLE_NAME" \
                        --policy-arn "$POLICY_ARN" 2>/dev/null || echo -e "${YELLOW}  Warning: Could not detach policy $POLICY_ARN${NC}"
                fi
            done
            
            if run_cmd aws iam delete-role --role-name "$INFRA_ROLE_NAME" 2>&1; then
                echo -e "${GREEN}Infrastructure role deleted${NC}"
            else
                echo -e "${RED}Failed to delete infrastructure role (may require elevated permissions)${NC}"
            fi
        else
            echo -e "${YELLOW}Skipping infrastructure role deletion${NC}"
        fi
    fi
fi

# ============================================================================
# STEP 8: Delete CloudWatch Resources
# ============================================================================
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Step 8: Delete CloudWatch Resources${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# Delete CloudWatch log groups
echo -e "${YELLOW}Deleting CloudWatch log groups...${NC}"

# ECS service log group
LOG_GROUP="/ecs/${EXPRESS_SERVICE_NAME}"
if aws logs describe-log-groups --log-group-name-prefix "$LOG_GROUP" --region "$AWS_REGION" --query 'logGroups[0]' --output text 2>/dev/null | grep -q "$LOG_GROUP"; then
    run_cmd aws logs delete-log-group \
        --log-group-name "$LOG_GROUP" \
        --region "$AWS_REGION"
    echo -e "${GREEN}Deleted log group: $LOG_GROUP${NC}"
fi

# Only delete log groups for THIS app's agent (based on config file)
# We need to be careful not to delete logs for other agents
AGENT_CONFIG="$AGENT_DIR/.bedrock_agentcore.yaml"
if [ -f "$AGENT_CONFIG" ]; then
    RUNTIME_ARN=$(grep "agent_arn:" "$AGENT_CONFIG" | head -1 | sed 's/.*agent_arn: //' | tr -d ' ')
    if [ -n "$RUNTIME_ARN" ]; then
        # Extract runtime ID from ARN for targeted log group deletion
        RUNTIME_ID=$(echo "$RUNTIME_ARN" | sed 's/.*runtime\///' | sed 's/\/.*//')
        
        # Delete runtime log group for this specific agent
        RUNTIME_LOG_GROUP="/aws/bedrock-agentcore/runtimes/${RUNTIME_ID}"
        if aws logs describe-log-groups --log-group-name-prefix "$RUNTIME_LOG_GROUP" --region "$AWS_REGION" --query 'logGroups[0]' --output text 2>/dev/null | grep -q "$RUNTIME_ID"; then
            echo -e "${YELLOW}Deleting AgentCore log group: $RUNTIME_LOG_GROUP${NC}"
            run_cmd aws logs delete-log-group \
                --log-group-name "$RUNTIME_LOG_GROUP" \
                --region "$AWS_REGION" 2>/dev/null || true
        fi
        
        # Delete vended log group for this specific agent
        VENDED_LOG_GROUP="/aws/vendedlogs/bedrock-agentcore/runtime/${RUNTIME_ID}"
        if aws logs describe-log-groups --log-group-name-prefix "$VENDED_LOG_GROUP" --region "$AWS_REGION" --query 'logGroups[0]' --output text 2>/dev/null | grep -q "$RUNTIME_ID"; then
            echo -e "${YELLOW}Deleting vended log group: $VENDED_LOG_GROUP${NC}"
            run_cmd aws logs delete-log-group \
                --log-group-name "$VENDED_LOG_GROUP" \
                --region "$AWS_REGION" 2>/dev/null || true
        fi
    fi
else
    echo -e "${YELLOW}No agent config found - skipping AgentCore log group cleanup${NC}"
fi

# Delete CloudWatch Logs resource policy for X-Ray
echo -e "${YELLOW}Deleting CloudWatch Logs resource policy...${NC}"
run_cmd aws logs delete-resource-policy \
    --policy-name "AgentCoreTracingPolicy" \
    --region "$AWS_REGION" 2>/dev/null || true


# ============================================================================
# STEP 9: Delete AgentCore Agent and Memory
# ============================================================================
if [ "$SKIP_AGENT" != true ]; then
    echo ""
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}Step 9: Delete AgentCore Agent and Memory${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

    # Activate virtual environment if it exists (needed for agentcore CLI)
    if [ -f "$AGENT_DIR/.venv/bin/activate" ]; then
        echo -e "${YELLOW}Activating agent virtual environment...${NC}"
        source "$AGENT_DIR/.venv/bin/activate"
    fi

    # Check if agentcore CLI is available
    if command -v agentcore &> /dev/null; then
        # Try to get agent info from config file
        AGENT_CONFIG="$AGENT_DIR/.bedrock_agentcore.yaml"
        RUNTIME_ARN=""
        MEMORY_ID=""
        
        if [ -f "$AGENT_CONFIG" ]; then
            RUNTIME_ARN=$(grep "agent_arn:" "$AGENT_CONFIG" | head -1 | sed 's/.*agent_arn: //' | tr -d ' ')
            MEMORY_ID=$(grep "memory_id:" "$AGENT_CONFIG" | head -1 | sed 's/.*memory_id: //' | tr -d ' ')
        fi

        # Delete agent runtime
        if [ -n "$RUNTIME_ARN" ]; then
            echo -e "${YELLOW}Deleting AgentCore runtime: $RUNTIME_ARN${NC}"
            
            # Delete any log deliveries first
            RUNTIME_ID=$(echo "$RUNTIME_ARN" | sed 's/.*runtime\///')
            
            # Delete delivery sources
            run_cmd aws logs delete-delivery-source \
                --name "${RUNTIME_ID}-logs-source" \
                --region "$AWS_REGION" 2>/dev/null || true
            run_cmd aws logs delete-delivery-source \
                --name "${RUNTIME_ID}-traces-source" \
                --region "$AWS_REGION" 2>/dev/null || true
            
            # Delete delivery destinations
            run_cmd aws logs delete-delivery-destination \
                --name "${RUNTIME_ID}-logs-destination" \
                --region "$AWS_REGION" 2>/dev/null || true
            run_cmd aws logs delete-delivery-destination \
                --name "${RUNTIME_ID}-traces-destination" \
                --region "$AWS_REGION" 2>/dev/null || true
            
            # Delete the agent using agentcore CLI (run from agent directory for config context)
            # Note: agentcore destroy reads region from .bedrock_agentcore.yaml config
            if [ "$DRY_RUN" != true ]; then
                CURRENT_DIR=$(pwd)
                cd "$AGENT_DIR"
                if agentcore destroy --force 2>&1; then
                    echo -e "${GREEN}Agent runtime deleted${NC}"
                else
                    echo -e "${YELLOW}Agent deletion via CLI failed, may already be deleted${NC}"
                fi
                cd "$CURRENT_DIR"
            else
                echo -e "${CYAN}[DRY RUN] Would execute: agentcore destroy --force${NC}"
            fi
        else
            echo -e "${YELLOW}No agent runtime ARN found in config${NC}"
            
            # Try to find and delete by name using config file
            echo -e "${YELLOW}Searching for agent by name: $AGENT_NAME${NC}"
            CURRENT_DIR=$(pwd)
            cd "$AGENT_DIR"
            AGENT_LIST=$(agentcore status --agent "$AGENT_NAME" 2>/dev/null || echo "")
            if [ -n "$AGENT_LIST" ] && ! echo "$AGENT_LIST" | grep -q "not found"; then
                echo -e "${YELLOW}Found agent, attempting deletion...${NC}"
                if [ "$DRY_RUN" != true ]; then
                    agentcore destroy --agent "$AGENT_NAME" --force 2>/dev/null || echo -e "${YELLOW}Agent deletion failed${NC}"
                fi
            else
                echo -e "${YELLOW}Agent not found${NC}"
            fi
            cd "$CURRENT_DIR"
        fi

        # Delete memory
        if [ -n "$MEMORY_ID" ]; then
            echo -e "${YELLOW}Deleting AgentCore memory: $MEMORY_ID${NC}"
            if [ "$DRY_RUN" != true ]; then
                if agentcore memory delete "$MEMORY_ID" --region "$AWS_REGION" --wait 2>&1; then
                    echo -e "${GREEN}Memory deleted${NC}"
                else
                    echo -e "${YELLOW}Memory deletion failed, may already be deleted${NC}"
                fi
            else
                echo -e "${CYAN}[DRY RUN] Would execute: agentcore memory delete $MEMORY_ID --region $AWS_REGION --wait${NC}"
            fi
        else
            echo -e "${YELLOW}No memory ID found in config${NC}"
            
            # Try to find and delete by name
            echo -e "${YELLOW}Searching for memory by name: $MEMORY_NAME${NC}"
            MEMORY_LIST=$(agentcore memory list --region "$AWS_REGION" 2>/dev/null || echo "")
            FOUND_MEMORY_ID=$(echo "$MEMORY_LIST" | grep "$MEMORY_NAME" | awk '{print $1}' | head -1)
            if [ -n "$FOUND_MEMORY_ID" ]; then
                echo -e "${YELLOW}Found memory: $FOUND_MEMORY_ID${NC}"
                if [ "$DRY_RUN" != true ]; then
                    if agentcore memory delete "$FOUND_MEMORY_ID" --region "$AWS_REGION" --wait 2>&1; then
                        echo -e "${GREEN}Memory deleted${NC}"
                    else
                        echo -e "${YELLOW}Memory deletion failed${NC}"
                    fi
                fi
            else
                echo -e "${YELLOW}Memory not found${NC}"
            fi
        fi
    else
        echo -e "${YELLOW}agentcore CLI not found - skipping agent/memory deletion${NC}"
        echo "Install with: pip install bedrock-agentcore"
        echo "Then manually delete the agent and memory using the CLI or console"
    fi
fi

# ============================================================================
# STEP 10: Clean up local files
# ============================================================================
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Step 10: Clean up local files${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

if [ "$AUTO_YES" = true ]; then
    CLEAN_LOCAL="y"
else
    echo -e "${YELLOW}Delete local config files (.env, .bedrock_agentcore.yaml)? (y/n)${NC}"
    read -r CLEAN_LOCAL
fi

if [[ $CLEAN_LOCAL =~ ^[Yy]$ ]]; then
    # Clean agent directory
    if [ -f "$AGENT_DIR/.bedrock_agentcore.yaml" ]; then
        run_cmd rm -f "$AGENT_DIR/.bedrock_agentcore.yaml"
        echo -e "${GREEN}Deleted agent/.bedrock_agentcore.yaml${NC}"
    fi
    if [ -f "$AGENT_DIR/.env" ]; then
        run_cmd rm -f "$AGENT_DIR/.env"
        echo -e "${GREEN}Deleted agent/.env${NC}"
    fi
    if [ -d "$AGENT_DIR/.bedrock_agentcore" ]; then
        run_cmd rm -rf "$AGENT_DIR/.bedrock_agentcore"
        echo -e "${GREEN}Deleted agent/.bedrock_agentcore/ build cache${NC}"
    fi
    
    # Clean chatapp directory
    if [ -f "$CHATAPP_DIR/.env" ]; then
        run_cmd rm -f "$CHATAPP_DIR/.env"
        echo -e "${GREEN}Deleted chatapp/.env${NC}"
    fi
else
    echo -e "${YELLOW}Skipping local file cleanup${NC}"
fi

# ============================================================================
# COMPLETE
# ============================================================================
echo ""
echo -e "${GREEN}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║           Cleanup Complete!                                ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""

if [ "$DRY_RUN" = true ]; then
    echo -e "${CYAN}This was a DRY RUN - no resources were actually deleted.${NC}"
    echo -e "${CYAN}Run without --dry-run to perform actual cleanup.${NC}"
else
    echo -e "${CYAN}Summary of deleted resources:${NC}"
    if [ "$SKIP_CHATAPP" != true ]; then
        echo "  - ECS Express Mode service"
        echo "  - ECR repository"
        echo "  - Secrets Manager secret"
        echo "  - DynamoDB tables (usage, feedback, guardrails)"
        echo "  - Bedrock Guardrail"
        echo "  - Cognito User Pool"
        echo "  - IAM roles (execution, task)"
    fi
    echo "  - CloudWatch log groups"
    if [ "$SKIP_AGENT" != true ]; then
        echo "  - AgentCore Runtime"
        echo "  - AgentCore Memory"
    fi
    echo ""
    echo -e "${YELLOW}Note: Resources will take a few minutes to fully delete.${NC}"
fi
