# Bedrock Managed Knowledge Base Support

## Changes
- CDK `bedrock-stack.ts` updated to create managed KB with `addPropertyOverride`
- Knowledge Base tool uses `managedSearchConfiguration` for retrieval by default
- Added `MANAGED_KNOWLEDGE_BASE_CONNECTOR` data source in CDK stack
- Agent `knowledge_base.py` tool updated to branch on KB type for search config
- AgentCore memory integration unchanged; KB retrieval is separate path

## Design
- MANAGED available via `--context knowledgeBaseType=MANAGED`; VECTOR is the default for backward compatibility
- CDK uses `addPropertyOverride` since L2 constructs don't support managed type natively
- AgenticRetrieveStream available for enhanced retrieval quality
- Backward compatible: existing VECTOR deployments unaffected

## API Shapes
- KB Creation: `type: MANAGED` + `managedKnowledgeBaseConfiguration.embeddingModelType: MANAGED`
- Data Source: `type: MANAGED_KNOWLEDGE_BASE_CONNECTOR`
- Retrieval: `managedSearchConfiguration` (not `vectorSearchConfiguration`)
- Agentic: `AgenticRetrieveStream` with `foundationModelType: MANAGED`, `rerankingModelType: MANAGED`

## Configuration
| Variable | Description | Default |
|---|---|---|
| KNOWLEDGE_BASE_TYPE | MANAGED or VECTOR | MANAGED |
| USE_AGENTIC_RETRIEVAL | Enable agentic retrieval | true |
| KB_ID | KB identifier (from CDK output) | (required) |

## SDK Requirements
- boto3 >= 1.43 for managed search and agentic retrieval
- aws-cdk-lib >= 2.170.0 for KB L1 constructs

## Required IAM Permissions
```json
{
  "Effect": "Allow",
  "Action": [
    "bedrock:Retrieve",
    "bedrock:AgenticRetrieveStream"
  ],
  "Resource": "arn:aws:bedrock:<region>:<account-id>:knowledge-base/<kb-id>"
}
```

## Direct Ingestion (DLA API)

When a CUSTOM data source is configured on the KB, documents can be ingested directly without triggering a full S3 sync:

```bash
# Enable direct ingestion (opt-in)
export USE_DIRECT_INGESTION=true
```

With direct ingestion enabled, the Knowledge Base Explorer's upload feature will:
1. Try `IngestKnowledgeBaseDocuments` API first (immediate, no full sync)
2. Fall back to S3 upload + `StartIngestionJob` if no CUSTOM data source exists

Supported content: text files, PDFs, DOCX, HTML, CSV, and binary files (with appropriate mimeType).

> **Prerequisite:** Add a CUSTOM data source to your KB via the AWS console (Knowledge Bases → your KB → Add data source → Custom).

**References:**
- [Ingest documents directly into a knowledge base](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-direct-ingestion.html)
- [IngestKnowledgeBaseDocuments API](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent_IngestKnowledgeBaseDocuments.html)
- [Connect to a custom data source](https://docs.aws.amazon.com/bedrock/latest/userguide/custom-data-source-connector.html)

