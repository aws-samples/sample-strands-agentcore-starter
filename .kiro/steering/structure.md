# Project Structure

## Root Level

```
├── agent/              # Python backend agent (Strands + AgentCore)
├── chatapp/            # Python/FastAPI frontend (HTMX + vanilla JS)
├── assets/             # Documentation assets (images, threat model)
├── README.md           # Main documentation
└── setup.sh            # Master deployment script
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
├── deploy.sh                      # Deployment script
├── .bedrock_agentcore.yaml        # AgentCore deployment config (gitignored)
├── .env                           # Environment variables (gitignored)
├── .venv/                         # Python virtual environment (gitignored)
├── .bedrock_agentcore/            # Build artifacts (gitignored)
├── deploy/
│   └── setup-observability.sh     # CloudWatch/X-Ray setup
└── tools/
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
│   │   └── cost_calculator.py   # Cost calculations
│   ├── storage/                  # Data storage services
│   │   ├── usage.py             # Usage record storage
│   │   ├── feedback.py          # Feedback storage
│   │   └── guardrail.py         # Guardrail violation storage
│   ├── routes/
│   │   ├── auth.py              # Auth routes (/auth/login, /auth/logout)
│   │   ├── chat.py              # Chat API routes (/api/chat)
│   │   ├── memory.py            # Memory API routes (/api/memory/*)
│   │   ├── admin.py             # Admin dashboard routes (/admin/*)
│   │   └── feedback.py          # Feedback API routes
│   ├── models/
│   │   ├── feedback.py          # Feedback data models
│   │   └── guardrail.py         # Guardrail data models
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
│       │   └── admin_header.html # Admin navigation header
│       └── admin/               # Admin dashboard templates
│           ├── dashboard.html   # Main dashboard
│           ├── tokens.html      # Token analytics
│           ├── users.html       # User analytics
│           ├── user_detail.html # User detail view
│           ├── session_detail.html # Session detail view
│           ├── tools.html       # Tool analytics
│           ├── feedback.html    # Feedback analytics
│           └── guardrails.html  # Guardrail violations
├── deploy/
│   ├── setup-cognito.sh         # Cognito user pool setup
│   ├── setup-iam.sh             # IAM roles setup
│   ├── setup-dynamodb.sh        # Usage table setup
│   ├── setup-feedback-dynamodb.sh # Feedback table setup
│   ├── setup-guardrail-dynamodb.sh # Guardrail table setup
│   ├── setup-guardrail.sh       # Bedrock Guardrail setup
│   ├── create-secrets.sh        # Secrets Manager setup
│   └── create-user.sh           # Test user creation
├── Dockerfile                    # Container build
├── docker-compose.yml            # Local development
├── deploy.sh                     # ECS Express Mode deployment
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

## Configuration Files

**Gitignored** (contain secrets/generated content):
- `agent/.bedrock_agentcore.yaml` - AgentCore deployment config
- `chatapp/.env` - Environment variables

## Naming Conventions

- **Python**: snake_case for files, functions, variables; PascalCase for classes
- **JavaScript**: camelCase for functions/variables, PascalCase for classes
- **Templates**: lowercase with hyphens for partials
- **CSS**: Tailwind utility classes, CSS variables for theming
