#!/bin/bash
# Set up IAM roles for HTMX ChatApp ECS deployment
# Usage: ./setup-iam.sh

set -e

# Disable AWS CLI pager
export AWS_PAGER=""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

AWS_REGION="${AWS_REGION:-us-east-1}"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

EXECUTION_ROLE_NAME="htmx-chatapp-execution-role"
TASK_ROLE_NAME="htmx-chatapp-task-role"

echo -e "${YELLOW}Setting up IAM roles for HTMX ChatApp...${NC}"
echo "Account ID: $ACCOUNT_ID"
echo "Region: $AWS_REGION"

# Create Task Execution Role
echo -e "\n${YELLOW}Creating Task Execution Role...${NC}"

# Trust policy for ECS tasks
TRUST_POLICY='{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "ecs-tasks.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}'

# Check if execution role exists
if aws iam get-role --role-name "$EXECUTION_ROLE_NAME" 2>/dev/null; then
    echo -e "${GREEN}Execution role already exists${NC}"
else
    aws iam create-role \
        --role-name "$EXECUTION_ROLE_NAME" \
        --assume-role-policy-document "$TRUST_POLICY" \
        --description "Task execution role for HTMX ChatApp ECS tasks"
    echo -e "${GREEN}Created execution role${NC}"
fi

# Attach managed policy for ECS task execution
aws iam attach-role-policy \
    --role-name "$EXECUTION_ROLE_NAME" \
    --policy-arn "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy" 2>/dev/null || true

# Create inline policy for secrets access (wildcard region for multi-region support)
SECRETS_POLICY="{
  \"Version\": \"2012-10-17\",
  \"Statement\": [
    {
      \"Effect\": \"Allow\",
      \"Action\": [
        \"secretsmanager:GetSecretValue\"
      ],
      \"Resource\": \"arn:aws:secretsmanager:*:$ACCOUNT_ID:secret:htmx-chatapp/*\"
    }
  ]
}"

aws iam put-role-policy \
    --role-name "$EXECUTION_ROLE_NAME" \
    --policy-name "SecretsAccess" \
    --policy-document "$SECRETS_POLICY"

echo -e "${GREEN}Configured execution role policies${NC}"

# Create Task Role
echo -e "\n${YELLOW}Creating Task Role...${NC}"

if aws iam get-role --role-name "$TASK_ROLE_NAME" 2>/dev/null; then
    echo -e "${GREEN}Task role already exists${NC}"
else
    aws iam create-role \
        --role-name "$TASK_ROLE_NAME" \
        --assume-role-policy-document "$TRUST_POLICY" \
        --description "Task role for HTMX ChatApp ECS tasks"
    echo -e "${GREEN}Created task role${NC}"
fi

# Create inline policy for AgentCore, Cognito, and DynamoDB access
TASK_POLICY="{
  \"Version\": \"2012-10-17\",
  \"Statement\": [
    {
      \"Sid\": \"AgentCoreAccess\",
      \"Effect\": \"Allow\",
      \"Action\": [
        \"bedrock-agentcore:InvokeAgentRuntime\",
        \"bedrock-agentcore:GetMemory\",
        \"bedrock-agentcore:ListMemories\",
        \"bedrock-agentcore:QueryMemory\",
        \"bedrock-agentcore:ListEvents\",
        \"bedrock-agentcore:GetEvent\",
        \"bedrock-agentcore:ListMemoryRecords\",
        \"bedrock-agentcore:GetMemoryRecord\"
      ],
      \"Resource\": \"*\"
    },
    {
      \"Sid\": \"CognitoAccess\",
      \"Effect\": \"Allow\",
      \"Action\": [
        \"cognito-idp:GetUser\",
        \"cognito-idp:AdminGetUser\",
        \"cognito-idp:ListUsers\",
        \"cognito-idp:AdminListGroupsForUser\"
      ],
      \"Resource\": \"*\"
    },
    {
      \"Sid\": \"DynamoDBUsageAccess\",
      \"Effect\": \"Allow\",
      \"Action\": [
        \"dynamodb:PutItem\",
        \"dynamodb:GetItem\",
        \"dynamodb:Query\",
        \"dynamodb:Scan\"
      ],
      \"Resource\": [
        \"arn:aws:dynamodb:*:$ACCOUNT_ID:table/agentcore-usage-records\",
        \"arn:aws:dynamodb:*:$ACCOUNT_ID:table/agentcore-usage-records/index/*\"
      ]
    }
  ]
}"

aws iam put-role-policy \
    --role-name "$TASK_ROLE_NAME" \
    --policy-name "AgentCoreAccess" \
    --policy-document "$TASK_POLICY"

echo -e "${GREEN}Configured task role policies${NC}"

# Output role ARNs
echo -e "\n${GREEN}IAM Roles Created Successfully!${NC}"
echo ""
echo "Execution Role ARN:"
aws iam get-role --role-name "$EXECUTION_ROLE_NAME" --query 'Role.Arn' --output text
echo ""
echo "Task Role ARN:"
aws iam get-role --role-name "$TASK_ROLE_NAME" --query 'Role.Arn' --output text
