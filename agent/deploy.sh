#!/bin/bash
# Deployment script for AgentCore agent with environment variables
# Creates memory with LTM strategies if needed, then deploys the agent
#
# Usage: ./deploy.sh [--fresh]
#   --fresh  Clear existing config and start fresh (useful for IAM role issues)

set -e

# Disable AWS CLI pager
export AWS_PAGER=""

# Activate virtual environment if it exists
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/.venv/bin/activate" ]; then
    source "$SCRIPT_DIR/.venv/bin/activate"
fi

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Parse arguments
FRESH_DEPLOY=false
while [[ $# -gt 0 ]]; do
    case $1 in
        --fresh)
            FRESH_DEPLOY=true
            shift
            ;;
        *)
            shift
            ;;
    esac
done

# Clear old config if --fresh flag is set
if [ "$FRESH_DEPLOY" = true ]; then
    echo -e "${YELLOW}Fresh deploy requested - clearing old configuration...${NC}"
    rm -rf .bedrock_agentcore .bedrock_agentcore.yaml
fi

# Load environment variables from .env file if it exists
if [ -f .env ]; then
    echo "Loading environment variables from .env file..."
    export $(cat .env | grep -v '^#' | xargs)
fi

# Set defaults
LOG_LEVEL=${LOG_LEVEL:-INFO}
AWS_REGION=${AWS_REGION:-us-east-1}
GUARDRAIL_VERSION=${GUARDRAIL_VERSION:-1}
GUARDRAIL_ENABLED=${GUARDRAIL_ENABLED:-true}
MEMORY_NAME="chat_app_mem"
AGENT_NAME="chat_app"

# Auto-detect guardrail settings if not set
if [ -z "$GUARDRAIL_ID" ] || [ -z "$GUARDRAIL_VERSION" ] || [ "$GUARDRAIL_VERSION" = "DRAFT" ]; then
    # Try to load from chatapp/.env as fallback
    if [ -f "../chatapp/.env" ]; then
        if [ -z "$GUARDRAIL_ID" ]; then
            GUARDRAIL_ID=$(grep "^GUARDRAIL_ID=" "../chatapp/.env" 2>/dev/null | cut -d'=' -f2 | tr -d '"' | tr -d "'")
            if [ -n "$GUARDRAIL_ID" ]; then
                echo -e "${BLUE}Loaded GUARDRAIL_ID from chatapp/.env${NC}"
            fi
        fi
        CHATAPP_VERSION=$(grep "^GUARDRAIL_VERSION=" "../chatapp/.env" 2>/dev/null | cut -d'=' -f2 | tr -d '"' | tr -d "'")
        if [ -n "$CHATAPP_VERSION" ] && [ "$CHATAPP_VERSION" != "DRAFT" ]; then
            GUARDRAIL_VERSION="$CHATAPP_VERSION"
            echo -e "${BLUE}Loaded GUARDRAIL_VERSION from chatapp/.env: $GUARDRAIL_VERSION${NC}"
        fi
    fi
fi

# Auto-detect KB_ID if not set
if [ -z "$KB_ID" ]; then
    # Try to load from chatapp/.env as fallback
    if [ -f "../chatapp/.env" ]; then
        KB_ID=$(grep "^KB_ID=" "../chatapp/.env" 2>/dev/null | cut -d'=' -f2 | tr -d '"' | tr -d "'")
        if [ -n "$KB_ID" ] && [ "$KB_ID" != "None" ] && [ "$KB_ID" != "null" ]; then
            echo -e "${BLUE}Loaded KB_ID from chatapp/.env: $KB_ID${NC}"
        else
            KB_ID=""
        fi
    fi
fi

