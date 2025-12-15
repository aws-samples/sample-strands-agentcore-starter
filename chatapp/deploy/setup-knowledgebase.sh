#!/bin/bash
# Set up Amazon Bedrock Knowledge Base with S3 Vectors storage
# Usage: ./setup-knowledgebase.sh [--yes]
#
# Options:
#   --yes    Auto-confirm all prompts (non-interactive mode)
#
# This script creates:
# - IAM role for Bedrock KB operations
# - S3 bucket for source documents
# - S3 vector bucket and index for embeddings
# - Bedrock Knowledge Base with Titan Embed v2
# - Data source connecting KB to S3 bucket
#
# After running, the KB_ID will be exported for use by setup.sh

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
APP_NAME="${APP_NAME:-htmx-chatapp}"
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# Resource names
KB_ROLE_NAME="BedrockKBRole-${APP_NAME}"
SOURCE_BUCKET_NAME="${APP_NAME}-kb-${AWS_ACCOUNT_ID}-${AWS_REGION}"
VECTOR_BUCKET_NAME="${APP_NAME}-vectors-${AWS_REGION}"
VECTOR_INDEX_NAME="${APP_NAME}-index-${AWS_REGION}"
KB_NAME="${APP_NAME}-kb"
DATA_SOURCE_NAME="${APP_NAME}-kb-datasource"

echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║         Bedrock Knowledge Base Setup                       ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${YELLOW}Configuration:${NC}"
echo "  Region: $AWS_REGION"
echo "  Account: $AWS_ACCOUNT_ID"
echo "  App Name: $APP_NAME"
echo "  KB Name: $KB_NAME"
echo "  Source Bucket: $SOURCE_BUCKET_NAME"
echo "  Vector Bucket: $VECTOR_BUCKET_NAME"
echo ""

# ============================================================================
# Step 1: Create IAM Role for Knowledge Base
# ============================================================================
echo -e "${YELLOW}Step 1: Creating IAM role for Knowledge Base...${NC}"

# Trust policy for Bedrock
KB_TRUST_POLICY='{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "bedrock.amazonaws.com"
      },
      "Action": "sts:AssumeRole",
      "Condition": {
        "StringEquals": {
          "aws:SourceAccount": "'"$AWS_ACCOUNT_ID"'"
        },
        "ArnLike": {
          "aws:SourceArn": "arn:aws:bedrock:'"$AWS_REGION"':'"$AWS_ACCOUNT_ID"':knowledge-base/*"
        }
      }
    }
  ]
}'

# Check if role exists
if aws iam get-role --role-name "$KB_ROLE_NAME" > /dev/null 2>&1; then
    echo -e "${GREEN}IAM role already exists: $KB_ROLE_NAME${NC}"
    KB_ROLE_ARN=$(aws iam get-role --role-name "$KB_ROLE_NAME" --query 'Role.Arn' --output text)
else
    # Create the role
    KB_ROLE_ARN=$(aws iam create-role \
        --role-name "$KB_ROLE_NAME" \
        --assume-role-policy-document "$KB_TRUST_POLICY" \
        --description "IAM role for Bedrock Knowledge Base operations" \
        --query 'Role.Arn' \
        --output text)
    echo -e "${GREEN}Created IAM role: $KB_ROLE_NAME${NC}"
fi

# Inline policy for KB operations
KB_POLICY='{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "BedrockInvokeModel",
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel"
      ],
      "Resource": [
        "arn:aws:bedrock:'"$AWS_REGION"'::foundation-model/amazon.titan-embed-text-v2:0"
      ]
    },
    {
      "Sid": "S3SourceBucketAccess",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::'"$SOURCE_BUCKET_NAME"'",
        "arn:aws:s3:::'"$SOURCE_BUCKET_NAME"'/*"
      ]
    },
    {
      "Sid": "S3VectorsAccess",
      "Effect": "Allow",
      "Action": [
        "s3vectors:CreateIndex",
        "s3vectors:DeleteIndex",
        "s3vectors:GetIndex",
        "s3vectors:ListIndexes",
        "s3vectors:PutVectors",
        "s3vectors:GetVectors",
        "s3vectors:DeleteVectors",
        "s3vectors:QueryVectors"
      ],
      "Resource": [
        "arn:aws:s3vectors:'"$AWS_REGION"':'"$AWS_ACCOUNT_ID"':bucket/'"$VECTOR_BUCKET_NAME"'",
        "arn:aws:s3vectors:'"$AWS_REGION"':'"$AWS_ACCOUNT_ID"':bucket/'"$VECTOR_BUCKET_NAME"'/index/*"
      ]
    }
  ]
}'

