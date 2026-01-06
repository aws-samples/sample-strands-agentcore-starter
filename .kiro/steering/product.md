# Product Overview

AgentCore Chat Application - A full-stack conversational AI starter kit with built-in usage analytics and cost projection for proof-of-concept development.

## Core Features

- AI-powered conversational agent with memory persistence using Amazon Bedrock AgentCore
- Real-time SSE streaming for token-by-token response display
- Secure authentication via AWS Cognito with direct API authentication
- Modern chat interface with markdown support and syntax highlighting
- Session management with conversation history
- Memory viewer with event and semantic memory tabs (Events, Facts, Summaries, Preferences)
- Light/dark theme toggle for memory sidebar
- Admin dashboard with usage analytics and cost tracking (token + runtime costs)
- User feedback capture (thumbs up/down with comments)
- Guardrails analytics with violation tracking
- Prompt templates for quick access to pre-defined prompts (admin-managed, stored in DynamoDB)
- Application settings for branding customization (title, subtitle, logos, theme colors)
- Tool detail views with per-tool invocation analytics
- Knowledge Base integration for semantic search over curated documents
- Containerized deployment on AWS ECS Express Mode or CloudFront + Lambda Web Adapter

## Architecture

**Frontend**: Python FastAPI with Jinja2 templates, Tailwind CSS (CDN), vanilla JavaScript for SSE streaming
**Backend**: FastAPI serving HTML templates and API endpoints
**Agent Backend**: Python agent using Strands framework deployed to AgentCore Runtime
**Integration**: FastAPI routes invoke AgentCore Runtime (preserves streaming)
**Memory**: AgentCore Memory provides event and semantic memory for conversation persistence
**Storage**: DynamoDB for usage records, feedback, guardrail violations, prompt templates, app settings, and runtime usage
**Runtime Tracking**: Firehose pipeline streaming AgentCore Runtime usage logs to DynamoDB for vCPU/memory cost tracking
**Streaming**: Server-Sent Events (SSE) for real-time token-by-token response display

## Key Technologies

- Amazon Bedrock AgentCore (agent runtime and memory)
- Amazon Bedrock Knowledge Bases (semantic search with S3 Vectors)
- Amazon Bedrock Guardrails (content filtering)
- Amazon DynamoDB (usage analytics, feedback, guardrail storage, runtime usage)
- Amazon Kinesis Data Firehose (runtime usage log streaming)
- FastAPI (Python web framework)
- Jinja2 (server-side templating)
- HTMX (included but SSE streaming uses vanilla JS for complex state management)
- AWS ECS Express Mode (container hosting)
- Amazon CloudFront + Lambda Web Adapter (serverless hosting with edge distribution)
- AWS Cognito (authentication via direct InitiateAuth API)
- Strands Agents framework (Python)
- Tailwind CSS via CDN (styling)
- marked.js (markdown rendering)
- Server-Sent Events (SSE) for streaming
- Claude 3.7 Sonnet (LLM model)
