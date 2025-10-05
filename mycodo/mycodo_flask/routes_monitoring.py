# coding=utf-8
"""
Routes for monitoring endpoints (health checks and metrics).
"""
from flask import Blueprint, jsonify, Response

from mycodo.utils.health import health_checker
from mycodo.utils.metrics import metrics_collector

blueprint = Blueprint(
    'routes_monitoring',
    __name__,
    static_folder='../static',
    template_folder='../templates'
)


@blueprint.route('/health')
def health():
    """
    Health check endpoint for Kubernetes/Docker/monitoring systems.
    
    Returns:
        JSON response with health status and checks
        
    Status Codes:
        200: System is healthy
        503: System is unhealthy
    """
    health_status = health_checker.check_all()
    
    status_code = 200
    if health_status['status'] == 'unhealthy':
        status_code = 503
    
    return jsonify(health_status), status_code


@blueprint.route('/health/live')
def liveness():
    """
    Kubernetes liveness probe endpoint.
    
    Returns a simple OK if the application is running.
    
    Returns:
        JSON response indicating the app is alive
    """
    return jsonify({
        'status': 'alive',
        'uptime_seconds': health_checker.get_uptime()
    }), 200


@blueprint.route('/health/ready')
def readiness():
    """
    Kubernetes readiness probe endpoint.
    
    Checks if the application is ready to serve traffic.
    
    Returns:
        JSON response with readiness status
        
    Status Codes:
        200: Application is ready
        503: Application is not ready
    """
    # Check critical components only
    db_check = health_checker.check_database()
    
    if db_check['status'] == 'healthy':
        return jsonify({
            'status': 'ready',
            'message': 'Application is ready to serve traffic'
        }), 200
    else:
        return jsonify({
            'status': 'not_ready',
            'message': 'Application is not ready to serve traffic',
            'reason': db_check.get('message', 'Unknown')
        }), 503


@blueprint.route('/metrics')
def metrics():
    """
    Prometheus metrics endpoint.
    
    Returns metrics in Prometheus text format for scraping.
    
    Returns:
        Response with Prometheus metrics
    """
    metrics_data = metrics_collector.get_metrics()
    return Response(
        metrics_data,
        mimetype=metrics_collector.get_content_type()
    )
