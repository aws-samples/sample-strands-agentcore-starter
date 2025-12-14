#!/bin/bash
# HTMX ChatApp ECS Express Mode Deployment Script
# Deploys to ECS Express Mode for simplified infrastructure management
#
# Usage: ./deploy.sh [--skip-build] [--update] [--delete]
#   --skip-build  Skip Docker build and use existing image
#   --update      Update existing Express Mode service
#   --delete      Delete the Express Mode service

set -e

# Disable AWS CLI pager
export AWS_PAGER=""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
APP_NAME="htmx-chatapp"
EXPRESS_SERVICE_NAME="htmx-chatapp-express"
AWS_REGION="${AWS_REGION:-us-east-2}"
CONTAINER_PORT=8080


CPU="512"     # CPU in units (256, 512, 1024, 2048, 4096) - 1024 = 1 vCPU
MEMORY="1024" # Memory in MiB (512, 1024, 2048, 4096, 8192) - must be compatible with CPU
MIN_TASKS=1
MAX_TASKS=10

# Parse arguments
SKIP_BUILD=false
UPDATE_SERVICE=false
DELETE_SERVICE=false
while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-build)
            SKIP_BUILD=true
            shift
            ;;
        --update)
            UPDATE_SERVICE=true
            shift
            ;;
        --delete)
            DELETE_SERVICE=true
            shift
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            echo "Usage: ./deploy.sh [--skip-build] [--update] [--delete]"
            exit 1
            ;;
    esac
done

echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║       HTMX ChatApp ECS Express Mode Deployment             ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Get AWS account ID
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
if [ -z "$ACCOUNT_ID" ]; then
    echo -e "${RED}Error: Could not get AWS account ID. Check your AWS credentials.${NC}"
    exit 1
fi

ECR_REPO="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${APP_NAME}"
IMAGE_TAG=$(date +%Y%m%d-%H%M%S)
FULL_IMAGE_URI="${ECR_REPO}:${IMAGE_TAG}"

echo -e "${YELLOW}Configuration:${NC}"
echo "  Account ID:     $ACCOUNT_ID"
echo "  Region:         $AWS_REGION"
echo "  Service Name:   $EXPRESS_SERVICE_NAME"
echo "  ECR Repo:       $ECR_REPO"
echo "  CPU:            $CPU vCPU"
echo "  Memory:         $MEMORY GB"
echo "  Min Tasks:      $MIN_TASKS"
echo "  Max Tasks:      $MAX_TASKS"
echo ""

# Handle delete operation
if [ "$DELETE_SERVICE" = true ]; then
    echo -e "${YELLOW}Deleting Express Mode service...${NC}"
    
    SERVICE_ARN=$(aws ecs list-services \
        --cluster default \
        --region "$AWS_REGION" \
        --query "serviceArns[?contains(@, '${EXPRESS_SERVICE_NAME}')]" \
        --output text 2>/dev/null || echo "")
    
    if [ -n "$SERVICE_ARN" ] && [ "$SERVICE_ARN" != "None" ]; then
        aws ecs delete-express-gateway-service \
            --service-arn "$SERVICE_ARN" \
            --region "$AWS_REGION" \
            --monitor-resources || true
        echo -e "${GREEN}Express Mode service deleted${NC}"
    else
        echo -e "${YELLOW}No Express Mode service found to delete${NC}"
    fi
    exit 0
fi

# Step 1: Create ECR repository if it doesn't exist
echo -e "${YELLOW}Step 1: Ensuring ECR repository exists...${NC}"
if ! aws ecr describe-repositories --repository-names "$APP_NAME" --region "$AWS_REGION" > /dev/null 2>&1; then
    echo "Creating ECR repository..."
    aws ecr create-repository \
        --repository-name "$APP_NAME" \
        --region "$AWS_REGION" \
        --image-scanning-configuration scanOnPush=true > /dev/null
    echo -e "${GREEN}ECR repository created${NC}"
else
    echo -e "${GREEN}ECR repository exists${NC}"
fi

# Step 2: Build Docker image
if [ "$SKIP_BUILD" = false ]; then
    echo -e "\n${YELLOW}Step 2: Building Docker image for linux/amd64...${NC}"
    docker build --platform linux/amd64 -t "$APP_NAME:$IMAGE_TAG" -t "$APP_NAME:latest" .
    echo -e "${GREEN}Docker image built${NC}"
else
    echo -e "\n${YELLOW}Step 2: Skipping Docker build (--skip-build)${NC}"
    IMAGE_TAG="latest"
    FULL_IMAGE_URI="${ECR_REPO}:latest"
fi