aws iam put-role-policy \
    --role-name "$KB_ROLE_NAME" \
    --policy-name "BedrockKBPolicy" \
    --policy-document "$KB_POLICY"

echo -e "${GREEN}IAM role configured: $KB_ROLE_ARN${NC}"


# ============================================================================
# Step 2: Create S3 Source Bucket for Documents
# ============================================================================
echo -e "\n${YELLOW}Step 2: Creating S3 source bucket for documents...${NC}"

# Check if bucket exists
if aws s3api head-bucket --bucket "$SOURCE_BUCKET_NAME" 2>/dev/null; then
    echo -e "${GREEN}S3 source bucket already exists: $SOURCE_BUCKET_NAME${NC}"
else
    # Create bucket with region-appropriate configuration
    if [ "$AWS_REGION" = "us-east-1" ]; then
        # us-east-1 doesn't use LocationConstraint
        aws s3api create-bucket \
            --bucket "$SOURCE_BUCKET_NAME" \
            --region "$AWS_REGION"
    else
        aws s3api create-bucket \
            --bucket "$SOURCE_BUCKET_NAME" \
            --region "$AWS_REGION" \
            --create-bucket-configuration LocationConstraint="$AWS_REGION"
    fi
    echo -e "${GREEN}Created S3 source bucket: $SOURCE_BUCKET_NAME${NC}"
    
    # Create documents folder
    aws s3api put-object \
        --bucket "$SOURCE_BUCKET_NAME" \
        --key "documents/" \
        --region "$AWS_REGION"
    echo -e "${GREEN}Created documents/ folder in bucket${NC}"
fi


# ============================================================================
# Step 3: Create S3 Vector Bucket and Index
# ============================================================================
echo -e "\n${YELLOW}Step 3: Creating S3 vector bucket and index...${NC}"

# Check if vector bucket exists using get-vector-bucket (more reliable than list)
VECTOR_BUCKET_EXISTS=false
if aws s3vectors get-vector-bucket --vector-bucket-name "$VECTOR_BUCKET_NAME" --region "$AWS_REGION" > /dev/null 2>&1; then
    VECTOR_BUCKET_EXISTS=true
fi

if [ "$VECTOR_BUCKET_EXISTS" = true ]; then
    echo -e "${GREEN}S3 vector bucket already exists: $VECTOR_BUCKET_NAME${NC}"
else
    # Create vector bucket
    aws s3vectors create-vector-bucket \
        --vector-bucket-name "$VECTOR_BUCKET_NAME" \
        --region "$AWS_REGION"
    echo -e "${GREEN}Created S3 vector bucket: $VECTOR_BUCKET_NAME${NC}"
    
    # Wait for bucket to be ready
    echo -e "${YELLOW}Waiting for vector bucket to be ready...${NC}"
    sleep 5
fi

# Check if vector index exists using get-index (more reliable)
INDEX_EXISTS=false
if aws s3vectors get-index --vector-bucket-name "$VECTOR_BUCKET_NAME" --index-name "$VECTOR_INDEX_NAME" --region "$AWS_REGION" > /dev/null 2>&1; then
    INDEX_EXISTS=true
fi

if [ "$INDEX_EXISTS" = true ]; then
    echo -e "${GREEN}Vector index already exists: $VECTOR_INDEX_NAME${NC}"
