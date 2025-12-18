# Tech Stack

## Backend Agent (Python)

**Framework**: Strands Agents with Bedrock AgentCore SDK
**Runtime**: Python 3.11+
**Dependencies**: `bedrock-agentcore`, `strands-agents`
**Model**: `us.anthropic.claude-3-7-sonnet-20250219-v1:0`

### Configuration
- Environment variables via `.env` file (gitignored)
- Configuration management through `config.py` dataclass
- Structured logging via `logger.py`

### Common Commands
```bash
# Setup for local development
cd agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Local development
agentcore run --agent my_agent
```

## ChatApp (Python/FastAPI)

**Framework**: FastAPI with Jinja2 templates
**Runtime**: Python 3.11+
**Styling**: Tailwind CSS via CDN
**JavaScript**: Vanilla JS for SSE streaming, marked.js for markdown
**Auth**: AWS Cognito direct API (InitiateAuth, no hosted UI)

### Key Dependencies
- `fastapi` - Web framework
- `uvicorn` - ASGI server
- `jinja2` - Server-side templating
- `boto3` - AWS SDK for Cognito
- `python-jose` - JWT validation
- `httpx` - Async HTTP client for AgentCore

### Common Commands
```bash
# Setup for local development
cd chatapp
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Sync .env from AWS Secrets Manager (after CDK deployment)
./sync-env.sh --region us-east-1

# Or with DEV_MODE (bypasses Cognito auth)
./sync-env.sh --region us-east-1 --dev-mode

# Local development
uvicorn app.main:app --reload --port 8080
```

### Architecture Notes
- HTMX is included but SSE streaming uses vanilla JavaScript
- Reason: Token-by-token streaming with multiple event types (message, tool_use, tool_result, metadata) requires stateful accumulation that's easier in JS than HTMX's fragment replacement model
- Memory viewer uses CSS variables for light/dark theme support

## Infrastructure

**Hosting**: AWS ECS Express Mode (Fargate)
**Auth**: AWS Cognito User Pool (direct InitiateAuth API)
**Container**: Docker with uvicorn
**Agent Backend**: AgentCore Runtime
**Memory**: AgentCore Memory (event + semantic strategies)
**Storage**: DynamoDB (usage analytics, feedback, guardrail violations)
**Guardrails**: Amazon Bedrock Guardrails (content filtering)
**Knowledge Base**: Amazon Bedrock Knowledge Bases (S3 Vectors)
**Streaming**: Server-Sent Events (SSE)
**IaC**: AWS CDK (TypeScript)

### CDK Deployment (Recommended)
```bash
# Setup
cd cdk
npm install

# Deploy all stacks
./deploy-all.sh --region us-east-1

# Deploy with options
./deploy-all.sh --region us-east-1 --profile my-profile

# Destroy all stacks
./destroy-all.sh --region us-east-1
```

### CDK Stack Architecture
- **Foundation**: Cognito, DynamoDB, IAM roles, Secrets Manager
- **Bedrock**: Guardrail, Knowledge Base, AgentCore Memory
- **Agent**: ECR, CodeBuild, AgentCore Runtime, Observability
- **ChatApp**: ECS Express Mode service

Supports multi-region deployment in the same AWS account.

## Code Style

### Python
- Type hints via dataclasses
- Docstrings with Args/Returns/Raises sections
- Structured logging with context
- Configuration from environment variables
- Error handling with detailed logging

### JavaScript (chat.js)
- ES6+ syntax
- JSDoc comments for functions
- camelCase for functions/variables
- Modular organization with section comments

### Templates (Jinja2)
- CSS variables for theming
- Tailwind utility classes
- Inline `<script>` for component-specific JS

## Testing

Manual testing workflow documented in README. UI testing supported via Playwright MCP.