# If still not set, try to auto-detect from AWS (look for app-specific guardrail)
if [ -z "$GUARDRAIL_ID" ]; then
    echo -e "${YELLOW}Auto-detecting guardrail from AWS...${NC}"
    GUARDRAIL_NAME="agentcore-chatapp-guardrail"
    GUARDRAIL_ID=$(aws bedrock list-guardrails --region "$AWS_REGION" --query "guardrails[?name=='$GUARDRAIL_NAME'].id | [0]" --output text 2>/dev/null || echo "")
    if [ -n "$GUARDRAIL_ID" ] && [ "$GUARDRAIL_ID" != "None" ] && [ "$GUARDRAIL_ID" != "null" ]; then
        echo -e "${GREEN}Found guardrail '$GUARDRAIL_NAME': $GUARDRAIL_ID${NC}"
    else
        echo -e "${YELLOW}No guardrail named '$GUARDRAIL_NAME' found${NC}"
        GUARDRAIL_ID=""
    fi
fi

echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║           AgentCore Agent Deployment                       ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${YELLOW}Configuration:${NC}"
echo "  Region: $AWS_REGION"
echo "  LOG_LEVEL: $LOG_LEVEL"
echo ""

# Check if memory exists in config
CONFIG_FILE=".bedrock_agentcore.yaml"
MEMORY_EXISTS=false
MEMORY_ID=""

if [ -f "$CONFIG_FILE" ]; then
    EXISTING_MEMORY_ID=$(grep "memory_id:" "$CONFIG_FILE" 2>/dev/null | head -1 | sed 's/.*memory_id: //' | tr -d ' ')
    if [ -n "$EXISTING_MEMORY_ID" ] && [ "$EXISTING_MEMORY_ID" != "null" ]; then
        echo -e "${GREEN}Memory already configured: $EXISTING_MEMORY_ID${NC}"
        MEMORY_EXISTS=true
        MEMORY_ID="$EXISTING_MEMORY_ID"
    fi
fi

# Create memory with LTM strategies if it doesn't exist
if [ "$MEMORY_EXISTS" = false ]; then
    echo -e "${YELLOW}Step 1: Creating memory with LTM strategies...${NC}"
    
    # Check if memory with this name already exists
    EXISTING_MEM=$(agentcore memory list --region "$AWS_REGION" 2>/dev/null | grep "$MEMORY_NAME" | head -1 || echo "")
    
    if [ -n "$EXISTING_MEM" ]; then
        # Extract memory ID from the list output
        MEMORY_ID=$(echo "$EXISTING_MEM" | awk '{print $1}')
        echo -e "${GREEN}Found existing memory: $MEMORY_ID${NC}"
    else
        # Define LTM strategies (semantic, summary, user preference)
        STRATEGIES='[{"semanticMemoryStrategy":{"name":"SemanticFacts","namespaces":["/users/{actorId}/facts"]}},{"summaryMemoryStrategy":{"name":"SessionSummaries","namespaces":["/summaries/{actorId}/{sessionId}"]}},{"userPreferenceMemoryStrategy":{"name":"UserPreferences","namespaces":["/users/{actorId}/preferences"]}}]'
        
        # Create memory with strategies
        echo -e "${YELLOW}Creating memory resource with LTM strategies...${NC}"
        CREATE_OUTPUT=$(agentcore memory create "$MEMORY_NAME" \
            --region "$AWS_REGION" \
            --description "Memory for AgentCore chat agent with LTM strategies" \
            --event-expiry-days 30 \
            --strategies "$STRATEGIES" \
            --wait 2>&1)
        
        echo "$CREATE_OUTPUT"
        
        # Extract memory ID from output
        MEMORY_ID=$(echo "$CREATE_OUTPUT" | grep -oE '[a-zA-Z0-9_]+-[a-zA-Z0-9]+' | head -1)
        
        if [ -z "$MEMORY_ID" ]; then
            # Try to get it from the list
            MEMORY_ID=$(agentcore memory list --region "$AWS_REGION" 2>/dev/null | grep "$MEMORY_NAME" | awk '{print $1}' | head -1)
        fi
        
        echo -e "${GREEN}Memory created with LTM strategies: $MEMORY_ID${NC}"
    fi
    
fi