else
    # Create vector index with 1024 dimensions (Titan Embed v2), float32, cosine distance
    # nonFilterableMetadataKeys are used by Bedrock KB for storing text chunks and metadata
    aws s3vectors create-index \
        --vector-bucket-name "$VECTOR_BUCKET_NAME" \
        --index-name "$VECTOR_INDEX_NAME" \
        --region "$AWS_REGION" \
        --data-type "float32" \
        --dimension 1024 \
        --distance-metric "cosine" \
        --metadata-configuration '{
            "nonFilterableMetadataKeys": ["AMAZON_BEDROCK_TEXT", "AMAZON_BEDROCK_METADATA"]
        }'
    echo -e "${GREEN}Created vector index: $VECTOR_INDEX_NAME${NC}"
    
    # Wait for index to be ready
    echo -e "${YELLOW}Waiting for vector index to be ready...${NC}"
    sleep 10
fi


# ============================================================================
# Step 4: Create Bedrock Knowledge Base
# ============================================================================
echo -e "\n${YELLOW}Step 4: Creating Bedrock Knowledge Base...${NC}"

# Check if KB already exists by name
EXISTING_KB=$(aws bedrock-agent list-knowledge-bases \
    --region "$AWS_REGION" \
    --query "knowledgeBaseSummaries[?name=='$KB_NAME'].knowledgeBaseId" \
    --output text 2>/dev/null || echo "")

if [ -n "$EXISTING_KB" ] && [ "$EXISTING_KB" != "None" ]; then
    echo -e "${GREEN}Knowledge Base already exists: $EXISTING_KB${NC}"
    KB_ID="$EXISTING_KB"
    KB_ARN=$(aws bedrock-agent get-knowledge-base \
        --knowledge-base-id "$KB_ID" \
        --region "$AWS_REGION" \
        --query 'knowledgeBase.knowledgeBaseArn' \
        --output text)
