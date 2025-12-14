#!/bin/bash
# Set up observability infrastructure for AgentCore agent
# - Enables CloudWatch Transaction Search for X-Ray traces (one-time per account)
# - Configures log delivery and tracing for Runtime
#
# Note: AgentCore Runtime automatically provides metrics via the GenAI Observability
# dashboard including session count, latency, token usage, and error rates.
#
# Usage: ./setup-observability.sh [--skip-transaction-search] [--runtime-arn <arn>]

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

# Configuration
AWS_REGION="${AWS_REGION:-us-east-1}"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
SKIP_TRANSACTION_SEARCH=false
SKIP_LOG_DELIVERY=false
RUNTIME_ARN=""
SAMPLING_PERCENTAGE=100  # Default to 100% for POC/starter apps

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-transaction-search)
            SKIP_TRANSACTION_SEARCH=true
            shift
            ;;
        --skip-log-delivery)
            SKIP_LOG_DELIVERY=true
            shift
            ;;
        --region)
            AWS_REGION="$2"
            shift 2
            ;;
        --runtime-arn)
            RUNTIME_ARN="$2"
            shift 2
            ;;
        --sampling-percentage)
            SAMPLING_PERCENTAGE="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: ./setup-observability.sh [options]"
            echo ""
            echo "Options:"
            echo "  --skip-transaction-search    Skip CloudWatch Transaction Search setup"
            echo "  --skip-log-delivery          Skip Runtime log delivery and tracing setup"
            echo "  --runtime-arn <arn>          AgentCore Runtime ARN (auto-detected from config if not provided)"
            echo "  --sampling-percentage <n>    Percentage of traces to index (default: 100, free tier: 1)"
            echo "  --region <region>            AWS region (default: us-east-1)"
            echo "  -h, --help                   Show this help message"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

# Try to get runtime ARN from agent config if not provided
if [ -z "$RUNTIME_ARN" ]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    AGENT_CONFIG="$SCRIPT_DIR/../.bedrock_agentcore.yaml"
    if [ -f "$AGENT_CONFIG" ]; then
        RUNTIME_ARN=$(grep "agent_arn:" "$AGENT_CONFIG" | head -1 | sed 's/.*agent_arn: //' | tr -d ' ')
    fi
fi

echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     AgentCore Observability Setup                          ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${YELLOW}Configuration:${NC}"
echo "  AWS Region: $AWS_REGION"
echo "  Account ID: $ACCOUNT_ID"
echo "  Runtime ARN: ${RUNTIME_ARN:-not set}"
echo "  Sampling: ${SAMPLING_PERCENTAGE}%"
echo ""

# ============================================================================
# STEP 1: Enable CloudWatch Transaction Search (one-time setup)
# ============================================================================
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Step 1: CloudWatch Transaction Search${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

if [ "$SKIP_TRANSACTION_SEARCH" = true ]; then
    echo -e "${YELLOW}Skipping Transaction Search setup (--skip-transaction-search)${NC}"
else
    # Check if Transaction Search is already enabled
    CURRENT_DEST=$(aws xray get-trace-segment-destination --region "$AWS_REGION" 2>/dev/null | grep -o '"Destination": "[^"]*"' | cut -d'"' -f4 || echo "")
    
    if [ "$CURRENT_DEST" = "CloudWatchLogs" ]; then
        echo -e "${GREEN}Transaction Search already enabled${NC}"
    else
        echo -e "${YELLOW}Creating resource policy for X-Ray to CloudWatch Logs...${NC}"
        
        # Create resource policy
        POLICY_DOC=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "TransactionSearchXRayAccess",
      "Effect": "Allow",
      "Principal": {
        "Service": "xray.amazonaws.com"
      },
      "Action": "logs:PutLogEvents",
      "Resource": [
        "arn:aws:logs:${AWS_REGION}:${ACCOUNT_ID}:log-group:aws/spans:*",
        "arn:aws:logs:${AWS_REGION}:${ACCOUNT_ID}:log-group:/aws/application-signals/data:*"
      ],
      "Condition": {
        "ArnLike": {
          "aws:SourceArn": "arn:aws:xray:${AWS_REGION}:${ACCOUNT_ID}:*"
        },
        "StringEquals": {
          "aws:SourceAccount": "${ACCOUNT_ID}"
        }
      }
    }
  ]
}
EOF
)
        
        aws logs put-resource-policy \
            --policy-name "AgentCoreTracingPolicy" \
            --policy-document "$POLICY_DOC" \
            --region "$AWS_REGION" 2>/dev/null || echo -e "${YELLOW}Resource policy may already exist${NC}"
        
        echo -e "${YELLOW}Enabling Transaction Search (X-Ray to CloudWatch Logs)...${NC}"
        aws xray update-trace-segment-destination \
            --destination CloudWatchLogs \
            --region "$AWS_REGION" 2>/dev/null || echo -e "${YELLOW}Transaction Search may already be enabled${NC}"
        
        echo -e "${GREEN}Transaction Search enabled - traces will appear in CloudWatch${NC}"
        echo -e "${YELLOW}Note: It may take up to 10 minutes for spans to become available${NC}"
    fi
    
    # Configure sampling percentage
    echo -e "${YELLOW}Setting trace sampling to ${SAMPLING_PERCENTAGE}%...${NC}"
    aws xray update-indexing-rule \
        --name "Default" \
        --rule "{\"Probabilistic\": {\"DesiredSamplingPercentage\": ${SAMPLING_PERCENTAGE}}}" \
        --region "$AWS_REGION" 2>/dev/null || echo -e "${YELLOW}Could not update sampling rule${NC}"
    echo -e "${GREEN}Trace sampling set to ${SAMPLING_PERCENTAGE}%${NC}"
