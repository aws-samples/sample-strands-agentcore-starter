"""Unit tests for authentication module.

Tests for Cognito OAuth client, middleware, and configuration validation.
"""

import pytest
import json
import time
import base64
from unittest.mock import patch, MagicMock

# Test configuration module
class TestConfiguration:
    """Tests for configuration module."""

    def test_configuration_error_includes_variable_name(self):
        """Test that ConfigurationError includes the variable name."""
        from app.config import ConfigurationError
        
        error = ConfigurationError("TEST_VAR")
        assert "TEST_VAR" in str(error)
        assert error.variable_name == "TEST_VAR"

    def test_configuration_error_with_custom_message(self):
        """Test ConfigurationError with custom message."""
        from app.config import ConfigurationError
        
        error = ConfigurationError("TEST_VAR", "custom message")
        assert "TEST_VAR" in str(error)
        assert "custom message" in str(error)

    @patch.dict('os.environ', {}, clear=True)
    def test_missing_required_env_var_raises_error(self):
        """Test that missing required env vars raise ConfigurationError."""
        from app.config import AppConfig, ConfigurationError, get_config
        
        # Clear the cache
        get_config.cache_clear()
        
        with pytest.raises(ConfigurationError) as exc_info:
            AppConfig.from_env()
        
        # Should mention the first missing variable
        assert exc_info.value.variable_name in [
            "COGNITO_USER_POOL_ID",
            "COGNITO_CLIENT_ID", 
            "COGNITO_CLIENT_SECRET",
            "AGENTCORE_RUNTIME_ARN",
            "AWS_REGION",
            "MEMORY_ID",
        ]

    @patch.dict('os.environ', {
        'COGNITO_USER_POOL_ID': 'us-east-1_testpool',
        'COGNITO_CLIENT_ID': 'test-client-id',
        'COGNITO_CLIENT_SECRET': 'test-client-secret',
        'AGENTCORE_RUNTIME_ARN': 'arn:aws:bedrock:us-east-1:123456789:agent/test',
        'AWS_REGION': 'us-east-1',
        'MEMORY_ID': 'test-memory-id',
    }, clear=True)
    def test_valid_config_loads_successfully(self):
        """Test that valid configuration loads without error."""
        from app.config import AppConfig, get_config
        
        # Clear the cache
        get_config.cache_clear()
        
        config = AppConfig.from_env()
        
        assert config.cognito_user_pool_id == 'us-east-1_testpool'
        assert config.cognito_client_id == 'test-client-id'
        assert config.cognito_client_secret == 'test-client-secret'
        assert config.aws_region == 'us-east-1'
        assert config.memory_id == 'test-memory-id'


# Test Cognito auth module
class TestCognitoAuth:
    """Tests for Cognito direct API authentication client."""

    @patch.dict('os.environ', {
        'COGNITO_USER_POOL_ID': 'us-east-1_testpool',
        'COGNITO_CLIENT_ID': 'test-client-id',
        'COGNITO_CLIENT_SECRET': 'test-client-secret',
        'AGENTCORE_RUNTIME_ARN': 'arn:aws:bedrock:us-east-1:123456789:agent/test',
        'AWS_REGION': 'us-east-1',
        'MEMORY_ID': 'test-memory-id',
        'APP_URL': 'http://localhost:8080',
    }, clear=True)
    def test_cognito_auth_initializes_with_config(self):
        """Test that CognitoAuth initializes with configuration values."""
        from app.config import get_config
        from app.auth.cognito import CognitoAuth
        
        get_config.cache_clear()
        
        auth = CognitoAuth()
        
        assert auth.user_pool_id == 'us-east-1_testpool'
        assert auth.client_id == 'test-client-id'
        assert auth.client_secret == 'test-client-secret'
        assert auth.region == 'us-east-1'

    @patch.dict('os.environ', {
        'COGNITO_USER_POOL_ID': 'us-east-1_testpool',
        'COGNITO_CLIENT_ID': 'test-client-id',
        'COGNITO_CLIENT_SECRET': 'test-client-secret',
        'AGENTCORE_RUNTIME_ARN': 'arn:aws:bedrock:us-east-1:123456789:agent/test',
        'AWS_REGION': 'us-east-1',
        'MEMORY_ID': 'test-memory-id',
        'APP_URL': 'http://localhost:8080',
    }, clear=True)
    def test_cognito_auth_generates_secret_hash(self):
        """Test that CognitoAuth generates correct secret hash."""
        from app.config import get_config
        from app.auth.cognito import CognitoAuth
        
        get_config.cache_clear()
        
        auth = CognitoAuth()
        secret_hash = auth._get_secret_hash("test@example.com")
        
        # Secret hash should be a base64 encoded string
        assert isinstance(secret_hash, str)
        assert len(secret_hash) > 0


