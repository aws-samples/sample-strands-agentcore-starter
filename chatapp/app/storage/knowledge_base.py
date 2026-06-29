"""Read/write browsing of the Bedrock Knowledge Base source documents.

Powers the **Knowledge Base Explorer** page (``/admin/kb``). Two data sources,
both the very same ones the agent relies on at query time:

1. **Source documents** — the files the Knowledge Base was built from, stored in
   the KB source S3 bucket under the ``documents/`` prefix. They can be listed,
   read (when text-based), and new ones can be uploaded.
2. **Semantic retrieval** — ``bedrock-agent-runtime:Retrieve`` against the
   vector Knowledge Base, i.e. exactly what the agent sees for a query.

There are **no document scopes** here: the explorer shows a single flat list of
every document under the ``documents/`` prefix.

Everything is **best-effort**: every public coroutine catches its own errors and
returns a structured dict with an ``error`` key rather than raising, so the UI
always renders.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from functools import lru_cache
from typing import Any, Optional

import boto3
from botocore.config import Config

logger = logging.getLogger(__name__)

# ── Configuration (env-resolved) ─────────────────────────────────────────────
_REGION = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))

# The data source ingests this prefix (see cdk/lib/bedrock-stack.ts inclusionPrefixes).
_DOC_PREFIX = "documents/"
# Uploaded files land under this sub-prefix so they're easy to distinguish from
# seeded content.
_UPLOAD_PREFIX = "documents/uploads/"

# Read cap so a huge file can't blow up the page.
_MAX_READ_BYTES = 512_000
# Upload cap (10 MB) — generous for documents, bounded for safety.
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024

# File extensions we render inline as text.
_TEXT_EXTENSIONS = {
    ".md", ".markdown", ".txt", ".text", ".json", ".csv", ".tsv",
    ".yaml", ".yml", ".html", ".htm", ".xml", ".log", ".rst",
}
# Extensions accepted for upload (text + common docs that Bedrock can parse).
_UPLOAD_EXTENSIONS = _TEXT_EXTENSIONS | {".pdf", ".doc", ".docx"}

# Filenames are sanitized to this character set.
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


@lru_cache(maxsize=1)
def _cfg() -> Config:
    return Config(region_name=_REGION, retries={"max_attempts": 2, "mode": "adaptive"})


@lru_cache(maxsize=1)
def _s3():
    return boto3.client("s3", config=_cfg())


@lru_cache(maxsize=1)
def _kb_runtime():
    return boto3.client("bedrock-agent-runtime", config=_cfg())


@lru_cache(maxsize=1)
def _kb_agent():
    return boto3.client("bedrock-agent", config=_cfg())


def _source_bucket() -> Optional[str]:
    return os.environ.get("KB_SOURCE_BUCKET", "").strip() or None


def _kb_id() -> Optional[str]:
    return os.environ.get("KB_ID", "").strip() or None


def is_configured() -> bool:
    """True when both the KB id and source bucket are available."""
    return bool(_kb_id() and _source_bucket())


def _ext(name: str) -> str:
    idx = name.rfind(".")
    return name[idx:].lower() if idx != -1 else ""


# ── Document listing ──────────────────────────────────────────────────────────
def _list_objects_sync(bucket: str, prefix: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    paginator = _s3().get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith("/"):
                continue
            name = key.rsplit("/", 1)[-1]
            out.append({
                "key": key,
                "name": name,
                "size": obj.get("Size", 0),
                "last_modified": obj.get("LastModified").isoformat() if obj.get("LastModified") else "",
                "readable": _ext(name) in _TEXT_EXTENSIONS,
            })
    return out


async def list_documents() -> dict[str, Any]:
    """List every KB source document under the ``documents/`` prefix (flat)."""
    bucket = _source_bucket()
    if not bucket:
        return {"documents": [], "error": "Knowledge Base source bucket is not configured."}

    try:
        loop = asyncio.get_event_loop()
        docs = await loop.run_in_executor(None, _list_objects_sync, bucket, _DOC_PREFIX)
    except Exception as e:  # noqa: BLE001
        logger.warning("KB list failed: %s", e)
        return {"documents": [], "error": "Could not list documents. Check the server logs for details."}

    docs.sort(key=lambda d: d["name"].lower())
    return {"documents": docs, "bucket": bucket}


# ── Document read ──────────────────────────────────────────────────────────────
def _get_object_text_sync(bucket: str, key: str) -> str:
    obj = _s3().get_object(Bucket=bucket, Key=key)
    body = obj["Body"].read(_MAX_READ_BYTES + 1)
    text = body[:_MAX_READ_BYTES].decode("utf-8", errors="replace")
    if len(body) > _MAX_READ_BYTES:
        text += "\n\n… [truncated]"
    return text


async def get_document(key: str) -> dict[str, Any]:
    """Return the text content of one KB source document. Best-effort."""
    bucket = _source_bucket()
    if not bucket:
        return {"error": "Knowledge Base source bucket is not configured."}
    # Guard against path traversal and reading outside the documents/ prefix.
    if not key or ".." in key or not key.startswith(_DOC_PREFIX):
        return {"error": "Invalid document key."}

    name = key.rsplit("/", 1)[-1]
    if _ext(name) not in _TEXT_EXTENSIONS:
        return {
            "key": key,
            "name": name,
            "readable": False,
            "content": "",
            "notice": "Preview is not available for this file type. Text formats "
                      "(Markdown, TXT, JSON, CSV, YAML, HTML, XML) render inline.",
        }

    try:
        loop = asyncio.get_event_loop()
        content = await loop.run_in_executor(None, _get_object_text_sync, bucket, key)
    except Exception as e:  # noqa: BLE001
        logger.warning("KB get_object failed (%s): %s", key, e)
        return {"error": "Could not read document. Check the server logs for details."}
    return {"key": key, "name": name, "readable": True, "content": content}


# ── Semantic search ────────────────────────────────────────────────────────────
def _retrieve_sync(kb_id: str, query: str, n: int) -> list[dict[str, Any]]:
    resp = _kb_runtime().retrieve(
        knowledgeBaseId=kb_id,
        retrievalQuery={"text": query},
        retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": n}},
    )
    hits = []
    for r in resp.get("retrievalResults", []):
        hits.append({
            "score": round(r.get("score") or 0.0, 4),
            "content": (r.get("content") or {}).get("text", ""),
            "uri": (r.get("location") or {}).get("s3Location", {}).get("uri", ""),
        })
    return hits


async def search(query: str, n: int = 5) -> dict[str, Any]:
    """Semantic search against the vector Knowledge Base (what the agent sees)."""
    if not query or not query.strip():
        return {"results": [], "error": "Enter a search query."}
    kb_id = _kb_id()
    if not kb_id:
        return {"results": [], "error": "Knowledge Base is not configured."}
    try:
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(
            None, _retrieve_sync, kb_id, query.strip(), max(1, min(int(n), 10))
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("KB retrieve failed: %s", e)
        return {"results": [], "error": "Retrieval failed. Check the server logs for details."}
    return {"results": results}


# ── Upload + ingestion ──────────────────────────────────────────────────────────
def _safe_filename(filename: str) -> str:
    """Strip any path and reduce to a safe, predictable filename."""
    base = (filename or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1].strip()
    base = _SAFE_NAME_RE.sub("-", base).strip("-._")
    return base or "upload"


def _start_ingestion_sync(kb_id: str) -> Optional[str]:
    """Start an ingestion job for the KB's first data source. Returns job id."""
    ds = _kb_agent().list_data_sources(knowledgeBaseId=kb_id, maxResults=1)
    summaries = ds.get("dataSourceSummaries", [])
    if not summaries:
        raise RuntimeError("No data source found for the Knowledge Base.")
    data_source_id = summaries[0]["dataSourceId"]
    job = _kb_agent().start_ingestion_job(
        knowledgeBaseId=kb_id,
        dataSourceId=data_source_id,
        description="Triggered by Knowledge Base Explorer upload",
    )
    return job.get("ingestionJob", {}).get("ingestionJobId")


