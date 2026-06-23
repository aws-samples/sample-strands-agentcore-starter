#!/bin/bash
# CDK Deployment Script for AgentCore Chat Application
# This script deploys all CDK stacks in the correct dependency order.
# All Docker builds are handled by AWS CodeBuild - no local Docker required.
#
# Usage: ./deploy-all.sh [options]
#   --region <region>    AWS region (default: us-east-1)
#   --profile <profile>  AWS CLI profile to use
#   --ingress <mode>     Ingress mode: ecs, furl, or both (default: ecs)
#   --skip-chatapp       Deploy Foundation + Bedrock + Agent only (skip ChatApp)
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
INGRESS_MODE="furl"
SKIP_CHATAPP=false
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
        --ingress)
            INGRESS_MODE="$2"
            # Validate ingress mode
            if [[ "$INGRESS_MODE" != "ecs" && "$INGRESS_MODE" != "furl" && "$INGRESS_MODE" != "both" ]]; then
                echo -e "${RED}Error: Invalid ingress mode '$INGRESS_MODE'. Must be: ecs, furl, or both${NC}"
                exit 1
            fi
            shift 2
            ;;
        --skip-chatapp)
            SKIP_CHATAPP=true
            shift
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
            echo "  --ingress <mode>     Ingress mode: ecs, furl, or both (default: ecs)"
            echo "  --skip-chatapp       Deploy Foundation + Bedrock + Agent only (skip ChatApp)"
            echo "  --dry-run            Show what would be deployed without deploying"
            echo "  -h, --help           Show this help message"
            echo ""
            echo "Ingress Modes:"
            echo "  ecs    - Deploy with ECS Express Gateway (~\$59.70/mo)"
            echo "  furl   - Deploy with CloudFront + Lambda Web Adapter (default, ~\$4.60/mo)"
            echo "  both   - Deploy both ECS and Lambda simultaneously"
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
echo "  Ingress Mode: $INGRESS_MODE"
echo "  Skip ChatApp: $SKIP_CHATAPP"
echo "  Dry Run: $DRY_RUN"
echo ""

if [ "$DRY_RUN" = true ]; then
    echo -e "${CYAN}DRY RUN MODE - No resources will be deployed${NC}"
    echo ""
fi

# Change to CDK directory
cd "$SCRIPT_DIR"

APP_NAME="${APP_NAME:-htmx-chatapp}"

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
    echo -e "${YELLOW}CDK not bootstrapped in $AWS_REGION. Running cdk bootstrap...${NC}"
    if [ "$DRY_RUN" != true ]; then
        npx cdk bootstrap "aws://$AWS_ACCOUNT_ID/$AWS_REGION"
    else
        echo -e "${CYAN}[DRY RUN] Would run: cdk bootstrap aws://$AWS_ACCOUNT_ID/$AWS_REGION${NC}"
    fi
else
    echo -e "${GREEN}CDK already bootstrapped in $AWS_REGION${NC}"
fi

# Bootstrap us-east-1 for Lambda@Edge (required for CloudFront)
if [ "$AWS_REGION" != "us-east-1" ]; then
    BOOTSTRAP_USEAST1=$(aws cloudformation describe-stacks \
        --stack-name CDKToolkit \
        --region "us-east-1" \
        --query 'Stacks[0].StackStatus' \
        --output text 2>/dev/null || echo "NOT_FOUND")
    
    if [ "$BOOTSTRAP_USEAST1" = "NOT_FOUND" ]; then
        echo -e "${YELLOW}CDK not bootstrapped in us-east-1 (required for Lambda@Edge). Running cdk bootstrap...${NC}"
        if [ "$DRY_RUN" != true ]; then
            npx cdk bootstrap "aws://$AWS_ACCOUNT_ID/us-east-1"
        else
            echo -e "${CYAN}[DRY RUN] Would run: cdk bootstrap aws://$AWS_ACCOUNT_ID/us-east-1${NC}"
        fi
    else
        echo -e "${GREEN}CDK already bootstrapped in us-east-1 (for Lambda@Edge)${NC}"
    fi
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
# Note: cdk-nag may report errors, but we continue deployment
# Security findings are logged to cdk.out/AwsSolutions-NagReport.csv
npx cdk synth --quiet || echo -e "${YELLOW}Note: cdk-nag reported findings (check cdk.out/AwsSolutions-NagReport.csv)${NC}"

