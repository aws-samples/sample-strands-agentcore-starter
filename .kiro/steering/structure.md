# Project Structure

## Root Level

```
├── agent/              # Python backend agent (Strands + AgentCore)
├── chatapp/            # Python/FastAPI frontend (HTMX + vanilla JS)
├── cdk/                # CDK infrastructure (deployment)
├── assets/             # Documentation assets (images)
└── README.md           # Main documentation
```

## Agent Directory (`agent/`)

```
agent/
├── my_agent.py                    # Main agent implementation with memory hooks
├── config.py                      # Configuration dataclass (loads from env)
├── logger.py                      # Structured logging setup
├── guardrails.py                  # Guardrail evaluation logic
├── telemetry.py                   # OpenTelemetry instrumentation
├── requirements.txt               # Python dependencies
├── Dockerfile                     # Container build for AgentCore
├── .env                           # Environment variables (gitignored)
├── .venv/                         # Python virtual environment (gitignored)
└── tools/
    ├── __init__.py                # Tools module init
    ├── knowledge_base.py          # Knowledge Base search tool
    ├── url_fetcher.py             # URL content fetching
    ├── weather.py                 # Weather lookup
    └── web_search.py              # Web search
```

## ChatApp Directory (`chatapp/`)

```
chatapp/
├── app/
│   ├── __init__.py               # App initialization
│   ├── main.py                   # FastAPI application entry point
│   ├── config.py                 # Configuration management
│   ├── auth/
│   │   ├── cognito.py           # Cognito direct auth (InitiateAuth API)
│   │   └── middleware.py        # Auth middleware with token refresh
│   ├── agentcore/
│   │   ├── client.py            # AgentCore Runtime client
│   │   └── memory.py            # Memory API client
│   ├── admin/                    # Admin dashboard module
│   │   ├── repository.py        # Usage analytics DynamoDB queries
│   │   ├── feedback_repository.py # Feedback queries
│   │   ├── guardrail_repository.py # Guardrail violation queries
│   │   ├── runtime_usage_repository.py # AgentCore Runtime usage queries
│   │   └── cost_calculator.py   # Cost calculations
│   ├── storage/                  # Data storage services
│   │   ├── usage.py             # Usage record storage
│   │   ├── feedback.py          # Feedback storage
│   │   ├── guardrail.py         # Guardrail violation storage
│   │   ├── prompt_template.py   # Prompt template storage
│   │   └── app_settings.py      # Application settings storage
│   ├── helpers/                  # Shared utilities
│   │   └── settings.py          # App settings helper (color presets, defaults)
│   ├── routes/
│   │   ├── auth.py              # Auth routes (/auth/login, /auth/logout)
│   │   ├── chat.py              # Chat API routes (/api/chat)
│   │   ├── memory.py            # Memory API routes (/api/memory/*)
│   │   ├── admin.py             # Admin dashboard routes (/admin/*)
│   │   ├── feedback.py          # Feedback API routes
│   │   ├── prompt_templates.py  # Prompt templates routes (/api/templates, /admin/templates)
│   │   └── app_settings.py      # App settings routes (/admin/settings)
│   ├── models/
│   │   ├── feedback.py          # Feedback data models
│   │   ├── guardrail.py         # Guardrail data models
│   │   ├── prompt_template.py   # Prompt template data model
│   │   └── app_settings.py      # App settings data model
│   ├── session/
│   │   └── manager.py           # Session management
│   ├── static/
│   │   ├── js/
│   │   │   ├── chat.js          # SSE streaming, session mgmt, UI logic
│   │   │   └── admin-utils.js   # Admin dashboard utilities
│   │   └── favicon.svg
│   └── templates/
│       ├── base.html            # Base layout with Tailwind CDN, CSS variables
│       ├── chat.html            # Main chat page
│       ├── login.html           # Login form
│       ├── components/
│       │   ├── sidebar.html     # Memory viewer with theme toggle
│       │   └── header.html      # Shared header component (replaces admin_header.html)
│       └── admin/               # Admin dashboard templates
│           ├── dashboard.html   # Main dashboard
│           ├── tokens.html      # Token analytics
│           ├── users.html       # User analytics
│           ├── user_detail.html # User detail view
│           ├── session_detail.html # Session detail view
│           ├── tools.html       # Tool analytics
│           ├── tool_detail.html # Tool detail view
│           ├── feedback.html    # Feedback analytics
│           ├── guardrails.html  # Guardrail violations
│           ├── templates.html   # Prompt templates management
│           └── settings.html    # Application settings (branding, colors)
├── scripts/
│   ├── create-user.sh           # Test user creation
│   └── generate_test_data.py    # Generate test data for admin dashboard
├── sync-env.sh                   # Sync .env from AWS Secrets Manager
├── Dockerfile                    # Container build
├── docker-compose.yml            # Local development
├── requirements.txt              # Python dependencies
├── pyproject.toml               # Python project config
└── README.md                    # ChatApp documentation
```

**Key Files**:
- `app/main.py`: FastAPI app with routes and middleware
- `app/static/js/chat.js`: SSE streaming, message rendering, session management
- `app/templates/components/sidebar.html`: Memory viewer with light/dark theme
- `app/auth/cognito.py`: Direct Cognito authentication (no hosted UI)
- `app/routes/chat.py`: SSE streaming endpoint proxying to AgentCore
- `app/routes/admin.py`: Admin dashboard with usage analytics
- `app/admin/repository.py`: DynamoDB queries for usage data
- `app/admin/runtime_usage_repository.py`: DynamoDB queries for AgentCore Runtime metrics

## Configuration Files

**Gitignored** (contain secrets/generated content):
- `agent/.bedrock_agentcore.yaml` - AgentCore deployment config
- `chatapp/.env` - Environment variables

## CDK Directory (`cdk/`)

```
cdk/
├── bin/
│   └── app.ts                     # CDK app entry point
├── lib/
│   ├── config.ts                  # Shared configuration and export names
│   ├── foundation-stack.ts        # Cognito, DynamoDB, IAM roles, Secrets
│   ├── bedrock-stack.ts           # Guardrail, Knowledge Base, Memory
│   ├── agent-stack.ts             # ECR, CodeBuild, AgentCore Runtime
│   └── chatapp-stack.ts           # ECS Express Mode service
├── test/
│   └── config.test.ts             # Configuration tests
├── deploy-all.sh                  # Full deployment script
├── destroy-all.sh                 # Full cleanup script
├── cdk.json                       # CDK configuration
├── package.json                   # Node.js dependencies
└── tsconfig.json                  # TypeScript configuration
```

**Key Files**:
- `lib/config.ts`: Centralized naming and export configuration
- `lib/foundation-stack.ts`: Auth, storage, IAM, and secrets (no dependencies)
- `lib/bedrock-stack.ts`: AI/ML resources (depends on Foundation for secret updates)
- `lib/agent-stack.ts`: Agent infrastructure (depends on Bedrock)
- `lib/chatapp-stack.ts`: ECS application (depends on Foundation, Agent)

## Naming Conventions

- **Python**: snake_case for files, functions, variables; PascalCase for classes
- **JavaScript**: camelCase for functions/variables, PascalCase for classes
- **TypeScript (CDK)**: camelCase for variables, PascalCase for classes and constructs
- **Templates**: lowercase with hyphens for partials
- **CSS**: Tailwind utility classes, CSS variables for theming
