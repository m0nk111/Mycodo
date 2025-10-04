# coding=utf-8
"""
Flask middleware for logging and metrics collection.
"""
import time
import uuid

from flask import request, g

from mycodo.utils.logging_config import bind_context, clear_context, get_logger
from mycodo.utils.metrics import metrics_collector

logger = get_logger(__name__)


def setup_request_middleware(app):
    """
    Set up Flask middleware for request logging and metrics.
    
    Args:
        app: Flask application instance
    """
    
    @app.before_request
    def before_request():
        """Execute before each request."""
        # Generate and bind request ID for correlation
        request_id = str(uuid.uuid4())
        g.request_id = request_id
        g.start_time = time.time()
        
        # Bind context for structured logging
        bind_context(
            request_id=request_id,
            method=request.method,
            path=request.path,
            remote_addr=request.remote_addr
        )
        
        # Log the request
        logger.info(
            "request_started",
            method=request.method,
            path=request.path,
            remote_addr=request.remote_addr
        )
    
    @app.after_request
    def after_request(response):
        """Execute after each request."""
        # Calculate request duration
        if hasattr(g, 'start_time'):
            duration = time.time() - g.start_time
            
            # Record metrics
            metrics_collector.record_http_request(
                method=request.method,
                endpoint=request.endpoint or 'unknown',
                status=response.status_code,
                duration=duration
            )
            
            # Log the response
            logger.info(
                "request_completed",
                method=request.method,
                path=request.path,
                status_code=response.status_code,
                duration_seconds=duration
            )
        
        # Add request ID to response headers
        if hasattr(g, 'request_id'):
            response.headers['X-Request-ID'] = g.request_id
        
        # Clear context after request
        clear_context()
        
        return response
    
    @app.teardown_request
    def teardown_request(exception=None):
        """Execute on request teardown."""
        if exception:
            # Log exception
            logger.error(
                "request_exception",
                method=request.method,
                path=request.path,
                exception=str(exception),
                exc_info=True
            )
            
            # Record error metric
            metrics_collector.record_error(
                component='flask',
                error_type=type(exception).__name__
            )
        
        # Clear context
        clear_context()
