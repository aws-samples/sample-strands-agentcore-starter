# AgentCore + Strands Agents Starter Application

A full-stack conversational AI starter kit built with Amazon Bedrock AgentCore, Strands Agents SDK, FastAPI, and htmx. This project is used for rapid prototyping of agentic applications. It accelerates proof-of-concept development with built-in telemetry capture, usage analytics, and cost projections.

![Agent Chat UI](/assets/starter.png?raw=true "Agent Chat UI")

## Why This Starter?

Building AI agents is exciting, but understanding their usage, results, and cost profile is critical before scaling. This starter provides:

- **Ready-to-deploy agent** with memory persistence, guardrails, and tool support
- **Built-in usage analytics** tracking every token, tool call, and model invocation
- **User feedback capture** for each response to understand usefulness 
- **Cost projections** to forecast production spending from PoC usage patterns
- **Real-time streaming** for responsive user experience
- **Customizable foundation** to change models, add tools, and extend functionality

## Key Features

- 🤖 **AI-powered conversational agent** with short-term (STM) and long-term memory (LTM)
- ⚡ **Streaming chat** with embedded memory viewer
- 📊 **Admin dashboard** with usage analytics and cost tracking
- 💰 **Cost projections** based on actual usage patterns (token + compute costs)
- 👍 **User feedback** with sentiment ratings and comments
- 🛡️ **Guardrails analytics** with violation tracking and content filtering
- 🔧 **Tool usage details** with per-tool invocation analytics
- 📝 **Prompt templates** for quick access to pre-defined prompts
- 🎨 **Application settings** for branding customization (title, logos, theme colors)
- ☁️ Containerized deployment using **Amazon ECS Express Mode**
- 🧠 AI Agents powered by **Amazon Bedrock AgentCore** using the **Strands Agents SDK**
- 🔐 Secure authentication via **Amazon Cognito**

## Admin Dashboard

The built-in admin dashboard (`/admin`) provides comprehensive usage analytics:

<table width="100%">
<tr>
<td width="50%" valign="top">

**📊 Dashboard Overview** `/admin`
- Total tokens, invocations, estimated costs
- **Total cost breakdown** (token cost + compute cost)
- Top users and tools by usage
- Model breakdown with per-model costs
- **Runtime metrics** (duration, vCPU hours, memory GB-hours)
- Feedback and guardrails summary

</td>
<td width="50%" valign="top">

**🔢 Token Analytics** `/admin/tokens`
- Token usage breakdown by model
- Input vs output distribution
- Cost per model comparison
- Time-range filtering

</td>
</tr>
<tr>
<td width="50%" valign="top">

**👥 User Analytics** `/admin/users`
- Per-user token usage and session counts
- Search users by ID
- Drill-down to individual sessions
- Sorted by total tokens

</td>
<td width="50%" valign="top">

**📋 Session Details** `/admin/sessions/{id}`
- Complete session token usage
- Tools invoked with success/error rates
- Individual invocation records
- Model and latency information
- **Runtime usage** (vCPU hours, runtime cost)

</td>
</tr>
<tr>
<td width="50%" valign="top">

**👍 Feedback Analytics** `/admin/feedback`
- Thumbs up/down on responses
- Optional comments on negative feedback
- Filter by sentiment and date range
- Drill-down to conversation context

</td>
<td width="50%" valign="top">

**🛡️ Guardrails Analytics** `/admin/guardrails`
- Violation tracking by filter type
- Filter strength and confidence levels
- Source breakdown (input vs output)
- Expandable violation details

</td>
</tr>
<tr>
<td width="50%" valign="top">

**🔧 Tool Analytics** `/admin/tools`
- Call counts per tool
- Success/error rates
- Average execution times
- Drill-down to tool detail view

</td>
<td width="50%" valign="top">



</td>
</tr>
<tr>
<td width="50%" valign="top">

**📝 Prompt Templates** `/admin/templates`
- Create reusable prompt templates
- Edit title, description, and prompt text
- Templates appear in chat UI dropdown
- Default "Capabilities" template included

</td>
<td width="50%" valign="top">

**🎨 Application Settings** `/admin/settings`
- Customize app title and subtitle
- Upload custom header and chat logos
- Theme color customization with presets
- Live preview of color changes

</td>
</tr>
</table>

![Usage Dashboard](/assets/usage.png?raw=true "Usage Dashboard")

## Architecture

```
┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐
│     Browser     │      │   ECS Express   │      │   Guardrails    │      │    AgentCore    │
│  Chat + Admin   │◀────▶│    (Fargate)    │◀────▶│   (Bedrock)     │◀────▶│     Runtime     │
│                 │ SSE  │    FastAPI      │      │                 │      │  Strands Agent  │
└─────────────────┘      └─────────────────┘      └─────────────────┘      └─────────────────┘
        │                       │                                           │           │
        │                       ▼                                           │           ▼
        │                ┌─────────────────┐                                │   ┌───────────────┐
        │                │    DynamoDB     │◀───────────────────────────────┤   │    Bedrock    │
        │                │  Usage/Feedback │      Runtime Usage             │   │ Choice of LLM │
        │                │  Runtime Usage  │◀──┐                            │   └───────────────┘
        │                └─────────────────┘   │  │                         │
        │                                      │  │                         │
        ▼                                ┌─────┴──┴──┐                      ▼
┌─────────────────┐                      │  Lambda   │              ┌─────────────────┐
│     Cognito     │                      │ Transform │              │    AgentCore    │
│      Auth       │                      └─────┬─────┘              │     Memory      │──┐
└─────────────────┘                            │                    └─────────────────┘  │
                                         ┌─────┴─────┐                                   │
                                         │ Firehose  │◀─── USAGE_LOGS (Runtime) │
                                         └───────────┘◀──────────────────────────────────┘
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
   ./deploy-all.sh --region <aws-region-id>
   ```