class TestJWTExtraction:
    """Tests for JWT user ID extraction."""

    @patch.dict('os.environ', {
        'COGNITO_USER_POOL_ID': 'us-east-1_testpool',
        'COGNITO_CLIENT_ID': 'test-client-id',
        'COGNITO_CLIENT_SECRET': 'test-client-secret',
        'AGENTCORE_RUNTIME_ARN': 'arn:aws:bedrock:us-east-1:123456789:agent/test',
        'AWS_REGION': 'us-east-1',
        'MEMORY_ID': 'test-memory-id',
        'APP_URL': 'http://localhost:8080',
    }, clear=True)
    def test_extract_user_id_from_valid_token(self):
        """Test extracting user ID from a valid JWT token."""
        from app.config import get_config
        from app.auth.cognito import CognitoAuth, UserInfo
        
        get_config.cache_clear()
        
        # Mock the validate_token method to return expected user info
        with patch.object(CognitoAuth, 'validate_token') as mock_validate:
            mock_validate.return_value = UserInfo(
                user_id="user-123-abc",
                email="test@example.com",
                username="testuser"
            )
            
            from app.auth.cognito import extract_user_id
            
            # Create a dummy token (validation is mocked)
            token = "dummy.token.value"
            
            user_id = extract_user_id(token)
            assert user_id == "user-123-abc"

    @patch.dict('os.environ', {
        'COGNITO_USER_POOL_ID': 'us-east-1_testpool',
        'COGNITO_CLIENT_ID': 'test-client-id',
        'COGNITO_CLIENT_SECRET': 'test-client-secret',
        'AGENTCORE_RUNTIME_ARN': 'arn:aws:bedrock:us-east-1:123456789:agent/test',
        'AWS_REGION': 'us-east-1',
        'MEMORY_ID': 'test-memory-id',
        'APP_URL': 'http://localhost:8080',
    }, clear=True)
    def test_extract_user_id_missing_sub_raises_error(self):
        """Test that missing sub claim raises TokenValidationError."""
        from app.config import get_config
        from app.auth.cognito import CognitoAuth, TokenValidationError
        
        get_config.cache_clear()
        
        # Mock validate_token to raise TokenValidationError for missing sub
        with patch.object(CognitoAuth, 'validate_token') as mock_validate:
            mock_validate.side_effect = TokenValidationError("Token missing 'sub' claim")
            
            from app.auth.cognito import extract_user_id
            
            token = "dummy.token.value"
            
            with pytest.raises(TokenValidationError) as exc_info:
                extract_user_id(token)
            
            assert "sub" in str(exc_info.value)

    def test_extract_user_id_invalid_token_raises_error(self):
        """Test that invalid token raises TokenValidationError."""
        from app.auth.cognito import extract_user_id, TokenValidationError
        
        with pytest.raises(TokenValidationError):
            extract_user_id("not-a-valid-token")


class TestValidateToken:
    """Tests for token validation."""

    @patch.dict('os.environ', {
        'COGNITO_USER_POOL_ID': 'us-east-1_testpool',
        'COGNITO_CLIENT_ID': 'test-client-id',
        'COGNITO_CLIENT_SECRET': 'test-client-secret',
        'AGENTCORE_RUNTIME_ARN': 'arn:aws:bedrock:us-east-1:123456789:agent/test',
        'AWS_REGION': 'us-east-1',
        'MEMORY_ID': 'test-memory-id',
        'APP_URL': 'http://localhost:8080',
    }, clear=True)
    def test_validate_token_extracts_user_info(self):
        """Test that validate_token extracts user info correctly."""
        from app.config import get_config
        from app.auth.cognito import CognitoAuth, UserInfo
        
        get_config.cache_clear()
        
        auth = CognitoAuth()
        
        # Mock the internal methods to bypass JWKS validation
        mock_signing_key = {"kty": "RSA", "kid": "test-key-id"}
        
        with patch.object(auth, '_get_signing_key', return_value=mock_signing_key):
            with patch('app.auth.cognito.jwk.construct') as mock_construct:
                with patch('app.auth.cognito.jwt.decode') as mock_decode:
                    mock_decode.return_value = {
                        "sub": "user-456-def",
                        "email": "user@example.com",
                        "cognito:username": "testuser",
                        "token_use": "access",
                        "exp": int(time.time()) + 3600
                    }
                    
                    token = "dummy.token.value"
                    user_info = auth.validate_token(token)
                    
                    assert user_info.user_id == "user-456-def"

    @patch.dict('os.environ', {
        'COGNITO_USER_POOL_ID': 'us-east-1_testpool',
        'COGNITO_CLIENT_ID': 'test-client-id',
        'COGNITO_CLIENT_SECRET': 'test-client-secret',
        'AGENTCORE_RUNTIME_ARN': 'arn:aws:bedrock:us-east-1:123456789:agent/test',
        'AWS_REGION': 'us-east-1',
        'MEMORY_ID': 'test-memory-id',
        'APP_URL': 'http://localhost:8080',
    }, clear=True)
    def test_validate_token_expired_raises_error(self):
        """Test that expired token raises TokenExpiredError."""
        from app.config import get_config
        from app.auth.cognito import CognitoAuth, TokenExpiredError
        from jose.exceptions import ExpiredSignatureError
        
        get_config.cache_clear()
        
        auth = CognitoAuth()
        
        # Mock the internal methods to simulate expired token
        mock_signing_key = {"kty": "RSA", "kid": "test-key-id"}
        
        with patch.object(auth, '_get_signing_key', return_value=mock_signing_key):
            with patch('app.auth.cognito.jwk.construct') as mock_construct:
                with patch('app.auth.cognito.jwt.decode') as mock_decode:
                    mock_decode.side_effect = ExpiredSignatureError("Token has expired")
                    
                    token = "dummy.expired.token"
                    
                    with pytest.raises(TokenExpiredError):
                        auth.validate_token(token)