# Step 3: Push to ECR
echo -e "\n${YELLOW}Step 3: Pushing image to ECR...${NC}"
aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "$ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"
docker tag "$APP_NAME:$IMAGE_TAG" "$FULL_IMAGE_URI"
docker push "$FULL_IMAGE_URI"
echo -e "${GREEN}Image pushed to ECR${NC}"

# Step 4: Create IAM roles for Express Mode if they don't exist
echo -e "
${YELLOW}Step 4: Ensuring IAM roles exist...${NC}"

# Task Execution Role - use custom role created by setup-iam.sh (has secrets access)
CUSTOM_EXECUTION_ROLE="htmx-chatapp-execution-role"
EXECUTION_ROLE_ARN=$(aws iam get-role --role-name "$CUSTOM_EXECUTION_ROLE" --query 'Role.Arn' --output text 2>/dev/null || echo "")

if [ -z "$EXECUTION_ROLE_ARN" ]; then
    echo -e "${RED}Error: Custom execution role '$CUSTOM_EXECUTION_ROLE' not found.${NC}"
    echo -e "${RED}This role is required for Secrets Manager access.${NC}"
    echo -e "${YELLOW}Run ./deploy/setup-iam.sh first to create the required IAM roles.${NC}"
    exit 1
fi
echo -e "${GREEN}Using custom Task Execution Role: $CUSTOM_EXECUTION_ROLE${NC}"

# Infrastructure Role for Express Mode
INFRA_ROLE_ARN=$(aws iam get-role --role-name "ecsInfrastructureRoleForExpressServices" --query 'Role.Arn' --output text 2>/dev/null || echo "")
if [ -z "$INFRA_ROLE_ARN" ]; then
    echo "Creating Infrastructure Role for Express Mode..."
    aws iam create-role \
        --role-name "ecsInfrastructureRoleForExpressServices" \
        --assume-role-policy-document '{
            "Version": "2012-10-17",
            "Statement": [{
                "Sid": "AllowAccessInfrastructureForECSExpressServices",
                "Effect": "Allow",
                "Principal": {"Service": "ecs.amazonaws.com"},
                "Action": "sts:AssumeRole"
            }]
        }' > /dev/null

    aws iam attach-role-policy \
        --role-name "ecsInfrastructureRoleForExpressServices" \
        --policy-arn "arn:aws:iam::aws:policy/service-role/AmazonECSInfrastructureRoleforExpressGatewayServices"

    INFRA_ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/ecsInfrastructureRoleForExpressServices"
    echo -e "${GREEN}Infrastructure Role created${NC}"

    # Wait for role to propagate
    echo "Waiting for IAM role propagation..."
    sleep 30
else
    # VERIFY the policy is attached
    INFRA_POLICY=$(aws iam list-attached-role-policies \
        --role-name "ecsInfrastructureRoleForExpressServices" \
        --query 'AttachedPolicies[?PolicyName==`AmazonECSInfrastructureRoleforExpressGatewayServices`]' \
        --output text)

    if [ -z "$INFRA_POLICY" ]; then
        echo -e "${YELLOW}Attaching missing policy to Infrastructure Role...${NC}"
        aws iam attach-role-policy \
            --role-name "ecsInfrastructureRoleForExpressServices" \
            --policy-arn "arn:aws:iam::aws:policy/service-role/AmazonECSInfrastructureRoleforExpressGatewayServices"
        sleep 30
    fi

    INFRA_ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/ecsInfrastructureRoleForExpressServices"
    echo -e "${GREEN}Infrastructure Role verified${NC}"
fi

# Verify default cluster exists
echo "Verifying default ECS cluster..."
CLUSTER_EXISTS=$(aws ecs describe-clusters \
    --clusters default \
    --region "$AWS_REGION" \
    --query 'clusters[0].clusterArn' \
    --output text 2>/dev/null || echo "")

if [ -z "$CLUSTER_EXISTS" ] || [ "$CLUSTER_EXISTS" = "None" ]; then
    echo "Creating default ECS cluster..."
    aws ecs create-cluster --cluster-name default --region "$AWS_REGION" > /dev/null
    echo -e "${GREEN}Default cluster created${NC}"
else
    echo -e "${GREEN}Default cluster exists${NC}"
fi

# Step 5: Get Task Role ARN (for accessing AWS services like AgentCore)
echo -e "\n${YELLOW}Step 5: Getting Task Role ARN...${NC}"
TASK_ROLE_ARN=$(aws iam get-role --role-name "${APP_NAME}-task-role" --query 'Role.Arn' --output text 2>/dev/null || echo "")
if [ -z "$TASK_ROLE_ARN" ]; then
    echo -e "${YELLOW}Warning: Task role '${APP_NAME}-task-role' not found.${NC}"
    echo "The application may not be able to access AWS services like AgentCore."
    echo "Run deploy/setup-iam.sh to create the task role."
fi

