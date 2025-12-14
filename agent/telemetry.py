"""OpenTelemetry integration for agent observability."""
import os
from typing import Optional
from strands.telemetry import StrandsTelemetry


class AgentTelemetry:
    """Manages OpenTelemetry setup for the agent.
    
    Provides a centralized way to configure tracing and metrics
    for the Strands agent with support for OTLP export and console debugging.
    """
    
    def __init__(self):
        """Initialize telemetry manager."""
        self._telemetry: Optional[StrandsTelemetry] = None
        self._initialized = False
    
    def setup(
        self,
        enabled: bool = True,
        otlp_endpoint: Optional[str] = None,
        console_export: bool = False,
        service_name: str = "agentcore-chat-agent"
    ) -> None:
        """Configure OpenTelemetry for the agent.
        
        Sets up tracing and metrics exporters based on configuration.
        This should be called once during agent initialization.
        
        Args:
            enabled: Whether to enable OpenTelemetry
            otlp_endpoint: OTLP collector endpoint (e.g., "http://collector:4318")
            console_export: Whether to export traces to console for debugging
            service_name: Service name for telemetry identification
        """
        if not enabled:
            return
        
        if self._initialized:
            return
        
        # Set service name for OpenTelemetry
        os.environ.setdefault("OTEL_SERVICE_NAME", service_name)
        
        # Initialize Strands telemetry
        self._telemetry = StrandsTelemetry()
        
        # Setup OTLP exporter if endpoint is provided
        if otlp_endpoint:
            os.environ.setdefault("OTEL_EXPORTER_OTLP_ENDPOINT", otlp_endpoint)
            self._telemetry.setup_otlp_exporter()
        
        # Setup console exporter for debugging
        if console_export:
            self._telemetry.setup_console_exporter()
        
        # Setup metrics with same exporters
        self._telemetry.setup_meter(
            enable_console_exporter=console_export,
            enable_otlp_exporter=bool(otlp_endpoint)
        )
        
        self._initialized = True
    
    @property
    def initialized(self) -> bool:
        """Check if telemetry has been initialized."""
        return self._initialized


# Global telemetry instance
_telemetry = AgentTelemetry()


def setup_telemetry(
    enabled: bool = True,
    otlp_endpoint: Optional[str] = None,
    console_export: bool = False,
    service_name: str = "agentcore-chat-agent"
) -> None:
    """Setup OpenTelemetry for the agent.
    
    Convenience function to configure the global telemetry instance.
    
    Args:
        enabled: Whether to enable OpenTelemetry
        otlp_endpoint: OTLP collector endpoint
        console_export: Whether to export traces to console
        service_name: Service name for telemetry
    """
    _telemetry.setup(
        enabled=enabled,
        otlp_endpoint=otlp_endpoint,
        console_export=console_export,
        service_name=service_name
    )


def is_telemetry_initialized() -> bool:
    """Check if telemetry has been initialized."""
    return _telemetry.initialized
