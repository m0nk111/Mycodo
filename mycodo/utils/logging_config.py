# coding=utf-8
"""
Structured logging configuration using structlog.

This module provides a centralized configuration for structured logging
across the Mycodo application. It configures structlog with JSON output
for production and console output for development.
"""
import logging
import sys
from typing import Any, Dict

import structlog
from structlog.types import EventDict, Processor


def add_app_context(logger: logging.Logger, method_name: str, event_dict: EventDict) -> EventDict:
    """
    Add application context to log entries.
    
    Args:
        logger: The logger instance
        method_name: The name of the log method
        event_dict: The event dictionary
        
    Returns:
        Modified event dictionary with application context
    """
    event_dict['app'] = 'mycodo'
    return event_dict


def setup_structlog(json_logs: bool = True, log_level: str = "INFO") -> None:
    """
    Configure structlog for the application.
    
    Args:
        json_logs: If True, output logs in JSON format. If False, use console format.
        log_level: The logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    # Configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper(), logging.INFO),
    )
    
    # Define processors based on output format
    processors: list[Processor] = [
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.contextvars.merge_contextvars,
        add_app_context,
        structlog.processors.StackInfoRenderer(),
    ]
    
    if json_logs:
        # Production: JSON output
        processors.extend([
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer()
        ])
    else:
        # Development: Console output with colors
        processors.extend([
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer()
        ])
    
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = None) -> structlog.stdlib.BoundLogger:
    """
    Get a configured structlog logger.
    
    Args:
        name: The name for the logger. If None, uses the calling module name.
        
    Returns:
        A configured structlog logger instance
    """
    return structlog.get_logger(name)


def bind_context(**kwargs: Any) -> None:
    """
    Bind context variables to the current thread/context.
    
    This allows adding context that will be included in all subsequent
    log entries within the same context (e.g., request_id, user_id).
    
    Args:
        **kwargs: Key-value pairs to bind to the logging context
    """
    structlog.contextvars.bind_contextvars(**kwargs)


def unbind_context(*keys: str) -> None:
    """
    Unbind context variables from the current thread/context.
    
    Args:
        *keys: Keys to unbind from the logging context
    """
    structlog.contextvars.unbind_contextvars(*keys)


def clear_context() -> None:
    """Clear all context variables from the current thread/context."""
    structlog.contextvars.clear_contextvars()
