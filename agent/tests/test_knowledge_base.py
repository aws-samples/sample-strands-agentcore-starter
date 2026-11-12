"""Unit tests for agent/tools/knowledge_base.py"""

import json
import os
from unittest.mock import MagicMock, patch

import pytest


class TestGetKbClient:
    def test_creates_client_with_user_agent(self):
        with patch("boto3.client") as mock_client:
            mock_client.return_value = MagicMock()
            from agent.tools.knowledge_base import _get_kb_client
            _get_kb_client()
            config = mock_client.call_args.kwargs.get("config") or mock_client.call_args[1].get("config")
            assert "aws-agentcore-starter/bedrock-kb" in config.user_agent_extra


class TestGetKbType:
    def test_default_is_vector(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("KNOWLEDGE_BASE_TYPE", None)
            from agent.tools.knowledge_base import _get_kb_type
            assert _get_kb_type() == "VECTOR"

    def test_managed_from_env(self):
        with patch.dict(os.environ, {"KNOWLEDGE_BASE_TYPE": "MANAGED"}):
            from agent.tools.knowledge_base import _get_kb_type
            assert _get_kb_type() == "MANAGED"


class TestSearchKnowledgeBase:
    """Tests call the underlying function via _tool_func to bypass Strands decorator."""

    def _call(self, **kwargs):
        """Call the underlying tool function directly."""
        from agent.tools.knowledge_base import search_knowledge_base
        return json.loads(search_knowledge_base._tool_func(**kwargs))

    def test_no_kb_id_returns_error(self):
        with patch.dict(os.environ, {"KB_ID": ""}):
            result = self._call(query="test")
            assert result["success"] is False
            assert "not configured" in result["error"]

    def test_empty_query_returns_empty(self):
        with patch.dict(os.environ, {"KB_ID": "TEST_KB"}):
            result = self._call(query="")
            assert result["success"] is True
            assert result["result_count"] == 0

    def test_vector_type_uses_vector_config(self):
        with patch.dict(os.environ, {"KB_ID": "TEST_KB", "KNOWLEDGE_BASE_TYPE": "VECTOR"}):
            mock_client = MagicMock()
            mock_client.retrieve.return_value = {
                "retrievalResults": [
                    {"content": {"text": "Result"}, "score": 0.9, "location": {"type": "S3", "s3Location": {"uri": "s3://b/k"}}}
                ]
            }

            with patch("agent.tools.knowledge_base._get_kb_client", return_value=mock_client):
                result = self._call(query="test query")

            assert result["success"] is True
            assert result["result_count"] == 1
            call_kwargs = mock_client.retrieve.call_args.kwargs
            assert "vectorSearchConfiguration" in call_kwargs["retrievalConfiguration"]

    def test_managed_type_uses_managed_config(self):
        with patch.dict(os.environ, {"KB_ID": "TEST_KB", "KNOWLEDGE_BASE_TYPE": "MANAGED", "USE_AGENTIC_RETRIEVAL": "false"}):
            mock_client = MagicMock()
            mock_client.retrieve.return_value = {
                "retrievalResults": [
                    {"content": {"text": "Managed result"}, "score": 0.8, "location": {"type": "S3", "s3Location": {"uri": "s3://b/m"}}}
                ]
            }

            with patch("agent.tools.knowledge_base._get_kb_client", return_value=mock_client):
                result = self._call(query="test query")

            assert result["success"] is True
            assert result["result_count"] == 1
            call_kwargs = mock_client.retrieve.call_args.kwargs
            assert "managedSearchConfiguration" in call_kwargs["retrievalConfiguration"]

    def test_managed_agentic_with_fallback(self):
        with patch.dict(os.environ, {"KB_ID": "TEST_KB", "KNOWLEDGE_BASE_TYPE": "MANAGED", "USE_AGENTIC_RETRIEVAL": "true"}):
            mock_client = MagicMock()
            mock_client.agentic_retrieve_stream.side_effect = Exception("Not available")
            mock_client.retrieve.return_value = {
                "retrievalResults": [
                    {"content": {"text": "Fallback"}, "score": 0.7, "location": {"type": "S3", "s3Location": {"uri": "s3://b/f"}}}
                ]
            }

            with patch("agent.tools.knowledge_base._get_kb_client", return_value=mock_client):
                result = self._call(query="test")

            assert result["success"] is True
            assert "Fallback" in result["results"][0]["text"]
            mock_client.agentic_retrieve_stream.assert_called_once()
            mock_client.retrieve.assert_called_once()

    def test_min_score_filtering(self):
        with patch.dict(os.environ, {"KB_ID": "TEST_KB", "KNOWLEDGE_BASE_TYPE": "VECTOR"}):
            mock_client = MagicMock()
            mock_client.retrieve.return_value = {
                "retrievalResults": [
                    {"content": {"text": "High"}, "score": 0.9, "location": {}},
                    {"content": {"text": "Low"}, "score": 0.2, "location": {}},
                ]
            }

            with patch("agent.tools.knowledge_base._get_kb_client", return_value=mock_client):
                result = self._call(query="test", min_score=0.5)

            assert result["result_count"] == 1
            assert result["results"][0]["text"] == "High"

    def test_resource_not_found_handled(self):
        with patch.dict(os.environ, {"KB_ID": "INVALID_KB", "KNOWLEDGE_BASE_TYPE": "VECTOR"}):
            mock_client = MagicMock()
            mock_client.retrieve.side_effect = Exception("ResourceNotFoundException: KB not found")

            with patch("agent.tools.knowledge_base._get_kb_client", return_value=mock_client):
                result = self._call(query="test")

            assert result["success"] is False
            assert "not found" in result["error"]
