"""Structured logging configuration for AgentCore backend."""
import logging
import sys
from typing import Optional


def setup_logger(name: str, level: str = "INFO") -> logging.Logger:
    """Configure structured logging for the agent.
    
    Creates a logger with console output and structured formatting.
    Supports standard Python logging levels: DEBUG, INFO, WARNING, ERROR, CRITICAL.
    
    Args:
        name: Logger name (typically __name__ of the calling module)
        level: Log level as string (DEBUG, INFO, WARNING, ERROR, CRITICAL)
               Defaults to INFO if invalid level provided
    
    Returns:
        Configured logger instance ready for use
        
    Example:
        >>> logger = setup_logger(__name__, "DEBUG")
        >>> logger.info("Application started")
        >>> logger.debug("Detailed debug information")
    """
    logger = logging.getLogger(name)
    
    # Convert level string to logging constant, default to INFO if invalid
    try:
        log_level = getattr(logging, level.upper())
    except AttributeError:
        log_level = logging.INFO
        print(f"Warning: Invalid log level '{level}', defaulting to INFO", file=sys.stderr)
    
    logger.setLevel(log_level)
    
    # Avoid adding duplicate handlers if logger already configured
    if logger.handlers:
        return logger
    
    # Console handler with structured formatting
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)
    
    # Format: timestamp - module - level - message
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    handler.setFormatter(formatter)
    
    logger.addHandler(handler)
    
    # Prevent propagation to root logger to avoid duplicate logs
    logger.propagate = False
    
    return logger
