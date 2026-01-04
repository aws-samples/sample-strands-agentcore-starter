"""Unit tests for FastAPI routes."""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


class TestHealthEndpoint:
    """Tests for health check endpoint."""

    def test_health_returns_200(self):
        """Test that health endpoint returns 200 OK."""
        # Mock config to avoid env var requirements
        with patch("app.config.get_config") as mock_config:
            mock_config.return_value = MagicMock(
                cognito_user_pool_id="test-pool",
                cognito_client_id="test-client",
                cognito_client_secret="test-secret",
                aws_region="us-east-1",
                agentcore_runtime_arn="arn:aws:test",
                memory_id="test-memory",
                app_url="http://localhost:8080",
                usage_table_name=None,
                feedback_table_name=None,
                guardrail_table_name=None,
                prompt_template_table_name=None,
                app_settings_table_name=None,
                runtime_usage_table_name=None,
                dev_mode=False,
            )
            from app.main import app
            client = TestClient(app)
            
            response = client.get("/health")
            
            assert response.status_code == 200

    def test_health_returns_status_healthy(self):
        """Test that health endpoint returns healthy status."""
        with patch("app.config.get_config") as mock_config:
            mock_config.return_value = MagicMock(
                cognito_user_pool_id="test-pool",
                cognito_client_id="test-client",
                cognito_client_secret="test-secret",
                aws_region="us-east-1",
                agentcore_runtime_arn="arn:aws:test",
                memory_id="test-memory",
                app_url="http://localhost:8080",
                usage_table_name=None,
                feedback_table_name=None,
                guardrail_table_name=None,
                prompt_template_table_name=None,
                app_settings_table_name=None,
                runtime_usage_table_name=None,
                dev_mode=False,
            )
            from app.main import app
            client = TestClient(app)
            
            response = client.get("/health")
            data = response.json()
            
            assert data["status"] == "healthy"

    def test_health_includes_version(self):
        """Test that health endpoint includes version."""
        with patch("app.config.get_config") as mock_config:
            mock_config.return_value = MagicMock(
                cognito_user_pool_id="test-pool",
                cognito_client_id="test-client",
                cognito_client_secret="test-secret",
                aws_region="us-east-1",
                agentcore_runtime_arn="arn:aws:test",
                memory_id="test-memory",
                app_url="http://localhost:8080",
                usage_table_name=None,
                feedback_table_name=None,
                guardrail_table_name=None,
                prompt_template_table_name=None,
                app_settings_table_name=None,
                runtime_usage_table_name=None,
                dev_mode=False,
            )
            from app.main import app
            client = TestClient(app)
            
            response = client.get("/health")
            data = response.json()
            
            assert "version" in data


class TestRootRedirect:
    """Tests for root endpoint redirect."""

    def test_root_redirects_to_chat(self):
        """Test that root endpoint redirects to /chat."""
        with patch("app.config.get_config") as mock_config:
            mock_config.return_value = MagicMock(
                cognito_user_pool_id="test-pool",
                cognito_client_id="test-client",
                cognito_client_secret="test-secret",
                aws_region="us-east-1",
                agentcore_runtime_arn="arn:aws:test",
                memory_id="test-memory",
                app_url="http://localhost:8080",
                usage_table_name=None,
                feedback_table_name=None,
                guardrail_table_name=None,
                prompt_template_table_name=None,
                app_settings_table_name=None,
                runtime_usage_table_name=None,
                dev_mode=False,
            )
            from app.main import app
            client = TestClient(app, follow_redirects=False)
            
            response = client.get("/")
            
            assert response.status_code == 302
            assert response.headers["location"] == "/chat"