echo -e "${GREEN}Synthesis complete${NC}"

# ============================================================================
# STEP 4: Deploy all stacks
# CDK automatically deploys stacks in dependency order:
# Foundation → Bedrock → Agent → ChatApp
# ============================================================================
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Step 4: Deploy all stack${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

if [ "$DRY_RUN" = true ]; then
    echo -e "${CYAN}[DRY RUN] Would deploy all stacks${NC}"
    echo ""
    echo -e "${YELLOW}Stacks that would be deployed:${NC}"
    npx cdk list
else
    echo -e "${YELLOW}Deploying all stacks...${NC}"
    echo ""
    
    if [ "$SKIP_CHATAPP" = true ]; then
        # Deploy Agent stack (pulls in Foundation + Bedrock as dependencies)
        npx cdk deploy \
            "${APP_NAME}-Agent" \
            --context ingress="$INGRESS_MODE" \
            --require-approval never \
            --outputs-file cdk-outputs.json
    else
        npx cdk deploy \
            "${APP_NAME}-ChatApp" \
            --context ingress="$INGRESS_MODE" \
            --require-approval never \
            --outputs-file cdk-outputs.json
    fi
    
    echo -e "${GREEN}All stacks deployed${NC}"
fi

# ============================================================================
# STEP 4.5: Rebuild agent container and refresh AgentCore Runtime
# ----------------------------------------------------------------------------
# CDK's custom resource for triggering CodeBuild only fires when CloudFormation
# detects a property change (which doesn't happen when only S3 content changes).
# This step explicitly triggers CodeBuild, waits for it, then forces the
# AgentCore Runtime to re-pull the new :latest image.
# ============================================================================
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Step 4.5: Rebuild agent & refresh AgentCore Runtime${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

if [ "$DRY_RUN" = true ]; then
    echo -e "${CYAN}[DRY RUN] Would trigger CodeBuild and UpdateAgentRuntime${NC}"
else
    # --- Trigger CodeBuild directly ---
    BUILD_PROJECT="${APP_NAME}-agent-build"
    SOURCE_BUCKET="${APP_NAME}-build-source-${AWS_ACCOUNT_ID}-${AWS_REGION}"

    echo -e "${YELLOW}Triggering agent CodeBuild: ${BUILD_PROJECT}${NC}"
    BUILD_ID=$(aws codebuild start-build \
        --project-name "$BUILD_PROJECT" \
        --source-type-override S3 \
        --source-location-override "${SOURCE_BUCKET}/agent-source/" \
        --region "$AWS_REGION" \
        --query 'build.id' \
        --output text 2>&1)

    if [ $? -ne 0 ] || [ -z "$BUILD_ID" ] || [ "$BUILD_ID" = "None" ]; then
        echo -e "${RED}Failed to start CodeBuild: ${BUILD_ID}${NC}"
    else
        echo -e "${GREEN}CodeBuild started: ${BUILD_ID}${NC}"
        echo -e "${YELLOW}Waiting for build to complete...${NC}"

        # Wait for build (up to 10 minutes)
        for i in {1..40}; do
            BUILD_STATUS=$(aws codebuild batch-get-builds \
                --ids "$BUILD_ID" \
                --region "$AWS_REGION" \
                --query 'builds[0].buildStatus' \
                --output text 2>/dev/null)

            case "$BUILD_STATUS" in
                SUCCEEDED)
                    echo -e "\n${GREEN}Agent build SUCCEEDED${NC}"
                    break
                    ;;
                FAILED|FAULT|STOPPED|TIMED_OUT)
                    echo -e "\n${RED}Agent build ${BUILD_STATUS}${NC}"
                    echo -e "${RED}Check CodeBuild logs for details${NC}"
                    break
                    ;;
                *)
                    echo -n "."
                    sleep 15
                    ;;
            esac
        done

        if [ "$BUILD_STATUS" = "IN_PROGRESS" ]; then
            echo -e "\n${YELLOW}Build still in progress after 10 minutes — continuing without waiting${NC}"
        fi
    fi

    # --- Force AgentCore Runtime re-pull ---
    AGENT_STACK_KEY="${APP_NAME}-agent"
    RUNTIME_ARN=$(jq -r --arg key "$AGENT_STACK_KEY" '.[$key].AgentRuntimeArn // ""' cdk-outputs.json 2>/dev/null)

    if [ -z "$RUNTIME_ARN" ] || [ "$RUNTIME_ARN" = "null" ]; then
        echo -e "${YELLOW}AgentCore Runtime ARN not found in cdk-outputs.json — skipping refresh${NC}"
    elif [ "$BUILD_STATUS" = "SUCCEEDED" ]; then
        RUNTIME_ID="${RUNTIME_ARN##*/}"
        echo -e "${YELLOW}Refreshing AgentCore Runtime: ${RUNTIME_ID}${NC}"

        EXISTING=$(aws bedrock-agentcore-control get-agent-runtime \
            --agent-runtime-id "$RUNTIME_ID" \
            --region "$AWS_REGION" \
            --output json 2>/dev/null)

        if [ -n "$EXISTING" ]; then
            ROLE_ARN=$(echo "$EXISTING" | jq -r '.roleArn // ""')
            NETWORK_CFG=$(echo "$EXISTING" | jq -c '.networkConfiguration // {"networkMode":"PUBLIC"}')
            PROTOCOL_CFG=$(echo "$EXISTING" | jq -c '.protocolConfiguration // {"serverProtocol":"HTTP"}')
            ENV_VARS=$(echo "$EXISTING" | jq -c '.environmentVariables // {}')
            CONTAINER_URI=$(echo "$EXISTING" | jq -r '.agentRuntimeArtifact.containerConfiguration.containerUri // ""')

            if [ -n "$CONTAINER_URI" ] && [ "$CONTAINER_URI" != "null" ]; then
                ARTIFACT=$(jq -n --arg uri "$CONTAINER_URI" '{containerConfiguration:{containerUri:$uri}}')

                UPDATE_OUTPUT=$(aws bedrock-agentcore-control update-agent-runtime \
                    --agent-runtime-id "$RUNTIME_ID" \
                    --agent-runtime-artifact "$ARTIFACT" \
                    --role-arn "$ROLE_ARN" \
                    --network-configuration "$NETWORK_CFG" \
                    --protocol-configuration "$PROTOCOL_CFG" \
                    --environment-variables "$ENV_VARS" \
                    --region "$AWS_REGION" \
                    --query 'agentRuntimeVersion' \
                    --output text 2>&1)

                if [ $? -eq 0 ]; then
                    echo -e "${GREEN}AgentCore Runtime updated to version ${UPDATE_OUTPUT} (image re-pull triggered)${NC}"
                else
                    echo -e "${RED}UpdateAgentRuntime failed: ${UPDATE_OUTPUT}${NC}"
                fi
            fi
        else
            echo -e "${RED}Failed to fetch runtime config — skipping refresh${NC}"
        fi
    else
        echo -e "${YELLOW}Skipping runtime refresh (build did not succeed)${NC}"
    fi