def _put_object_sync(bucket: str, key: str, data: bytes, content_type: str) -> None:
    _s3().put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)


async def upload_document(filename: str, data: bytes, content_type: str = "") -> dict[str, Any]:
    """Write a new document under ``documents/uploads/`` and start ingestion.

    Returns a dict with ``key`` and ``ingestion_job_id`` on success, or ``error``.
    """
    bucket = _source_bucket()
    kb_id = _kb_id()
    if not bucket or not kb_id:
        return {"error": "Knowledge Base is not configured."}

    if not data:
        return {"error": "The uploaded file is empty."}
    if len(data) > _MAX_UPLOAD_BYTES:
        return {"error": f"File exceeds the {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB upload limit."}

    safe = _safe_filename(filename)
    if _ext(safe) not in _UPLOAD_EXTENSIONS:
        allowed = ", ".join(sorted(_UPLOAD_EXTENSIONS))
        return {"error": f"Unsupported file type. Allowed: {allowed}"}

    key = f"{_UPLOAD_PREFIX}{safe}"
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(
            None, _put_object_sync, bucket, key, data, content_type or "application/octet-stream"
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("KB upload put_object failed (%s): %s", key, e)
        return {"error": "Upload failed. Check the server logs for details."}

    # Best-effort ingestion trigger — the file is stored even if this fails.
    job_id: Optional[str] = None
    ingestion_error: Optional[str] = None
    try:
        job_id = await loop.run_in_executor(None, _start_ingestion_sync, kb_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("KB start_ingestion_job failed: %s", e)
        ingestion_error = "Ingestion could not be started. Check the server logs for details."

    return {
        "key": key,
        "name": safe,
        "size": len(data),
        "ingestion_job_id": job_id,
        "ingestion_error": ingestion_error,
    }