fi

# ============================================================================
# STEP 2: Configure Runtime Log Delivery and Tracing
# ============================================================================
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Step 2: Runtime Log Delivery and Tracing${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

if [ "$SKIP_LOG_DELIVERY" = true ]; then
    echo -e "${YELLOW}Skipping log delivery setup (--skip-log-delivery)${NC}"
elif [ -z "$RUNTIME_ARN" ]; then
    echo -e "${YELLOW}No Runtime ARN found - skipping log delivery setup${NC}"
    echo "To configure log delivery, either:"
    echo "  1. Deploy the agent first (agentcore launch)"
    echo "  2. Provide --runtime-arn <arn> argument"
else
    # Extract runtime ID from ARN for naming
    # ARN format: arn:aws:bedrock-agentcore:region:account:runtime/runtime-id
    RUNTIME_ID=$(echo "$RUNTIME_ARN" | sed 's/.*runtime\///')
    
    echo -e "${YELLOW}Configuring log delivery for runtime: $RUNTIME_ID${NC}"
    
    # Create log group for vended logs if it doesn't exist
    LOG_GROUP_NAME="/aws/vendedlogs/bedrock-agentcore/runtime/${RUNTIME_ID}"
    
    echo -e "${YELLOW}Creating log group: $LOG_GROUP_NAME${NC}"
    aws logs create-log-group \
        --log-group-name "$LOG_GROUP_NAME" \
        --region "$AWS_REGION" 2>/dev/null || echo -e "${YELLOW}Log group may already exist${NC}"
    
    LOG_GROUP_ARN="arn:aws:logs:${AWS_REGION}:${ACCOUNT_ID}:log-group:${LOG_GROUP_NAME}"
    
    # Create delivery source for logs
    echo -e "${YELLOW}Creating delivery source for logs...${NC}"
    aws logs put-delivery-source \
        --name "${RUNTIME_ID}-logs-source" \
        --log-type "APPLICATION_LOGS" \
        --resource-arn "$RUNTIME_ARN" \
        --region "$AWS_REGION" 2>/dev/null || echo -e "${YELLOW}Delivery source may already exist${NC}"
    
    # Create delivery source for traces
    echo -e "${YELLOW}Creating delivery source for traces...${NC}"
    aws logs put-delivery-source \
        --name "${RUNTIME_ID}-traces-source" \
        --log-type "TRACES" \
        --resource-arn "$RUNTIME_ARN" \
        --region "$AWS_REGION" 2>/dev/null || echo -e "${YELLOW}Delivery source may already exist${NC}"
    
    # Create delivery destination for logs (CloudWatch Logs)
    echo -e "${YELLOW}Creating delivery destination for logs...${NC}"
    aws logs put-delivery-destination \
        --name "${RUNTIME_ID}-logs-destination" \
        --delivery-destination-type "CWL" \
        --delivery-destination-configuration "destinationResourceArn=${LOG_GROUP_ARN}" \
        --region "$AWS_REGION" 2>/dev/null || echo -e "${YELLOW}Delivery destination may already exist${NC}"
    
    # Get the destination ARN
    LOGS_DEST_ARN=$(aws logs describe-delivery-destinations \
        --region "$AWS_REGION" \
        --query "deliveryDestinations[?name=='${RUNTIME_ID}-logs-destination'].arn" \
        --output text 2>/dev/null || echo "")
    
    # Create delivery destination for traces (X-Ray)
    echo -e "${YELLOW}Creating delivery destination for traces (X-Ray)...${NC}"
    aws logs put-delivery-destination \
        --name "${RUNTIME_ID}-traces-destination" \
        --delivery-destination-type "XRAY" \
        --region "$AWS_REGION" 2>/dev/null || echo -e "${YELLOW}Delivery destination may already exist${NC}"
    
    # Get the traces destination ARN
    TRACES_DEST_ARN=$(aws logs describe-delivery-destinations \
        --region "$AWS_REGION" \
        --query "deliveryDestinations[?name=='${RUNTIME_ID}-traces-destination'].arn" \
        --output text 2>/dev/null || echo "")
    
    # Create deliveries (connect sources to destinations)
    if [ -n "$LOGS_DEST_ARN" ]; then
        echo -e "${YELLOW}Creating log delivery...${NC}"
        aws logs create-delivery \
            --delivery-source-name "${RUNTIME_ID}-logs-source" \
            --delivery-destination-arn "$LOGS_DEST_ARN" \
            --region "$AWS_REGION" 2>/dev/null || echo -e "${YELLOW}Log delivery may already exist${NC}"
    fi
    
    if [ -n "$TRACES_DEST_ARN" ]; then
        echo -e "${YELLOW}Creating trace delivery...${NC}"
        aws logs create-delivery \
            --delivery-source-name "${RUNTIME_ID}-traces-source" \
            --delivery-destination-arn "$TRACES_DEST_ARN" \
            --region "$AWS_REGION" 2>/dev/null || echo -e "${YELLOW}Trace delivery may already exist${NC}"
    fi
    
    echo -e "${GREEN}Log delivery and tracing configured for runtime${NC}"
fi

# ============================================================================
# COMPLETE
# ============================================================================
echo ""
echo -e "${GREEN}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║     Observability Setup Complete!                          ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${CYAN}What's configured:${NC}"
echo "  ✓ CloudWatch Transaction Search (X-Ray traces, ${SAMPLING_PERCENTAGE}% sampling)"
if [ -n "$RUNTIME_ARN" ] && [ "$SKIP_LOG_DELIVERY" != true ]; then
    echo "  ✓ Runtime log delivery to CloudWatch Logs"
    echo "  ✓ Runtime tracing delivery to X-Ray"
fi
echo ""
echo -e "${CYAN}Built-in metrics (via GenAI Observability dashboard):${NC}"
echo "  • Session count, latency, duration"
echo "  • Token usage (input/output)"
echo "  • Error rates"
echo "  • Tool execution traces"
echo ""
echo -e "${CYAN}View your observability data:${NC}"
echo "  GenAI Dashboard: https://${AWS_REGION}.console.aws.amazon.com/cloudwatch/home?region=${AWS_REGION}#gen-ai-observability/agent-core/agents"
echo "  Runtime Console: https://${AWS_REGION}.console.aws.amazon.com/bedrock-agentcore/agents"
echo "  Traces: https://${AWS_REGION}.console.aws.amazon.com/cloudwatch/home?region=${AWS_REGION}#xray:service-map"
echo ""
echo -e "${YELLOW}Note: You can also enable tracing via the AgentCore console:${NC}"
echo "  1. Go to Runtime Console URL above"
echo "  2. Select your agent (htmx_chatapp)"
echo "  3. In 'Tracing' section, click Edit and Enable"
echo "  4. For Identity tracing, go to Identity tab and enable there"
echo ""