fi

# ============================================================================
# STEP 5: Force ECS deployment (if needed)
# ============================================================================
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Step 5: Check ECS deployment${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

if [ "$SKIP_CHATAPP" = true ]; then
    echo -e "${GREEN}Skipping ECS deployment check (--skip-chatapp)${NC}"
elif [ "$INGRESS_MODE" = "furl" ]; then
    echo -e "${GREEN}Skipping ECS deployment check (ingress mode: furl)${NC}"
elif [ "$DRY_RUN" != true ]; then
    # Force ECS to pull the new image (if not already deploying)
    echo ""
    echo -e "${YELLOW}Checking ECS deployment status...${NC}"
    DEPLOYMENT_COUNT=$(aws ecs describe-services \
        --cluster default \
        --services "${APP_NAME}-express" \
        --region "$AWS_REGION" \
        --query 'length(services[0].deployments)' \
        --output text 2>/dev/null || echo "1")
    
    if [ "$DEPLOYMENT_COUNT" = "1" ]; then
        echo -e "${YELLOW}Forcing ECS deployment to pull new image...${NC}"
        aws ecs update-service \
            --cluster default \
            --service "${APP_NAME}-express" \
            --force-new-deployment \
            --region "$AWS_REGION" \
            --query 'service.serviceName' \
            --output text > /dev/null
        echo -e "${GREEN}ECS deployment triggered${NC}"
    else
        echo -e "${GREEN}ECS deployment already in progress (${DEPLOYMENT_COUNT} deployments)${NC}"
    fi
else
    if [ "$INGRESS_MODE" != "furl" ]; then
        echo -e "${CYAN}[DRY RUN] Would check ECS deployment status${NC}"
    fi
fi

# ============================================================================
# STEP 6: Display outputs and next steps
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
    if [ "$SKIP_CHATAPP" = true ]; then
        echo -e "  ${YELLOW}4. ${APP_NAME}-ChatApp (skipped)${NC}"
    elif [ "$INGRESS_MODE" = "ecs" ]; then
        echo "  4. ${APP_NAME}-ChatApp (ECS Express Mode)"
    elif [ "$INGRESS_MODE" = "furl" ]; then
        echo "  4. ${APP_NAME}-ChatApp (Lambda Function URL)"
    else
        echo "  4. ${APP_NAME}-ChatApp (ECS Express Mode + Lambda Function URL)"
    fi
    
    echo ""
    echo -e "${BLUE}Application Endpoints:${NC}"
    
    if [ "$SKIP_CHATAPP" = true ]; then
        echo -e "${YELLOW}ChatApp was skipped — no application endpoints to display${NC}"
        echo ""
        echo -e "${YELLOW}AgentCore Runtime ARN:${NC}"
        AGENT_STACK_KEY="${APP_NAME}-agent"
        RUNTIME_ARN_DISPLAY=$(jq -r --arg key "$AGENT_STACK_KEY" '.[$key].AgentRuntimeArn // "N/A"' cdk-outputs.json 2>/dev/null)
        echo "  $RUNTIME_ARN_DISPLAY"
    else
        # Handle ECS Express Mode URL (for 'ecs' or 'both' modes)
        if [ "$INGRESS_MODE" = "ecs" ] || [ "$INGRESS_MODE" = "both" ]; then
            ECS_SERVICE_NAME="htmx-chatapp-express"
            SERVICE_URL=""
            
            echo -e "${YELLOW}Fetching ECS Express Mode service URL...${NC}"
            
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
            fi
            
            # Display URL or fallback message
            if [ -n "$SERVICE_URL" ]; then
                echo -e "${GREEN}Application URL:${NC} https://$SERVICE_URL"
            else
                echo -e "${YELLOW}ECS Express Mode: URL not yet available (service may still be initializing)${NC}"
                if [ -n "$SERVICE_ARN" ]; then
                    echo -e "${YELLOW}Get URL with:${NC} aws ecs describe-express-gateway-service --service-arn \"$SERVICE_ARN\" --region $AWS_REGION --query 'service.activeConfigurations[0].ingressPaths[0].endpoint' --output text"
                fi
            fi
            echo ""
        fi
        
        # Handle Lambda Function URL (for 'furl' or 'both' modes)
        if [ "$INGRESS_MODE" = "furl" ] || [ "$INGRESS_MODE" = "both" ]; then
            echo -e "${YELLOW}Fetching CloudFront URL...${NC}"
            
            # Get Lambda Function URL from CDK outputs
            STACK_KEY="${APP_NAME}-chatapp"
            LAMBDA_URL=$(jq -r --arg key "$STACK_KEY" '.[$key].LambdaFunctionUrl // ""' cdk-outputs.json 2>/dev/null)
            
            if [ -n "$LAMBDA_URL" ] && [ "$LAMBDA_URL" != "null" ]; then
                echo -e "${GREEN}Application URL:${NC} $LAMBDA_URL"
            else
                echo -e "${YELLOW}  Lambda Function URL: Unable to retrieve from outputs${NC}"
                echo -e "${YELLOW}  Check cdk-outputs.json or AWS Console for the Function URL${NC}"
            fi
            echo ""
        fi
    fi
    
    echo ""
    echo -e "${CYAN}╔════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║           CDK Deployment Complete!                         ║${NC}"
    echo -e "${CYAN}╚════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${YELLOW}Next Steps:${NC}"
    if [ "$SKIP_CHATAPP" = true ]; then
        echo "  1. Deploy the ChatApp later: ./deploy-all.sh --region $AWS_REGION"
        echo "  2. Or invoke the agent directly via AgentCore Runtime API"
    else
        echo "  1. Create a user: cd ../chatapp/scripts && ./create-user.sh <email> <password> --admin"
        echo "  2. Access the application using the URL(s) shown above"
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
