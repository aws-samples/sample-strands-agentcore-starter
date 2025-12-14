"""Cognito authentication client using direct API calls.

This module provides the CognitoAuth class for handling authentication
with AWS Cognito using the InitiateAuth API (no hosted UI required).
"""

import base64
import hashlib
import hmac
import logging
import time
from dataclasses import dataclass
from typing import Optional

import boto3
import httpx
from botocore.exceptions import ClientError
from jose import jwk, jwt, JWTError
from jose.exceptions import ExpiredSignatureError

from app.config import get_config

logger = logging.getLogger(__name__)

# Module-level JWKS cache (shared across instances)
_jwks_cache: Optional[dict] = None
_jwks_cache_time: float = 0
JWKS_CACHE_TTL = 3600  # Cache JWKS for 1 hour


class AuthenticationError(Exception):
    """Raised when authentication fails."""
    pass


class TokenExpiredError(AuthenticationError):
    """Raised when a token has expired."""
    pass


class TokenValidationError(AuthenticationError):
    """Raised when token validation fails."""
    pass


@dataclass
class TokenResponse:
    """Response from Cognito authentication.
    
    Attributes:
        access_token: JWT access token for API calls
        id_token: JWT ID token containing user claims
        refresh_token: Token for refreshing access tokens
        expires_in: Token expiration time in seconds
        token_type: Token type (typically "Bearer")
    """
    access_token: str
    id_token: str
    refresh_token: Optional[str]
    expires_in: int
    token_type: str


@dataclass
class UserInfo:
    """User information extracted from JWT token.
    
    Attributes:
        user_id: The unique user identifier (sub claim)
        email: User's email address
        username: Cognito username
    """
    user_id: str
    email: Optional[str] = None
    username: Optional[str] = None


