# AgentCore + Strands Agents Starter Application

A full-stack conversational AI starter kit built with Amazon Bedrock AgentCore, Strands Agents SDK, FastAPI, and htmx. This project is used for rapid prototyping of agentic applications. It accelerates proof-of-concept development with built-in telemetry capture, usage analytics, and cost projections.

![Agent Chat UI](/assets/starter.png?raw=true "Agent Chat UI")

## Why This Starter?

Skip weeks of infrastructure setup and go straight to validating your agentic AI use case. This starter provides everything you need to move from idea to production-ready POC:

- **Production-grade infrastructure in minutes** — Deploy a complete agentic AI stack (auth, memory, guardrails, knowledge base, analytics) with a single CDK command, eliminating weeks of boilerplate development
- **Built-in cost intelligence** — Track token usage, runtime costs, and tool invocations with projections to forecast production spending before you scale
- **Flexible deployment options** — Choose between always-on ECS (\~$46/mo) or serverless [Lambda Web Adapter](https://github.com/awslabs/aws-lambda-web-adapter) (\~$12/mo) based on your traffic patterns and budget
- **Extensible agent framework** — Add custom tools, swap models, integrate your own knowledge base, and customize the UI without rebuilding core infrastructure

## Key Features

**Chat Experience**
- 🤖 **AI-powered conversational agent** with short-term (STM) and long-term memory (LTM)
- ⚡ **Real-time streaming** with token-by-token SSE responses and embedded memory viewer
- 📝 **Prompt templates** for quick access to pre-defined prompts
- 🎨 **Customizable branding** - title, logos, and theme colors

**POC Analytics & Insights**
- 📊 **Admin dashboard** with usage analytics and cost tracking
- 💰 **Cost projections** based on actual usage patterns (token + runtime costs)
- 👍 **User feedback capture** with sentiment ratings and comments
- 🛡️ **Guardrails analytics** with violation tracking and content filtering
- 🔧 **Tool usage analytics** with per-tool invocation metrics and success rates

**Agent Capabilities**
- 🧠 **Amazon Bedrock AgentCore** with Strands Agents SDK
- 📚 **Knowledge Base integration** for semantic search over your documents (S3 Vectors)
- 🛠️ **Pre-built tools** - web search, URL fetcher, weather, calculator, current time

**Infrastructure**
- ☁️ **Flexible deployment options** - ECS Express Mode or CloudFront + Lambda Web Adapter
- 💸 **Cost-optimized** - Serverless options with pay-per-use pricing
- 🔐 **Cognito authentication** with secure token management
- 📡 **OpenTelemetry and Bedrock AgentCore Observability** with logs, traces, and metrics

## Admin Dashboard

The built-in admin dashboard (`/admin`) provides comprehensive usage analytics:

<table width="100%">
<tr>
<td width="50%" valign="top">

**📊 Dashboard Overview** `/admin`
- Total cost breakdown (token cost + runtime cost)
- Top users and tools by usage
- Model breakdown with per-model costs

</td>
<td width="50%" valign="top">

**🔢 Token Usage** `/admin/tokens`
- Token usage breakdown by model
- Input vs output distribution
- Monthly projections

</td>
</tr>
<tr>
<td width="50%" valign="top">

**💬 Chat History** `/admin/history`
- Browse all chat sessions with time filtering
- Token cost vs runtime cost breakdown

</td>
<td width="50%" valign="top">

**📋 Session Details** `/admin/sessions/{id}`
- Complete session token and runtime usage
- Tools invoked with success/error rates

</td>
</tr>
<tr>
<td width="50%" valign="top">

**👍 Feedback Analytics** `/admin/feedback`
- User sentiment and comments capture
- Review related conversation context

</td>
<td width="50%" valign="top">

**👥 User Analytics** `/admin/users`
- Per-user token usage and session counts

</td>
</tr>
<tr>
<td width="50%" valign="top">

**🛡️ Guardrails Analytics** `/admin/guardrails`
- Violation tracking by filter type
- Filter strength and confidence levels

</td>
<td width="50%" valign="top">

**🔧 Tool Analytics** `/admin/tools`
- Call counts per tool with success/error rates
- Average execution times

</td>
</tr>
<tr>
<td width="50%" valign="top">

**📝 Prompt Templates** `/admin/templates`
- Create reusable prompt templates that appear in chat UI dropdown
- Edit title, description, and prompt text

</td>
<td width="50%" valign="top">

**🎨 Application Settings** `/admin/settings`
- Customize app title, subtitle, and welcome message
- Set app theme including color and custom logos

</td>
</tr>
</table>

![Usage Dashboard](/assets/usage.png?raw=true "Usage Dashboard")

## Architecture

The application supports two ingress modes for the FastAPI application: ECS Express Gateway (serverless container) or CloudFront + Lambda Web Adapter (serverless function with edge distribution).

```
┌─────────────────┐      ┌─────────────────────────────────┐      ┌─────────────────┐
│                 │      │     ECS Express (Fargate)       │      │                 │
│     Browser     │      │            - or -               │      │   Guardrails    │
│  Chat + Admin   │◀────▶│  CloudFront + Lambda Web Adapter│◀────▶│   (Bedrock)     │
│                 │ SSE  │                                 │      │                 │
└─────────────────┘      │           FastAPI               │      └─────────────────┘
        │                └─────────────────────────────────┘               │
        │                               │                                  │
        │                               ▼                                  ▼
        │                        ┌─────────────────┐              ┌─────────────────┐
        │                        │    DynamoDB     │              │    AgentCore    │
        │                        │  Usage/Feedback │              │     Runtime     │
        │                        │  Runtime Usage  │              │  Strands Agent  │
        │                        └─────────────────┘              └─────────────────┘
        │                               ▲                          │      │      │
        │                               │                          │      │      │
        │                        ┌──────┴──────┐                   │      │      │
        │                        │   Lambda    │                   │      │      │
        │                        │  Transform  │                   ▼      │      ▼
        │                        └─────────────┘           ┌───────────┐  │  ┌───────────┐
        │                               ▲                  │  Bedrock  │  │  │ AgentCore │
        │                        ┌──────┴──────┐           │   LLM     │  │  │  Memory   │
        │                        │  Firehose   │           └───────────┘  │  └───────────┘
        ▼                        └─────────────┘                          │
┌─────────────────┐                     ▲                                 │
│     Cognito     │                     │                                 │
│      Auth       │                     └─────────────────────────────────┘
└─────────────────┘                              USAGE_LOGS
```

## Prerequisites

| Tool | Minimum Version | Purpose |
|------|----------------|---------|
| **Node.js** | 18.x+ | CDK runtime |
| **AWS CDK CLI** | 2.x | Infrastructure deployment |
| **AWS CLI** | 2.x | AWS resource management |

Install CDK CLI globally:
```bash
npm install -g aws-cdk
```

Note: Docker is not required locally - all container builds are handled by AWS CodeBuild.

### AWS Requirements

- AWS Account with a Default VPC
- IAM permissions with access to Bedrock, Bedrock AgentCore, ECS, Cognito, ECR, DynamoDB, Secrets Manager

## Quick Start

1. **Clone the repository**:
   ```bash
   git clone https://github.com/aws-samples/sample-strands-agentcore-starter
   cd sample-strands-agentcore-starter
   ```

2. **Install CDK dependencies**:
   ```bash
   cd cdk
   npm install
   ```

3. **Deploy all stacks**:
   ```bash
   ./deploy-all.sh --region <aws-region-id> --profile <your-profile> --ingress furl
   ```

4. **Create a test user** (add `--admin` for admin access):
   ```bash
   cd ../chatapp/scripts
   ./create-user.sh your-email@example.com YourPassword123@ --admin
   ```

5. **Wait for deployment** (5-10 minutes for ECS, 3-4 minutes for Lambda), then access the URL shown in the deployment output.

The deployment creates:
- Cognito User Pool for authentication
- DynamoDB tables for usage analytics, feedback, and guardrails
- Bedrock Guardrail for content filtering
- Bedrock Knowledge Base with S3 Vectors
- AgentCore Memory with LTM strategies
- AgentCore Runtime with the deployed agent
- ChatApp ingress (ECS Express Mode and/or CloudFront + Lambda Web Adapter based on --ingress flag)

## Deployment Options

The application supports three ingress modes for different use cases and cost profiles:

### Ingress Modes

| Mode | Description | Monthly Cost | Use Case |
|------|-------------|--------------|----------|
| **ecs** | ECS Express Gateway - Always-on container service | ~$46 | Production workloads, consistent traffic, no cold starts |
| **furl** (default) | CloudFront + Lambda Web Adapter - Serverless pay-per-use with edge distribution | ~$12 | Development, PoC, sporadic usage, cost optimization |
| **both** | Deploy both simultaneously | ~$58 | A/B testing, migration, redundancy |

### Deployment Command

```bash
./deploy-all.sh [options]

Options:
  --region <region>    AWS region (default: us-east-1)
  --profile <profile>  AWS CLI profile to use
  --ingress <mode>     Ingress mode: ecs, furl, or both (default: ecs)
  --dry-run            Show what would be deployed without deploying
```

### Examples

```bash
# Deploy with ECS Express Gateway
./deploy-all.sh --region us-east-1 --ingress ecs

# Deploy with CloudFront + Lambda Web Adapter (default)
./deploy-all.sh --region us-east-1 --ingress furl

# Deploy both ECS and Lambda simultaneously
./deploy-all.sh --region us-east-1 --ingress both
```

### Cost Breakdown

**ECS Mode** (~$44/month):
- ECS Fargate: ~$18/mo (0.5 vCPU, 1GB RAM, always-on)
- Application Load Balancer: ~$16.20/mo (managed by Express Gateway)
- IPv4 addresses: ~$10.95/mo (3 ALB IPs across AZs + 1 task ENI)
- Data transfer: ~$0.50/mo

**Lambda Web Adapter Mode** (~$12/month typical):
- CloudFront distribution: ~$1.00/mo (1M requests)
- Lambda compute: ~$10/mo (10,000 requests/day @ 1GB/2s avg)
- Lambda@Edge: ~$0.50/mo (payload hash computation)
- Data transfer: ~$0.60/mo
- No charges for: IPv4, ALB, or idle time
- Cold starts: First request after idle may take 3-5 seconds

**Both Mode**: Combines costs of both deployment modes

## Stack Architecture

The CDK deployment creates 4 consolidated CloudFormation stacks:

| Stack | Description | Key Resources |
|-------|-------------|---------------|
| **Foundation** | Auth, Storage, IAM, Secrets | Cognito, DynamoDB tables, ECS roles, Secrets Manager |
| **Bedrock** | AI/ML Resources | Guardrail, Knowledge Base (S3 Vectors), AgentCore Memory |
| **Agent** | Agent Infrastructure | ECR, CodeBuild, AgentCore Runtime, Observability |
| **ChatApp** | Application | ECR, CodeBuild, S3 source, ECS Express Mode and/or CloudFront + Lambda Web Adapter |

Deployment order: Foundation → Bedrock → Agent → ChatApp

## Multi-Region Deployment

The CDK stacks support deploying to multiple regions in the same AWS account. IAM roles are automatically suffixed with the region name to avoid conflicts.

```bash
# Deploy to us-east-1
./deploy-all.sh --region us-east-1

# Deploy to eu-west-1 (same account)
./deploy-all.sh --region eu-west-1
```

## Useful Commands

```bash
# List all stacks
npx cdk list

# Deploy a specific stack
npx cdk deploy htmx-chatapp-Foundation

# View stack differences before deploying
npx cdk diff

# Synthesize CloudFormation templates
npx cdk synth

# View stack outputs
cat cdk-outputs.json
```

## Updating Deployments

To update the application after code changes:

```bash
cd cdk
./deploy-all.sh --region <aws-region-id>
```

To update only the ChatApp (faster for UI changes):

```bash
cd cdk
npx cdk deploy htmx-chatapp-ChatApp --require-approval never
```

## Local Development

For local development, you need to sync environment variables from your deployed CDK stacks.

**Prerequisites**: CDK stacks must be deployed first (`./deploy-all.sh`).

```bash
cd chatapp
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Sync .env from AWS Secrets Manager (auto-populates all values)
./sync-env.sh --region <aws-region-id>

# Or with DEV_MODE (bypasses Cognito authentication)
./sync-env.sh --region <aws-region-id> --dev-mode

# Run locally
uvicorn app.main:app --reload --port 8080
```

- Chat: http://localhost:8080
- Admin: http://localhost:8080/admin

**DEV_MODE**: When enabled, Cognito authentication is bypassed and requests use a default `dev-user-001` user ID. This is useful for rapid iteration without needing to log in. Set `DEV_USER_ID` in `.env` to customize the user ID.

**Manual .env setup**: If you prefer manual configuration, copy `.env.example` to `.env` and fill in values. The secret `htmx-chatapp/config` in AWS Secrets Manager contains all required values.

## Cleanup

To destroy all CDK-managed resources:

```bash
cd cdk
./destroy-all.sh --region <aws-region-id>
```

Options:
```bash
./destroy-all.sh [options]

Options:
  --region <region>    AWS region (default: us-east-1)
  --profile <profile>  AWS CLI profile to use
  --yes                Auto-confirm all prompts (DANGEROUS)
  --dry-run            Show what would be destroyed without destroying
```



# Environment Variables

## Agent
| Variable | Description |
|----------|-------------|
| `BEDROCK_AGENTCORE_MEMORY_ID` | AgentCore Memory ID |
| `AWS_REGION` | AWS region |

## ChatApp
| Variable | Required | Description |
|----------|----------|-------------|
| `COGNITO_USER_POOL_ID` | Yes | Cognito User Pool ID |
| `COGNITO_CLIENT_ID` | Yes | Cognito App Client ID |
| `COGNITO_CLIENT_SECRET` | Yes | Cognito App Client Secret |
| `AGENTCORE_RUNTIME_ARN` | Yes | AgentCore Runtime ARN |
| `MEMORY_ID` | Yes | AgentCore Memory ID |
| `USAGE_TABLE_NAME` | Yes | DynamoDB table for usage records |
| `FEEDBACK_TABLE_NAME` | Yes | DynamoDB table for feedback records |
| `GUARDRAIL_TABLE_NAME` | Yes | DynamoDB table for guardrail violations |
| `GUARDRAIL_ID` | No | Bedrock Guardrail ID for content filtering |
| `GUARDRAIL_VERSION` | No | Bedrock Guardrail version (default: DRAFT) |
| `GUARDRAIL_ENABLED` | No | Enable/disable guardrail evaluation (default: true) |
| `PROMPT_TEMPLATES_TABLE_NAME` | Yes | DynamoDB table for prompt templates |
| `APP_SETTINGS_TABLE_NAME` | Yes | DynamoDB table for application settings |
| `RUNTIME_USAGE_TABLE_NAME` | Yes | DynamoDB table for AgentCore runtime usage |
| `APP_URL` | No | Application URL for callbacks |
| `AWS_REGION` | Yes | AWS region |

# Project Structure

```
sample-strands-agentcore-starter/
├── agent/                        # AgentCore agent
│   ├── my_agent.py               # Agent definition
│   ├── tools/                    # Agent tools
│   └── requirements.txt
│
├── chatapp/                      # Chat and Admin UI
│   ├── app/
│   │   ├── main.py               # FastAPI application
│   │   ├── admin/                # Usage analytics module
│   │   ├── auth/                 # Cognito authentication
│   │   ├── agentcore/            # AgentCore client
│   │   ├── helpers/              # Shared utilities (settings)
│   │   ├── storage/              # Data storage services
│   │   ├── routes/               # Chat and Admin API routes
│   │   ├── models/               # Data models
│   │   └── templates/            # UI templates
│   ├── scripts/
│   │   ├── create-user.sh        # User creation script
│   │   └── generate_test_data.py # Test data generator for admin dashboard
│   └── requirements.txt
│
├── cdk/                          # CDK Infrastructure
│   ├── lib/
│   │   ├── foundation-stack.ts   # Auth, Storage, IAM, Secrets
│   │   ├── bedrock-stack.ts      # Guardrail, KB, Memory
│   │   ├── agent-stack.ts        # ECR, CodeBuild, Runtime
│   │   └── chatapp-stack.ts      # ECS Express Mode
│   ├── deploy-all.sh             # Full deployment script
│   └── destroy-all.sh            # Full cleanup script
│
└── README.md
```

# Cost Tracking

The system tracks usage metrics for cost analysis.

_**Note:** Telemetry data is provided for monitoring purposes. Actual billing is calculated based on metered usage data and may differ from telemetry values due to aggregation timing, reconciliation processes, and measurement precision. Refer to your AWS billing statement for authoritative charges._

## Captured Metrics
- **Input/Output Tokens**: Per invocation token counts
- **Model ID**: Which model was used
- **Latency**: Response time in milliseconds
- **Tool Usage**: Call counts, success/error rates per tool
- **Guardrails Violations**: Per filter type, user, and session

## Default Models and Costs
| Model | Input Tokens (per 1M) | Output Tokens (per 1M) |
|-------|---------------|-----------------|
| Amazon Nova 2 Lite | $0.30 | $2.50 |
| Amazon Nova Pro | $0.80 | $3.20 |
| Anthropic Claude Haiku 4.5 | $1.00 | $5.00 |
| Anthropic Claude Sonnet 4.5 | $3.00 | $15.00 |
| Anthropic Claude Opus 4.5 | $5.00 | $25.00 |

## Monthly Projections
The dashboard calculates projected monthly costs using:
```
projected_monthly = (total_cost / days_in_period) * 30
```
Uses 30 calendar days for monthly estimates.

## AgentCore Runtime Usage Costs

In addition to token costs, the system tracks AgentCore Runtime usage:

| Metric | Rate |
|--------|------|
| vCPU Hours | $0.0895/hour |
| Memory GB-Hours | $0.00945/GB-hour |

**How it works:**
1. AgentCore Runtime emits USAGE_LOGS with metrics per operation
2. Logs are streamed via Kinesis Data Firehose to Lambda transform functions
3. Lambda parses the logs and writes usage records to DynamoDB (keyed by session_id)
4. The admin dashboard aggregates runtime costs alongside token costs

**Runtime metrics captured per invocation:**
- `time_elapsed_seconds` - Runtime duration
- `vcpu_hours` - vCPU time consumed
- `memory_gb_hours` - Memory time consumed
- `session_id` - Links runtime usage to chat session

The dashboard shows:
- **Total Cost** = Token Cost + Runtime Cost
- Per-session breakdown of token vs runtime costs
- Runtime metrics (duration, vCPU hours, memory GB-hours)

# Customization

## Adding New Tools
Add tools in `agent/tools/` and register them in `my_agent.py`.

## Changing Models
Update the model ID in `chatapp/app/static/js/chat.js` and add pricing to `chatapp/app/admin/cost_calculator.py`.

## Extending Analytics
The `UsageRepository` class in `chatapp/app/admin/repository.py` provides query methods that can be extended for custom analytics.

# Knowledge Base Integration

The agent includes a Bedrock Knowledge Base for semantic search over curated documents. When configured, the agent prioritizes Knowledge Base results before falling back to web search.

## Setup

The Knowledge Base is automatically created during CDK deployment. It creates:
- S3 bucket for source documents
- S3 Vectors bucket and index for embeddings
- Bedrock Knowledge Base with Titan Embed Text v2
- Data source connecting the KB to the S3 bucket

## Adding Documents to the Knowledge Base

1. **Upload documents to S3**:
   ```bash
   # Get the source bucket name from CDK outputs
   SOURCE_BUCKET=$(cat cdk/cdk-outputs.json | jq -r '."htmx-chatapp-Bedrock".SourceBucketName')
   
   # Upload documents to the documents/ prefix
   aws s3 cp my-document.pdf s3://${SOURCE_BUCKET}/documents/
   aws s3 cp my-folder/ s3://${SOURCE_BUCKET}/documents/ --recursive
   ```

2. **Sync/Ingest documents**:
   ```bash
   # Get the Knowledge Base ID and Data Source ID from CDK outputs
   KB_ID=$(cat cdk/cdk-outputs.json | jq -r '."htmx-chatapp-Bedrock".KnowledgeBaseId')
   DS_ID=$(aws bedrock-agent list-data-sources --knowledge-base-id $KB_ID --query "dataSourceSummaries[0].dataSourceId" --output text)
   
   # Start ingestion job
   aws bedrock-agent start-ingestion-job \
     --knowledge-base-id $KB_ID \
     --data-source-id $DS_ID
   
   # Check ingestion status
   aws bedrock-agent list-ingestion-jobs \
     --knowledge-base-id $KB_ID \
     --data-source-id $DS_ID
   ```

## Supported Document Formats

The Knowledge Base supports:
- PDF (.pdf)
- Plain text (.txt)
- Markdown (.md)
- HTML (.html)
- Microsoft Word (.doc, .docx)
- CSV (.csv)

## How the Agent Uses the Knowledge Base

When the agent receives a query:
1. The agent first searches the Knowledge Base for relevant context
2. If relevant results are found (score >= min_score), the agent uses that context
3. If no relevant results are found, the agent falls back to web search or URL fetcher

This prioritization ensures domain-specific knowledge takes precedence over general web content.

# Security

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for more information.

# License

This library is licensed under the MIT-0 License. See the [LICENSE](LICENSE) file.