# Step 6: Get Secrets ARN
echo -e "\n${YELLOW}Step 6: Getting Secrets Manager ARN...${NC}"
SECRETS_ARN=$(aws secretsmanager describe-secret --secret-id "${APP_NAME}/config" --region "$AWS_REGION" --query 'ARN' --output text 2>/dev/null)

if [ -z "$SECRETS_ARN" ] || [ "$SECRETS_ARN" = "None" ]; then
    echo -e "${RED}Error: Secrets not found. Run deploy/create-secrets.sh first.${NC}"
    exit 1
fi
echo -e "${GREEN}Secrets found${NC}"

# Step 7: Create CloudWatch Log Group
echo -e "\n${YELLOW}Step 7: Ensuring CloudWatch Log Group exists...${NC}"
aws logs create-log-group --log-group-name "/ecs/${EXPRESS_SERVICE_NAME}" --region "$AWS_REGION" 2>/dev/null || true
echo -e "${GREEN}Log group ready${NC}"


# Step 8: Build environment variables and secrets for container
echo -e "\n${YELLOW}Step 8: Preparing container configuration...${NC}"

# Build the primary container configuration
PRIMARY_CONTAINER=$(cat <<EOF
{
    "image": "${FULL_IMAGE_URI}",
    "containerPort": ${CONTAINER_PORT},
    "environment": [
        {"name": "PORT", "value": "${CONTAINER_PORT}"},
        {"name": "PYTHONUNBUFFERED", "value": "1"}
    ],
    "secrets": [
        {"name": "COGNITO_USER_POOL_ID", "valueFrom": "${SECRETS_ARN}:cognito_user_pool_id::"},
        {"name": "COGNITO_CLIENT_ID", "valueFrom": "${SECRETS_ARN}:cognito_client_id::"},
        {"name": "COGNITO_CLIENT_SECRET", "valueFrom": "${SECRETS_ARN}:cognito_client_secret::"},
        {"name": "AGENTCORE_RUNTIME_ARN", "valueFrom": "${SECRETS_ARN}:agentcore_runtime_arn::"},
        {"name": "MEMORY_ID", "valueFrom": "${SECRETS_ARN}:memory_id::"},
        {"name": "AWS_REGION", "valueFrom": "${SECRETS_ARN}:aws_region::"},
        {"name": "APP_URL", "valueFrom": "${SECRETS_ARN}:app_url::"},
        {"name": "USAGE_TABLE_NAME", "valueFrom": "${SECRETS_ARN}:usage_table_name::"},
        {"name": "FEEDBACK_TABLE_NAME", "valueFrom": "${SECRETS_ARN}:feedback_table_name::"},
        {"name": "GUARDRAIL_TABLE_NAME", "valueFrom": "${SECRETS_ARN}:guardrail_table_name::"},
        {"name": "GUARDRAIL_ID", "valueFrom": "${SECRETS_ARN}:guardrail_id::"},
        {"name": "GUARDRAIL_VERSION", "valueFrom": "${SECRETS_ARN}:guardrail_version::"}
    ]
}
EOF
)

# Build scaling target configuration
SCALING_TARGET='{"minTaskCount": '$MIN_TASKS', "maxTaskCount": '$MAX_TASKS'}'

echo -e "${GREEN}Container configuration ready${NC}"

# Step 9: Create or Update Express Mode service
echo -e "\n${YELLOW}Step 9: Deploying Express Mode service...${NC}"

# Write configs to temp files to avoid shell escaping issues with AWS CLI
CONTAINER_FILE=$(mktemp)
SCALING_FILE=$(mktemp)
trap "rm -f $CONTAINER_FILE $SCALING_FILE" EXIT

echo "$PRIMARY_CONTAINER" > "$CONTAINER_FILE"
echo "$SCALING_TARGET" > "$SCALING_FILE"

# Check if service exists
EXISTING_SERVICE=$(aws ecs list-services \
    --cluster default \
    --region "$AWS_REGION" \
    --query "serviceArns[?contains(@, '${EXPRESS_SERVICE_NAME}')]" \
    --output text 2>/dev/null || echo "")