class CognitoAuth:
    """Cognito authentication client using direct API calls.
    
    This class handles authentication using Cognito's InitiateAuth API,
    which doesn't require the hosted UI or callback URLs.
    """

    def __init__(
        self,
        user_pool_id: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        region: Optional[str] = None,
    ):
        """Initialize CognitoAuth with configuration.
        
        Args:
            user_pool_id: Cognito User Pool ID (defaults to config)
            client_id: Client ID (defaults to config)
            client_secret: Client secret (defaults to config)
            region: AWS region (defaults to config)
        """
        config = get_config()
        self.user_pool_id = user_pool_id or config.cognito_user_pool_id
        self.client_id = client_id or config.cognito_client_id
        self.client_secret = client_secret or config.cognito_client_secret
        self.region = region or config.aws_region
        
        # Create Cognito client
        self._client = boto3.client(
            'cognito-idp',
            region_name=self.region
        )
        
        # JWKS URI for token validation
        self._jwks_uri = f"https://cognito-idp.{self.region}.amazonaws.com/{self.user_pool_id}/.well-known/jwks.json"
        self._jwks_cache: Optional[dict] = None

    def _get_secret_hash(self, username: str) -> str:
        """Generate secret hash for Cognito API calls.
        
        Args:
            username: The username to hash
            
        Returns:
            Base64 encoded HMAC-SHA256 hash
        """
        message = username + self.client_id
        dig = hmac.new(
            self.client_secret.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).digest()
        return base64.b64encode(dig).decode()

    async def authenticate(self, email: str, password: str) -> TokenResponse:
        """Authenticate user with email and password.
        
        Args:
            email: User's email address
            password: User's password
            
        Returns:
            TokenResponse with access, ID, and refresh tokens
            
        Raises:
            AuthenticationError: If authentication fails
        """
        try:
            response = self._client.initiate_auth(
                ClientId=self.client_id,
                AuthFlow='USER_PASSWORD_AUTH',
                AuthParameters={
                    'USERNAME': email,
                    'PASSWORD': password,
                    'SECRET_HASH': self._get_secret_hash(email),
                }
            )
            
            auth_result = response.get('AuthenticationResult', {})
            
            return TokenResponse(
                access_token=auth_result['AccessToken'],
                id_token=auth_result['IdToken'],
                refresh_token=auth_result.get('RefreshToken'),
                expires_in=auth_result.get('ExpiresIn', 3600),
                token_type=auth_result.get('TokenType', 'Bearer'),
            )
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            error_message = e.response.get('Error', {}).get('Message', str(e))
            
            if error_code in ('NotAuthorizedException', 'UserNotFoundException'):
                raise AuthenticationError("Invalid email or password")
            elif error_code == 'UserNotConfirmedException':
                raise AuthenticationError("User account not confirmed")
            elif error_code == 'PasswordResetRequiredException':
                raise AuthenticationError("Password reset required")
            else:
                raise AuthenticationError(f"Authentication failed: {error_message}")

    async def refresh_tokens(self, refresh_token: str, username: str) -> TokenResponse:
        """Refresh expired access tokens.
        
        Args:
            refresh_token: Valid refresh token
            username: Username associated with the token
            
        Returns:
            TokenResponse with new access and ID tokens
            
        Raises:
            AuthenticationError: If token refresh fails
        """
        try:
            response = self._client.initiate_auth(
                ClientId=self.client_id,
                AuthFlow='REFRESH_TOKEN_AUTH',
                AuthParameters={
                    'REFRESH_TOKEN': refresh_token,
                    'SECRET_HASH': self._get_secret_hash(username),
                }
            )
            
            auth_result = response.get('AuthenticationResult', {})
            
            return TokenResponse(
                access_token=auth_result['AccessToken'],
                id_token=auth_result['IdToken'],
                refresh_token=auth_result.get('RefreshToken', refresh_token),
                expires_in=auth_result.get('ExpiresIn', 3600),
                token_type=auth_result.get('TokenType', 'Bearer'),
            )
            
        except ClientError as e:
            error_message = e.response.get('Error', {}).get('Message', str(e))
            raise AuthenticationError(f"Token refresh failed: {error_message}")

    def _get_jwks(self) -> dict:
        """Fetch and cache JWKS from Cognito.
        
        Returns:
            JWKS dictionary with 'keys' array
            
        Raises:
            TokenValidationError: If JWKS cannot be fetched
        """
        global _jwks_cache, _jwks_cache_time
        
        # Return cached JWKS if still valid
        if _jwks_cache and (time.time() - _jwks_cache_time) < JWKS_CACHE_TTL:
            return _jwks_cache
        
        try:
            # Fetch JWKS from Cognito
            with httpx.Client(timeout=10.0) as client:
                response = client.get(self._jwks_uri)
                response.raise_for_status()
                _jwks_cache = response.json()
                _jwks_cache_time = time.time()
                logger.debug(f"Fetched JWKS from {self._jwks_uri}")
                return _jwks_cache
        except httpx.HTTPError as e:
            logger.error(f"Failed to fetch JWKS: {e}")
            # If we have a stale cache, use it rather than failing
            if _jwks_cache:
                logger.warning("Using stale JWKS cache")
                return _jwks_cache
            raise TokenValidationError(f"Failed to fetch JWKS: {e}")

    def _get_signing_key(self, token: str) -> dict:
        """Get the signing key for a token from JWKS.
        
        Args:
            token: JWT token to get signing key for
            
        Returns:
            JWK dictionary for the signing key
            
        Raises:
            TokenValidationError: If signing key not found
        """
        try:
            # Get the key ID from the token header
            unverified_header = jwt.get_unverified_header(token)
            kid = unverified_header.get("kid")
            
            if not kid:
                raise TokenValidationError("Token missing 'kid' header")
            
            # Find the matching key in JWKS
            jwks = self._get_jwks()
            for key in jwks.get("keys", []):
                if key.get("kid") == kid:
                    return key
            
            # Key not found - might need to refresh cache
            logger.warning(f"Key {kid} not found in JWKS, refreshing cache")
            global _jwks_cache_time
            _jwks_cache_time = 0  # Force refresh
            jwks = self._get_jwks()
            
            for key in jwks.get("keys", []):
                if key.get("kid") == kid:
                    return key
            
            raise TokenValidationError(f"Signing key {kid} not found in JWKS")
            
        except JWTError as e:
            raise TokenValidationError(f"Invalid token header: {e}")

    def validate_token(self, token: str, verify_exp: bool = True, id_token: str = None) -> UserInfo:
        """Validate JWT token with cryptographic signature verification.
        
        Verifies the token signature against Cognito's JWKS endpoint to ensure
        the token was issued by the expected Cognito User Pool.
        
        Args:
            token: JWT access token for validation
            verify_exp: Whether to verify token expiration
            id_token: Optional ID token to extract user claims from (has email, username)
            
        Returns:
            UserInfo with user ID and claims
            
        Raises:
            TokenExpiredError: If token has expired
            TokenValidationError: If token signature is invalid or token is malformed
        """
        try:
            # Get the signing key for this token
            signing_key = self._get_signing_key(token)
            
            # Build the public key from JWK
            public_key = jwk.construct(signing_key)
            
            # Expected issuer for this Cognito User Pool
            issuer = f"https://cognito-idp.{self.region}.amazonaws.com/{self.user_pool_id}"
            
            # Decode and verify the token
            # This verifies: signature, expiration (if verify_exp), issuer
            claims = jwt.decode(
                token,
                public_key,
                algorithms=["RS256"],
                issuer=issuer,
                options={
                    "verify_exp": verify_exp,
                    "verify_aud": False,  # Access tokens use 'client_id' not 'aud'
                    "verify_iss": True,
                },
            )
            
            # Verify token_use claim for access tokens
            token_use = claims.get("token_use")
            if token_use not in ("access", "id"):
                raise TokenValidationError(f"Invalid token_use: {token_use}")
            
            # Extract user information
            user_id = claims.get("sub")
            if not user_id:
                raise TokenValidationError("Token missing 'sub' claim")
            
            # If ID token provided, verify and extract richer user info
            email = None
            username = None
            if id_token:
                try:
                    id_signing_key = self._get_signing_key(id_token)
                    id_public_key = jwk.construct(id_signing_key)
                    id_claims = jwt.decode(
                        id_token,
                        id_public_key,
                        algorithms=["RS256"],
                        issuer=issuer,
                        audience=self.client_id,  # ID tokens have audience
                        options={"verify_exp": verify_exp},
                    )
                    email = id_claims.get("email")
                    username = id_claims.get("cognito:username") or email
                except Exception as e:
                    logger.warning(f"Failed to verify ID token: {e}")
                    # Fall back to unverified claims for email (non-critical)
                    try:
                        id_claims = jwt.get_unverified_claims(id_token)
                        email = id_claims.get("email")
                        username = id_claims.get("cognito:username") or email
                    except Exception:
                        pass
            
            return UserInfo(
                user_id=user_id,
                email=email,
                username=username,
            )
            
        except ExpiredSignatureError:
            raise TokenExpiredError("Token has expired")
        except JWTError as e:
            raise TokenValidationError(f"Invalid token: {str(e)}")


