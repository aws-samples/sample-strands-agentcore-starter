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
- 💰 **Cost projections** based on actual usage patterns
- 👍 **User feedback** with sentiment ratings and comments
- 🛡️ **Guardrails analytics** with violation tracking and content filtering
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
- Top users and tools by usage
- Model breakdown with per-model costs
- Projected monthly cost
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
<td colspan="2" valign="top">

**🔧 Tool Analytics** `/admin/tools` — Call counts per tool, success/error rates, average execution times
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
        │                │    DynamoDB     │                                │   │    Bedrock    │
        │                │  Usage/Feedback │                                │   │ Choice of LLM │
        │                └─────────────────┘                                │   └───────────────┘
        ▼                                                                   ▼
┌─────────────────┐                                                 ┌─────────────────┐
│     Cognito     │                                                 │    AgentCore    │
│      Auth       │                                                 │     Memory      │
└─────────────────┘                                                 └─────────────────┘
```

## Prerequisites

| Tool | Minimum Version | Purpose |
|------|----------------|---------|
| **Python** | 3.11+ | Backend development |
| **AWS CLI** | 2.x | AWS resource management |
| **Docker** | 20.x | Container builds |

### AWS Requirements

- AWS Account with a Default VPC
- IAM permissions with access to Bedrock, Bedrock AgentCore, ECS, Cognito, ECR, DynamoDB, Secrets Manager

## Quick Start

1) Clone the repository

```bash
git clone https://github.com/aws-samples/sample-strands-agentcore-starter
cd sample-strands-agentcore-starter
```
2) Install agent dependencies

```bash
cd agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd ..
```

3) Run the setup.sh to deploy agent and chat app resources. Answer the following when prompted:

    - _Path or Press Enter to use detected dependency file: requirements.txt_ 
      - **Press Enter**
    - _Execution role ARN/name (or press Enter to auto-create):_
      - **Press Enter**
    - _Configure OAuth authorizer instead? (yes/no) [no]:_
      - **Press Enter**
    - _Configure request header allowlist? (yes/no) [no]:_
      - **Press Enter**
    - _MemoryManager initialization_
      - **Your choice:** Enter the number for the **chat_app_mem** resource. This should be **1** unless you already had memory resources.

```bash
./setup.sh --region <aws-region-id>
```
```bash
./setup.sh [options]

Options:
  --region <region>         AWS region (default: us-east-1)
  --skip-agent              Skip agent deployment (use existing)
  --skip-chatapp            Skip chatapp deployment
```

4) Create a test user _(add --admin for admin access)_

```bash
cd chatapp/deploy
./create-user.sh your-email@example.com YourPassword123@ --admin
```

The setup script will:
- Deploy the agent to AgentCore Runtime (creates memory with LTM strategies)
- Create Cognito User Pool and app client
- Set up IAM roles for ECS
- Store secrets in AWS Secrets Manager
- Deploy the ChatApp to ECS Express Mode


5) Wait for ECS Service Deployment to complete. Monitor the deployment process on the [AWS Console](https://console.aws.amazon.com/ecs/v2/clusters/default).

    > ⚠️ This will take 4-6 minutes.

## Step-by-Step Setup

If you prefer to deploy components individually:

### 1. Deploy the Agent

```bash
cd agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Deploy agent with Short-term and Long-term Memory
./deploy.sh
```

This creates:
- AgentCore Memory with semantic, summary, and user preference strategies
- AgentCore Runtime with the deployed agent
- Configuration saved to `.bedrock_agentcore.yaml`

### 2. Deploy the ChatApp

```bash
cd chatapp

# Set up Cognito (creates user pool and client)
cd deploy
./setup-cognito.sh

# Create a test user (add --admin for admin access)
./create-user.sh your-email@example.com YourPassword123@ --admin

# Set up IAM roles
./setup-iam.sh

# Create secrets in AWS Secrets Manager
./create-secrets.sh
cd ..

# Deploy to ECS Express Mode
./deploy.sh
```

### 3. Local Development

For local development without deploying to ECS:

```bash
cd chatapp
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Copy example env and fill in values from agent deployment
cp .env.example .env
# Edit .env with values from agent/.bedrock_agentcore.yaml

# Run locally
uvicorn app.main:app --reload --port 8080
```

- Chat: http://localhost:8080
- Admin: http://localhost:8080/admin

## Updating Deployments

### Update Agent

```bash
cd agent
./deploy.sh  # Redeploys with latest code
```

### Update ChatApp

```bash
cd chatapp
./deploy.sh --update  # Updates existing ECS service
```

### Delete ChatApp Deployment

```bash
cd chatapp
./deploy.sh --delete  # Removes ECS Express Mode service
```

## Cleanup

To remove all AWS resources created by this starter, use the cleanup script:

```bash
./cleanup.sh --region <aws-region-id>
```

This deletes:
- ECS Express Mode service and ECR repository
- Secrets Manager secret
- IAM roles (execution, task, infrastructure)
- DynamoDB tables (usage, feedback, guardrails)
- Bedrock Guardrail
- Cognito User Pool
- CloudWatch log groups and alarms
- AgentCore agent runtime and memory
- Local config files (optional)

### Cleanup Options

```bash
./cleanup.sh [options]

Options:
  --region <region>  AWS region (default: us-east-1)
  --skip-agent       Skip agent/memory deletion
  --skip-chatapp     Skip chatapp resources deletion
  --dry-run          Show what would be deleted without deleting
```

### Dry Run

Preview what will be deleted before running:

```bash
./cleanup.sh --region us-east-1 --dry-run
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
| `APP_URL` | No | Application URL for callbacks |
| `AWS_REGION` | Yes | AWS region |

## Project Structure

```
sample-strands-agentcore-starter/
├── agent/                        # AgentCore agent
│   ├── my_agent.py               # Agent definition
│   ├── tools/                    # Agent tools
│   ├── deploy.sh                 # Deployment script
│   └── requirements.txt
│
├── chatapp/                      # Chat and Admin UI
│   ├── app/
│   │   ├── main.py               # FastAPI application
│   │   ├── admin/                # Usage analytics module
│   │   ├── auth/                 # Cognito authentication
│   │   ├── agentcore/            # AgentCore client
│   │   ├── storage/              # Data storage services
│   │   ├── routes/               # Chat and Admin API routes
│   │   ├── models/               # Data models
│   │   └── templates/            # UI templates
│   ├── deploy/                   # Deployment resources
│   ├── deploy.sh                 # Deployment script
│   └── requirements.txt
│
└── README.md
```

## Cost Tracking

The system tracks usage metrics for cost analysis:

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
projected_monthly = (total_cost / days_in_period) * 20
```
Uses 20 business days for realistic production estimates.

## Customization

### Adding New Tools
Add tools in `agent/tools/` and register them in `my_agent.py`.

### Changing Models
Update the model ID in `chatapp/app/static/js/chat.js` and add pricing to `chatapp/app/admin/cost_calculator.py`.

### Extending Analytics
The `UsageRepository` class in `chatapp/app/admin/repository.py` provides query methods that can be extended for custom analytics.

## Security

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for more information.

## License

This library is licensed under the MIT-0 License. See the [LICENSE](LICENSE) file.
