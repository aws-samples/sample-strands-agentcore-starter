# About the AgentCore Chat Application

> **Document class:** REFERENCE · **Topic:** Application overview, architecture, and features
>
> This article describes the AgentCore Chat Application starter kit. It is seeded into the
> Knowledge Base by default so the agent has something to retrieve and the Knowledge Base
> Explorer has a document to display out of the box.

## 1. What this application is

The AgentCore Chat Application is a full-stack conversational AI starter kit. It pairs a
Python agent (built on the Strands Agents framework and deployed to Amazon Bedrock
AgentCore Runtime) with a FastAPI web front end. The kit is designed for proof-of-concept
development: it ships with authentication, conversation memory, usage analytics, cost
projection, and a Knowledge Base out of the box.

Core capabilities:

- Conversational agent with persistent memory using Amazon Bedrock AgentCore.
- Real-time, token-by-token streaming of responses over Server-Sent Events (SSE).
- Secure sign-in through Amazon Cognito using the direct InitiateAuth API (no hosted UI).
- A modern chat interface with markdown rendering and syntax highlighting.
- Session management with conversation history.
- A memory viewer showing events, facts, summaries, and preferences.
- An admin dashboard with usage analytics and cost tracking (token plus runtime cost).
- User feedback capture (thumbs up/down with comments).
- Guardrails analytics with violation tracking.
- Prompt templates for quick access to pre-defined prompts.
- Knowledge Base integration for semantic search over curated documents.
- A Knowledge Base Explorer for browsing, searching, and uploading source documents.

## 2. Architecture

The system is composed of four parts:

1. **Agent backend** — a Python agent using the Strands Agents framework, deployed to the
   Amazon Bedrock AgentCore Runtime. It exposes tools for web search, URL fetching,
   weather lookup, and Knowledge Base search.
2. **Chat application** — a FastAPI service that renders Jinja2 templates, proxies chat
   requests to the AgentCore Runtime, and serves the admin dashboard. Styling uses
   Tailwind CSS via CDN; streaming uses vanilla JavaScript.
3. **Memory and storage** — AgentCore Memory provides event and semantic memory for
   conversation persistence. DynamoDB stores usage records, feedback, guardrail
   violations, prompt templates, application settings, and runtime usage.
4. **Knowledge Base** — an Amazon Bedrock Knowledge Base backed by S3 Vectors. Source
   documents live in an S3 bucket under the `documents/` prefix and are embedded with the
   Amazon Titan Text Embeddings V2 model.

## 3. How the Knowledge Base works

Source documents are stored in a dedicated S3 bucket under the `documents/` prefix. Amazon
Bedrock ingests those documents, splits them into chunks, embeds each chunk with Titan
Text Embeddings V2, and stores the vectors in an S3 Vectors index. At query time the agent
calls the `Retrieve` API, which performs a vector similarity search and returns the most
relevant passages.

When you add or change documents, Bedrock must run an *ingestion job* to pick up the
changes. The Knowledge Base Explorer triggers an ingestion job automatically after an
upload, so newly uploaded files become retrievable within a few minutes.

## 4. The Knowledge Base Explorer

The Knowledge Base Explorer is an admin page that lets you:

- **Browse** every source document in the Knowledge Base as a flat list.
- **Search** the Knowledge Base with the same semantic retrieval the agent uses, so you can
  validate what the agent will see for a given question.
- **Read** a document's contents directly in the browser when the file is text-based
  (for example Markdown, plain text, JSON, CSV, or YAML).
- **Upload** new documents into the Knowledge Base. Uploaded files are written to the
  `documents/uploads/` prefix and an ingestion job is started automatically.

Use the Explorer to confirm the data the agent relies on and to seed new domain knowledge
for testing.

## 5. Deployment

The application is deployed with the AWS CDK (TypeScript). Four stacks are provisioned:

- **Foundation** — Cognito, DynamoDB tables, IAM roles, and Secrets Manager.
- **Bedrock** — the Guardrail, the Knowledge Base (with its S3 Vectors index and source
  bucket), and AgentCore Memory.
- **Agent** — the ECR repository, CodeBuild project, AgentCore Runtime, and observability.
- **ChatApp** — the web front end, hosted on ECS Express Mode or on CloudFront with a
  Lambda Web Adapter.

The default foundation model is Anthropic Claude Sonnet. The embedding model for the
Knowledge Base is Amazon Titan Text Embeddings V2 (1024 dimensions, cosine distance).

## 6. Frequently asked questions

**How do I add knowledge for the agent to use?**
Upload a document through the Knowledge Base Explorer, or copy files into the `documents/`
prefix of the Knowledge Base source bucket and start an ingestion job. The Explorer starts
the job for you on upload.

**Why doesn't the agent know about a document I just added?**
Bedrock needs to run an ingestion job before new content is retrievable. Ingestion takes a
few minutes. If you added files outside the Explorer, start the ingestion job manually.

**What file types can the Explorer preview?**
Text-based files such as Markdown, plain text, JSON, CSV, YAML, HTML, and XML are rendered
inline. Binary formats such as PDF are listed but not previewed in the browser.

**Where are conversations stored?**
Short-term conversation context and long-term memory (summaries, facts, and preferences)
are stored in AgentCore Memory. Usage and analytics records are stored in DynamoDB.