else
    # Create Knowledge Base with retry logic for IAM propagation
    MAX_RETRIES=5
    RETRY_COUNT=0
    KB_CREATED=false
    
    while [ "$KB_CREATED" = false ] && [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
        echo -e "${YELLOW}Attempting to create Knowledge Base (attempt $((RETRY_COUNT + 1))/$MAX_RETRIES)...${NC}"
        
        # Build ARNs for S3 Vectors (note: ARN uses "bucket/" not "vector-bucket/")
        VECTOR_BUCKET_ARN="arn:aws:s3vectors:${AWS_REGION}:${AWS_ACCOUNT_ID}:bucket/${VECTOR_BUCKET_NAME}"
        INDEX_ARN="arn:aws:s3vectors:${AWS_REGION}:${AWS_ACCOUNT_ID}:bucket/${VECTOR_BUCKET_NAME}/index/${VECTOR_INDEX_NAME}"
        
        KB_RESULT=$(aws bedrock-agent create-knowledge-base \
            --name "$KB_NAME" \
            --description "Knowledge Base for $APP_NAME agent" \
            --role-arn "$KB_ROLE_ARN" \
            --region "$AWS_REGION" \
            --knowledge-base-configuration '{
                "type": "VECTOR",
                "vectorKnowledgeBaseConfiguration": {
                    "embeddingModelArn": "arn:aws:bedrock:'"$AWS_REGION"'::foundation-model/amazon.titan-embed-text-v2:0"
                }
            }' \
            --storage-configuration '{
                "type": "S3_VECTORS",
                "s3VectorsConfiguration": {
                    "vectorBucketArn": "'"$VECTOR_BUCKET_ARN"'",
                    "indexArn": "'"$INDEX_ARN"'"
                }
            }' \
            --query '[knowledgeBase.knowledgeBaseId, knowledgeBase.knowledgeBaseArn]' \
            --output text 2>&1) && KB_CREATED=true
        
        if [ "$KB_CREATED" = false ]; then
            if echo "$KB_RESULT" | grep -q "role"; then
                echo -e "${YELLOW}IAM role not yet propagated, waiting 15 seconds...${NC}"
                sleep 15
                RETRY_COUNT=$((RETRY_COUNT + 1))
            else
                echo -e "${RED}Error creating Knowledge Base: $KB_RESULT${NC}"
                exit 1
            fi
        fi
    done
    
    if [ "$KB_CREATED" = false ]; then
        echo -e "${RED}Failed to create Knowledge Base after $MAX_RETRIES attempts${NC}"
        exit 1
    fi
    
    KB_ID=$(echo "$KB_RESULT" | awk '{print $1}')
    KB_ARN=$(echo "$KB_RESULT" | awk '{print $2}')
    echo -e "${GREEN}Created Knowledge Base: $KB_ID${NC}"
    
    # Wait for KB to be ready
    echo -e "${YELLOW}Waiting for Knowledge Base to be ready...${NC}"
    sleep 10
fi

echo -e "${GREEN}Knowledge Base ARN: $KB_ARN${NC}"


# ============================================================================
# Step 5: Create Data Source
# ============================================================================
echo -e "\n${YELLOW}Step 5: Creating Data Source...${NC}"

# Check if data source already exists
EXISTING_DS=$(aws bedrock-agent list-data-sources \
    --knowledge-base-id "$KB_ID" \
    --region "$AWS_REGION" \
    --query "dataSourceSummaries[?name=='$DATA_SOURCE_NAME'].dataSourceId" \
    --output text 2>/dev/null || echo "")

if [ -n "$EXISTING_DS" ] && [ "$EXISTING_DS" != "None" ]; then
    echo -e "${GREEN}Data source already exists: $EXISTING_DS${NC}"
    DATA_SOURCE_ID="$EXISTING_DS"
else
    # Create data source connecting KB to S3 source bucket
    DATA_SOURCE_ID=$(aws bedrock-agent create-data-source \
        --knowledge-base-id "$KB_ID" \
        --name "$DATA_SOURCE_NAME" \
        --description "S3 data source for $APP_NAME Knowledge Base" \
        --region "$AWS_REGION" \
        --data-source-configuration '{
            "type": "S3",
            "s3Configuration": {
                "bucketArn": "arn:aws:s3:::'"$SOURCE_BUCKET_NAME"'",
                "inclusionPrefixes": ["documents/"]
            }
        }' \
        --data-deletion-policy "RETAIN" \
        --query 'dataSource.dataSourceId' \
        --output text)
    
    echo -e "${GREEN}Created data source: $DATA_SOURCE_ID${NC}"
fi


# ============================================================================
# Step 6: Update IAM Roles for KB Access
# ============================================================================
echo -e "\n${YELLOW}Step 6: Updating IAM roles for Knowledge Base access...${NC}"

# KB access policy document
KB_ACCESS_POLICY="{
  \"Version\": \"2012-10-17\",
  \"Statement\": [
    {
      \"Sid\": \"BedrockKBAccess\",
      \"Effect\": \"Allow\",
      \"Action\": [
        \"bedrock:Retrieve\",
        \"bedrock:RetrieveAndGenerate\"
      ],
      \"Resource\": [
        \"arn:aws:bedrock:$AWS_REGION:$AWS_ACCOUNT_ID:knowledge-base/$KB_ID\"
      ]
    }
  ]
}"

# Update ECS task role (for chatapp)
TASK_ROLE_NAME="htmx-chatapp-task-role"
if aws iam get-role --role-name "$TASK_ROLE_NAME" > /dev/null 2>&1; then
    aws iam put-role-policy \
        --role-name "$TASK_ROLE_NAME" \
        --policy-name "BedrockKBAccess" \
        --policy-document "$KB_ACCESS_POLICY"
    echo -e "${GREEN}Updated ECS task role with Knowledge Base permissions${NC}"
else
    echo -e "${YELLOW}ECS task role not found. Run setup-iam.sh first if using ECS.${NC}"
fi

# Update AgentCore Runtime role (for agent)
# The AgentCore SDK creates runtime roles with pattern: AmazonBedrockAgentCoreSDKRuntime-{region}-{hash}
echo -e "${YELLOW}Looking for AgentCore Runtime roles...${NC}"
AGENTCORE_ROLES=$(aws iam list-roles \
    --query "Roles[?starts_with(RoleName, 'AmazonBedrockAgentCoreSDKRuntime-${AWS_REGION}')].RoleName" \
    --output text 2>/dev/null | tr '\t' '\n')