if [ "$UPDATE_SERVICE" = true ] || ([ -n "$EXISTING_SERVICE" ] && [ "$EXISTING_SERVICE" != "None" ]); then
    echo "Updating existing Express Mode service..."
    
    SERVICE_ARN="$EXISTING_SERVICE"
    if [ -z "$SERVICE_ARN" ] || [ "$SERVICE_ARN" = "None" ]; then
        echo -e "${RED}Error: Service not found for update${NC}"
        exit 1
    fi
    
    if [ -n "$TASK_ROLE_ARN" ]; then
        aws ecs update-express-gateway-service \
            --service-arn "$SERVICE_ARN" \
            --primary-container "file://$CONTAINER_FILE" \
            --task-role-arn "$TASK_ROLE_ARN" \
            --cpu "$CPU" \
            --memory "$MEMORY" \
            --health-check-path "/health" \
            --scaling-target "file://$SCALING_FILE" \
            --region "$AWS_REGION"
    else
        aws ecs update-express-gateway-service \
            --service-arn "$SERVICE_ARN" \
            --primary-container "file://$CONTAINER_FILE" \
            --cpu "$CPU" \
            --memory "$MEMORY" \
            --health-check-path "/health" \
            --scaling-target "file://$SCALING_FILE" \
            --region "$AWS_REGION"
    fi

    echo -e "${GREEN}Express Mode service updated${NC}"
else
    echo "Creating new Express Mode service..."
    
    if [ -n "$TASK_ROLE_ARN" ]; then
        aws ecs create-express-gateway-service \
            --service-name "$EXPRESS_SERVICE_NAME" \
            --primary-container "file://$CONTAINER_FILE" \
            --execution-role-arn "$EXECUTION_ROLE_ARN" \
            --infrastructure-role-arn "$INFRA_ROLE_ARN" \
            --task-role-arn "$TASK_ROLE_ARN" \
            --cpu "$CPU" \
            --memory "$MEMORY" \
            --health-check-path "/health" \
            --scaling-target "file://$SCALING_FILE" \
            --region "$AWS_REGION"
    else
        aws ecs create-express-gateway-service \
            --service-name "$EXPRESS_SERVICE_NAME" \
            --primary-container "file://$CONTAINER_FILE" \
            --execution-role-arn "$EXECUTION_ROLE_ARN" \
            --infrastructure-role-arn "$INFRA_ROLE_ARN" \
            --cpu "$CPU" \
            --memory "$MEMORY" \
            --health-check-path "/health" \
            --scaling-target "file://$SCALING_FILE" \
            --region "$AWS_REGION"
    fi

    # Speed up deployment
    aws ecs update-service \
    --cluster default \
    --service $EXPRESS_SERVICE_NAME \
    --deployment-configuration '{
        "bakeTimeInMinutes": 0,
        "canaryConfiguration": {
        "canaryPercent": 100.0,
        "canaryBakeTimeInMinutes": 0
        }
    }'    
    
    echo -e "${GREEN}Express Mode service created${NC}"
fi

# Step 10: Get service URL
echo -e "\n${YELLOW}Step 10: Getting service URL...${NC}"

# Try to get the service ARN
SERVICE_ARN=$(aws ecs list-services \
    --cluster default \
    --region "$AWS_REGION" \
    --query "serviceArns[?contains(@, '${EXPRESS_SERVICE_NAME}')]" \
    --output text 2>/dev/null | head -1 || echo "")

# Wait for URL to be available (up to 60 seconds)
SERVICE_URL=""
SERVICE_STATUS=""
if [ -n "$SERVICE_ARN" ] && [ "$SERVICE_ARN" != "None" ]; then
    echo "Waiting for service URL..."
    for i in {1..12}; do
        SERVICE_INFO=$(aws ecs describe-express-gateway-service \
            --service-arn "$SERVICE_ARN" \
            --region "$AWS_REGION" 2>/dev/null || echo "")
        
        if [ -n "$SERVICE_INFO" ]; then
            SERVICE_URL=$(echo "$SERVICE_INFO" | jq -r '.service.activeConfigurations[0].ingressPaths[0].endpoint // empty' 2>/dev/null || echo "")
            SERVICE_STATUS=$(echo "$SERVICE_INFO" | jq -r '.service.status.statusCode // empty' 2>/dev/null || echo "")
            
            if [ -n "$SERVICE_URL" ]; then
                break
            fi
        fi
        echo -n "."
        sleep 5
    done
    echo ""
fi

# Final output
echo ""
echo -e "${CYAN}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║       ECS Express Mode Deployment Complete!                ║${NC}"
echo -e "${CYAN}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""

if [ -n "$SERVICE_ARN" ]; then
    echo -e "${BLUE}Service ARN:${NC} $SERVICE_ARN"
    echo ""
fi

if [ -n "$SERVICE_STATUS" ]; then
    echo ""
    echo -e "${BLUE}Service Status:${NC} $SERVICE_STATUS"
fi

if [ -z "$SERVICE_URL" ]; then
    echo -e "${YELLOW}URL not yet available. Get it with:${NC}"
    echo "  aws ecs describe-express-gateway-service --service-arn \"$SERVICE_ARN\" --region $AWS_REGION --query 'service.activeConfigurations[0].ingressPaths[0].endpoint' --output text"
fi

# Output for parent script capture (must be last line)
echo "DEPLOY_SERVICE_URL=${SERVICE_URL}"