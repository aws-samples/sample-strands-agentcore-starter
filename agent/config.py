"""Configuration management for AgentCore backend."""
from dataclasses import dataclass
import os
from typing import Optional


@dataclass
class AgentConfig:
    """Configuration for the AgentCore agent.
    
    Attributes:
        memory_id: AgentCore Memory ID for conversation persistence
        aws_region: AWS region for AgentCore services
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
        otel_endpoint: OpenTelemetry collector endpoint (optional)
        otel_enabled: Whether to enable OpenTelemetry tracing
        otel_console_export: Whether to export traces to console (for debugging)
        guardrail_id: Bedrock guardrail identifier (optional)
        guardrail_version: Bedrock guardrail version (optional)
        guardrail_enabled: Whether guardrail evaluation is enabled
        kb_id: Bedrock Knowledge Base ID (optional)
        kb_max_results: Maximum number of KB search results to return
        kb_min_score: Minimum relevance score threshold for KB results
    """
    memory_id: str
    aws_region: str
    log_level: str = "INFO"
    otel_endpoint: Optional[str] = None
    otel_enabled: bool = True
    otel_console_export: bool = False
    guardrail_id: Optional[str] = None
    guardrail_version: str = "1"
    guardrail_enabled: bool = True
    kb_id: Optional[str] = None
    kb_max_results: int = 5
    kb_min_score: float = 0.5
    
    @classmethod
    def from_env(cls) -> "AgentConfig":
        """Load configuration from environment variables.
        
        Checks for AgentCore-provided environment variables first,
        then falls back to custom environment variables for local development.
        
        Returns:
            AgentConfig instance with values from environment
            
        Raises:
            ValueError: If required environment variables are missing
        """
        # Try AgentCore-provided env var first (set automatically when memory is configured)
        memory_id = os.getenv("BEDROCK_AGENTCORE_MEMORY_ID") or os.getenv("MEMORY_ID")
        if not memory_id:
            raise ValueError(
                "MEMORY_ID environment variable is required. "
                "Set it in your .env file or configure memory in .bedrock_agentcore.yaml"
            )
        
        aws_region = (
            os.getenv("AWS_REGION") or 
            "us-east-1"
        )
        log_level = os.getenv("LOG_LEVEL", "INFO")
        
        # OpenTelemetry configuration
        otel_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        otel_enabled = os.getenv("OTEL_ENABLED", "true").lower() in ("true", "1", "yes")
        otel_console_export = os.getenv("OTEL_CONSOLE_EXPORT", "false").lower() in ("true", "1", "yes")
        
        # Guardrail configuration
        guardrail_id = os.getenv("GUARDRAIL_ID")
        guardrail_version = os.getenv("GUARDRAIL_VERSION", "DRAFT")
        guardrail_enabled = os.getenv("GUARDRAIL_ENABLED", "true").lower() in ("true", "1", "yes")
        
        # Knowledge Base configuration
        kb_id = os.getenv("KB_ID")
        kb_max_results = int(os.getenv("KB_MAX_RESULTS", "5"))
        kb_min_score = float(os.getenv("KB_MIN_SCORE", "0.5"))
        
        return cls(
            memory_id=memory_id,
            aws_region=aws_region,
            log_level=log_level,
            otel_endpoint=otel_endpoint,
            otel_enabled=otel_enabled,
            otel_console_export=otel_console_export,
            guardrail_id=guardrail_id,
            guardrail_version=guardrail_version,
            guardrail_enabled=guardrail_enabled,
            kb_id=kb_id,
            kb_max_results=kb_max_results,
            kb_min_score=kb_min_score
        )