def extract_user_id(token: str) -> str:
    """Extract user ID from JWT token with signature verification.
    
    Uses sub (UUID) for memory operations - required by AgentCore Memory API.
    Verifies the token signature against Cognito's JWKS.
    
    Args:
        token: JWT token (access or ID token)
        
    Returns:
        User ID (sub UUID)
        
    Raises:
        TokenValidationError: If token is invalid, signature fails, or missing required claims
    """
    try:
        # Use CognitoAuth to verify the token properly
        auth = CognitoAuth()
        user_info = auth.validate_token(token, verify_exp=True)
        return user_info.user_id
    except (TokenExpiredError, TokenValidationError):
        raise
    except Exception as e:
        raise TokenValidationError(f"Invalid token: {str(e)}")


async def get_user_groups(username: str) -> list[str]:
    """Get the groups a user belongs to in Cognito.
    
    Args:
        username: The user's username (email)
        
    Returns:
        List of group names the user belongs to
    """
    config = get_config()
    client = boto3.client('cognito-idp', region_name=config.aws_region)
    
    try:
        response = client.admin_list_groups_for_user(
            UserPoolId=config.cognito_user_pool_id,
            Username=username,
        )
        return [group['GroupName'] for group in response.get('Groups', [])]
    except ClientError as e:
        logger.warning(f"Failed to get groups for user {username}: {e}")
        return []


def is_admin(groups: list[str]) -> bool:
    """Check if user is an admin based on their groups.
    
    Args:
        groups: List of group names the user belongs to
        
    Returns:
        True if user is in the Admin group
    """
    return "Admin" in groups


async def get_user_emails_by_ids(user_ids: list[str]) -> dict[str, str]:
    """Look up user emails from Cognito by user IDs (sub).
    
    Args:
        user_ids: List of user IDs (Cognito sub UUIDs)
        
    Returns:
        Dictionary mapping user_id to email address
    """
    if not user_ids:
        return {}
    
    config = get_config()
    client = boto3.client('cognito-idp', region_name=config.aws_region)
    
    email_map = {}
    
    for user_id in user_ids:
        try:
            # Use admin_get_user with filter by sub
            response = client.list_users(
                UserPoolId=config.cognito_user_pool_id,
                Filter=f'sub = "{user_id}"',
                Limit=1,
            )
            
            users = response.get('Users', [])
            if users:
                user = users[0]
                # Extract email from attributes
                for attr in user.get('Attributes', []):
                    if attr['Name'] == 'email':
                        email_map[user_id] = attr['Value']
                        break
        except ClientError:
            # Skip users that can't be looked up
            continue
    
    return email_map