if [ -n "$AGENTCORE_ROLES" ]; then
    for ROLE_NAME in $AGENTCORE_ROLES; do
        echo -e "${YELLOW}Adding KB permissions to: $ROLE_NAME${NC}"
        aws iam put-role-policy \
            --role-name "$ROLE_NAME" \
            --policy-name "BedrockKBAccess" \
            --policy-document "$KB_ACCESS_POLICY" 2>/dev/null && \
        echo -e "${GREEN}Updated $ROLE_NAME with Knowledge Base permissions${NC}" || \
        echo -e "${YELLOW}Could not update $ROLE_NAME (may not have permission)${NC}"
    done
else
    echo -e "${YELLOW}No AgentCore Runtime roles found. Deploy the agent first, then re-run this script.${NC}"
fi

# ============================================================================
# Step 7: Export Values and Output
# ============================================================================
echo ""
echo -e "${GREEN}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║         Knowledge Base Setup Complete!                     ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${BLUE}Knowledge Base Details:${NC}"
echo "  KB ID: $KB_ID"
echo "  KB ARN: $KB_ARN"
echo "  KB Role ARN: $KB_ROLE_ARN"
echo "  Source Bucket: $SOURCE_BUCKET_NAME"
echo "  Vector Bucket: $VECTOR_BUCKET_NAME"
echo "  Vector Index: $VECTOR_INDEX_NAME"
echo "  Data Source ID: $DATA_SOURCE_ID"
echo ""

# Export environment variables for downstream scripts
export KB_ID
export KB_ARN
export SOURCE_BUCKET="$SOURCE_BUCKET_NAME"

# Write values to temp files for use by setup.sh
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMP_DIR="/tmp/kb-setup"
mkdir -p "$TEMP_DIR"

echo "$KB_ID" > "$TEMP_DIR/kb_id"
echo "$KB_ARN" > "$TEMP_DIR/kb_arn"
echo "$SOURCE_BUCKET_NAME" > "$TEMP_DIR/source_bucket"

# Only show manual instructions if not in auto mode
if [ "$AUTO_YES" = false ]; then
    echo -e "${BLUE}Add these values to your .env files:${NC}"
    echo ""
    echo "# Agent .env (agent/.env)"
    echo "KB_ID=${KB_ID}"
    echo ""
    echo "# ChatApp .env (chatapp/.env)"
    echo "KB_ID=${KB_ID}"
    echo ""
    echo -e "${YELLOW}Next Steps:${NC}"
    echo "1. Upload documents to s3://${SOURCE_BUCKET_NAME}/documents/"
    echo "2. Sync the Knowledge Base:"
    echo "   aws bedrock-agent start-ingestion-job --knowledge-base-id $KB_ID --data-source-id $DATA_SOURCE_ID --region $AWS_REGION"
    echo "3. Update your .env files with KB_ID"
    echo "4. Redeploy the agent and chatapp to apply changes"
    echo ""
else
    echo -e "${GREEN}KB config will be automatically applied by setup.sh${NC}"
    echo ""
fi

# Optionally update .env files
CHATAPP_DIR="$(dirname "$SCRIPT_DIR")"
AGENT_DIR="$(dirname "$CHATAPP_DIR")/agent"
CHATAPP_ENV_FILE="$CHATAPP_DIR/.env"
AGENT_ENV_FILE="$AGENT_DIR/.env"

update_env_file() {
    local ENV_FILE="$1"
    local FILE_NAME="$2"
    
    if [ -f "$ENV_FILE" ]; then
        if [ "$AUTO_YES" = true ]; then
            REPLY="y"
        else
            echo -e "${YELLOW}Would you like to update $FILE_NAME automatically? (y/n)${NC}"
            read -r REPLY
        fi
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            # Update or add KB_ID
            if grep -q "^KB_ID=" "$ENV_FILE"; then
                sed -i.bak "s|^KB_ID=.*|KB_ID=${KB_ID}|" "$ENV_FILE"
            else
                echo "KB_ID=${KB_ID}" >> "$ENV_FILE"
            fi
            
            rm -f "$ENV_FILE.bak"
            echo -e "${GREEN}$FILE_NAME updated!${NC}"
        fi
    fi
}

update_env_file "$CHATAPP_ENV_FILE" "chatapp/.env"
update_env_file "$AGENT_ENV_FILE" "agent/.env"