# If no config file exists, we need to run configure
if [ ! -f "$CONFIG_FILE" ]; then
    echo -e "${YELLOW}Step 2: Configuring agent...${NC}"
    # Use container deployment type for cross-region compatibility
    # --ecr auto lets AgentCore create/manage ECR repo
    agentcore configure \
        --entrypoint my_agent.py \
        --name "$AGENT_NAME" \
        --region "$AWS_REGION" \
        --deployment-type container \
        --ecr auto
    
    # Verify config was created
    if [ ! -f "$CONFIG_FILE" ]; then
        echo -e "${RED}Error: agentcore configure did not create config file${NC}"
        exit 1
    fi
fi

# Deploy with environment variables
echo -e "${YELLOW}Deploying agent...${NC}"

# Build env args - always include LOG_LEVEL
ENV_ARGS="--env LOG_LEVEL=$LOG_LEVEL"

# Add guardrail config if GUARDRAIL_ID is set
if [ -n "$GUARDRAIL_ID" ]; then
    ENV_ARGS="$ENV_ARGS --env GUARDRAIL_ID=$GUARDRAIL_ID --env GUARDRAIL_VERSION=$GUARDRAIL_VERSION --env GUARDRAIL_ENABLED=$GUARDRAIL_ENABLED"
    echo -e "${BLUE}Guardrail enabled: $GUARDRAIL_ID (version: $GUARDRAIL_VERSION)${NC}"
else
    echo -e "${YELLOW}Note: GUARDRAIL_ID not set - guardrail evaluation will be skipped${NC}"
fi

# Add Knowledge Base config if KB_ID is set
if [ -n "$KB_ID" ]; then
    ENV_ARGS="$ENV_ARGS --env KB_ID=$KB_ID"
    # Add optional KB config if set
    if [ -n "$KB_MAX_RESULTS" ]; then
        ENV_ARGS="$ENV_ARGS --env KB_MAX_RESULTS=$KB_MAX_RESULTS"
    fi
    if [ -n "$KB_MIN_SCORE" ]; then
        ENV_ARGS="$ENV_ARGS --env KB_MIN_SCORE=$KB_MIN_SCORE"
    fi
    echo -e "${BLUE}Knowledge Base enabled: $KB_ID${NC}"
else
    echo -e "${YELLOW}Note: KB_ID not set - Knowledge Base tool will be disabled${NC}"
fi

# Use CodeBuild for container builds (ARM64 architecture)
agentcore launch \
  --auto-update-on-conflict \
  $ENV_ARGS

echo ""
echo -e "${CYAN}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║           AgentCore Deployment Complete!                   ║${NC}"
echo -e "${CYAN}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Show config values for reference
if [ -f "$CONFIG_FILE" ]; then
    RUNTIME_ARN=$(grep "agent_arn:" "$CONFIG_FILE" | head -1 | sed 's/.*agent_arn: //' | tr -d ' ')
    MEMORY_ID=$(grep "memory_id:" "$CONFIG_FILE" | head -1 | sed 's/.*memory_id: //' | tr -d ' ')
    REGION=$(grep "region:" "$CONFIG_FILE" | head -1 | sed 's/.*region: //' | tr -d ' ')
    
    echo -e "${BLUE}Configuration (from .bedrock_agentcore.yaml):${NC}"
    echo "  Runtime ARN: $RUNTIME_ARN"
    echo "  Memory ID: $MEMORY_ID"
    echo "  Region: $REGION"
    echo ""
    echo -e "${BLUE}LTM Strategies configured:${NC}"
    echo "  - SemanticFacts: /users/{actorId}/facts"
    echo "  - SessionSummaries: /summaries/{actorId}/{sessionId}"
    echo "  - UserPreferences: /users/{actorId}/preferences"
    echo ""
    if [ -n "$GUARDRAIL_ID" ]; then
        echo -e "${BLUE}Guardrail Configuration:${NC}"
        echo "  Guardrail ID: $GUARDRAIL_ID"
        echo "  Version: $GUARDRAIL_VERSION"
        echo "  Enabled: $GUARDRAIL_ENABLED"
    else
        echo -e "${YELLOW}Guardrail: Not configured (set GUARDRAIL_ID in .env to enable)${NC}"
    fi
fi