4. **Create a test user** (add `--admin` for admin access):
   ```bash
   cd ../chatapp/scripts
   ./create-user.sh your-email@example.com YourPassword123@ --admin
   ```

5. **Wait for ECS deployment** (4-6 minutes), then access the URL shown in the deployment output.

The deployment creates:
- Cognito User Pool for authentication
- DynamoDB tables for usage analytics, feedback, and guardrails
- Bedrock Guardrail for content filtering
- Bedrock Knowledge Base with S3 Vectors
- AgentCore Memory with LTM strategies
- AgentCore Runtime with the deployed agent
- ECS Express Mode service for the ChatApp

### Deployment Options

```bash
./deploy-all.sh [options]

Options:
  --region <region>    AWS region (default: us-east-1)
  --profile <profile>  AWS CLI profile to use
  --dry-run            Show what would be deployed without deploying
```

### Stack Architecture

The CDK deployment creates 4 consolidated CloudFormation stacks:

| Stack | Description | Key Resources |
|-------|-------------|---------------|
| **Foundation** | Auth, Storage, IAM, Secrets | Cognito, DynamoDB tables, ECS roles, Secrets Manager |
| **Bedrock** | AI/ML Resources | Guardrail, Knowledge Base (S3 Vectors), AgentCore Memory |
| **Agent** | Agent Infrastructure | ECR, CodeBuild, AgentCore Runtime, Observability |
| **ChatApp** | Application | ECR, CodeBuild, S3 source, ECS Express Mode service |

Deployment order: Foundation → Bedrock → Agent → ChatApp

### Multi-Region Deployment

The CDK stacks support deploying to multiple regions in the same AWS account. IAM roles are automatically suffixed with the region name to avoid conflicts.

```bash
# Deploy to us-east-1
./deploy-all.sh --region us-east-1

# Deploy to eu-west-1 (same account)
./deploy-all.sh --region eu-west-1
```

### Useful Commands

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

### Updating Deployments

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

### Local Development

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

### Cleanup

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



## Environment Variables

### Agent
| Variable | Description |
|----------|-------------|
| `BEDROCK_AGENTCORE_MEMORY_ID` | AgentCore Memory ID |
| `AWS_REGION` | AWS region |

### ChatApp
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

## Project Structure

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

## Cost Tracking

The system tracks usage metrics for cost analysis.

_**Note:** Telemetry data is provided for monitoring purposes. Actual billing is calculated based on metered usage data and may differ from telemetry values due to aggregation timing, reconciliation processes, and measurement precision. Refer to your AWS billing statement for authoritative charges._

### Captured Metrics
- **Input/Output Tokens**: Per invocation token counts
- **Model ID**: Which model was used
- **Latency**: Response time in milliseconds
- **Tool Usage**: Call counts, success/error rates per tool
- **Guardrails Violations**: Per filter type, user, and session

### Default Models and Costs
| Model | Input Tokens (per 1M) | Output Tokens (per 1M) |
|-------|---------------|-----------------|
| Amazon Nova 2 Lite | $0.30 | $2.50 |
| Amazon Nova Pro | $0.80 | $3.20 |
| Anthropic Claude Haiku 4.5 | $1.00 | $5.00 |
| Anthropic Claude Sonnet 4.5 | $3.00 | $15.00 |
| Anthropic Claude Opus 4.5 | $5.00 | $25.00 |

### Monthly Projections
The dashboard calculates projected monthly costs using:
```
projected_monthly = (total_cost / days_in_period) * 30
```
Uses 30 calendar days for monthly estimates.

### AgentCore Runtime Usage Costs

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

## Customization

### Adding New Tools
Add tools in `agent/tools/` and register them in `my_agent.py`.

### Changing Models
Update the model ID in `chatapp/app/static/js/chat.js` and add pricing to `chatapp/app/admin/cost_calculator.py`.

### Extending Analytics
The `UsageRepository` class in `chatapp/app/admin/repository.py` provides query methods that can be extended for custom analytics.

## Knowledge Base Integration

The agent includes a Bedrock Knowledge Base for semantic search over curated documents. When configured, the agent prioritizes Knowledge Base results before falling back to web search.

### Setup

The Knowledge Base is automatically created during CDK deployment. It creates:
- S3 bucket for source documents
- S3 Vectors bucket and index for embeddings
- Bedrock Knowledge Base with Titan Embed Text v2
- Data source connecting the KB to the S3 bucket

### Adding Documents to the Knowledge Base

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

### Supported Document Formats

The Knowledge Base supports:
- PDF (.pdf)
- Plain text (.txt)
- Markdown (.md)
- HTML (.html)
- Microsoft Word (.doc, .docx)
- CSV (.csv)

### How the Agent Uses the Knowledge Base

When the agent receives a query:
1. The agent first searches the Knowledge Base for relevant context
2. If relevant results are found (score >= min_score), the agent uses that context
3. If no relevant results are found, the agent falls back to web search or URL fetcher

This prioritization ensures domain-specific knowledge takes precedence over general web content.

## Security

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for more information.

## License

This library is licensed under the MIT-0 License. See the [LICENSE](LICENSE) file.
