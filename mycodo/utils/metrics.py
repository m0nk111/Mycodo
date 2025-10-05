# coding=utf-8
"""
Prometheus metrics collection for Mycodo.

This module provides metrics collection using prometheus_client for
monitoring application performance and state.
"""
import time
from typing import Optional

from prometheus_client import Counter, Gauge, Histogram, Info
from prometheus_client import REGISTRY, CollectorRegistry
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST


# Create a custom registry for Mycodo metrics
mycodo_registry = CollectorRegistry()

# Application info
mycodo_info = Info(
    'mycodo_application',
    'Mycodo application information',
    registry=mycodo_registry
)

# HTTP request metrics
http_requests_total = Counter(
    'mycodo_http_requests_total',
    'Total HTTP requests',
    ['method', 'endpoint', 'status'],
    registry=mycodo_registry
)

http_request_duration_seconds = Histogram(
    'mycodo_http_request_duration_seconds',
    'HTTP request latency',
    ['method', 'endpoint'],
    registry=mycodo_registry
)

# Error metrics
errors_total = Counter(
    'mycodo_errors_total',
    'Total errors',
    ['component', 'error_type'],
    registry=mycodo_registry
)

# Sensor metrics
active_sensors = Gauge(
    'mycodo_active_sensors',
    'Number of active sensors',
    registry=mycodo_registry
)

sensor_readings_total = Counter(
    'mycodo_sensor_readings_total',
    'Total sensor readings',
    ['sensor_type'],
    registry=mycodo_registry
)

sensor_reading_errors_total = Counter(
    'mycodo_sensor_reading_errors_total',
    'Total sensor reading errors',
    ['sensor_type'],
    registry=mycodo_registry
)

sensor_value = Gauge(
    'mycodo_sensor_value',
    'Current sensor value',
    ['sensor_id', 'sensor_name', 'measurement_type', 'unit'],
    registry=mycodo_registry
)

# Output metrics
active_outputs = Gauge(
    'mycodo_active_outputs',
    'Number of active outputs',
    registry=mycodo_registry
)

output_state = Gauge(
    'mycodo_output_state',
    'Output state (0=off, 1=on)',
    ['output_id', 'output_name'],
    registry=mycodo_registry
)

output_duration_seconds_total = Counter(
    'mycodo_output_duration_seconds_total',
    'Total output on time in seconds',
    ['output_id', 'output_name'],
    registry=mycodo_registry
)

# Controller metrics
active_controllers = Gauge(
    'mycodo_active_controllers',
    'Number of active controllers',
    ['controller_type'],
    registry=mycodo_registry
)

# PID metrics
pid_setpoint = Gauge(
    'mycodo_pid_setpoint',
    'PID controller setpoint',
    ['pid_id', 'pid_name'],
    registry=mycodo_registry
)

pid_current_value = Gauge(
    'mycodo_pid_current_value',
    'PID controller current value',
    ['pid_id', 'pid_name'],
    registry=mycodo_registry
)

pid_output = Gauge(
    'mycodo_pid_output',
    'PID controller output',
    ['pid_id', 'pid_name'],
    registry=mycodo_registry
)

# Database metrics
database_connections = Gauge(
    'mycodo_database_connections',
    'Number of database connections',
    registry=mycodo_registry
)

database_query_duration_seconds = Histogram(
    'mycodo_database_query_duration_seconds',
    'Database query duration',
    ['query_type'],
    registry=mycodo_registry
)

# System metrics
system_uptime_seconds = Gauge(
    'mycodo_system_uptime_seconds',
    'System uptime in seconds',
    registry=mycodo_registry
)

daemon_uptime_seconds = Gauge(
    'mycodo_daemon_uptime_seconds',
    'Daemon uptime in seconds',
    registry=mycodo_registry
)


class MetricsCollector:
    """Utility class for collecting and updating metrics."""
    
    def __init__(self):
        """Initialize the metrics collector."""
        self.start_time = time.time()
    
    def set_application_info(self, version: str, python_version: str):
        """
        Set application information metrics.
        
        Args:
            version: Mycodo version
            python_version: Python version
        """
        mycodo_info.info({
            'version': version,
            'python_version': python_version
        })
    
    def record_http_request(
        self,
        method: str,
        endpoint: str,
        status: int,
        duration: float
    ):
        """
        Record an HTTP request.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: The endpoint path
            status: HTTP status code
            duration: Request duration in seconds
        """
        http_requests_total.labels(
            method=method,
            endpoint=endpoint,
            status=str(status)
        ).inc()
        
        http_request_duration_seconds.labels(
            method=method,
            endpoint=endpoint
        ).observe(duration)
    
    def record_error(self, component: str, error_type: str):
        """
        Record an error occurrence.
        
        Args:
            component: The component where the error occurred
            error_type: The type of error
        """
        errors_total.labels(
            component=component,
            error_type=error_type
        ).inc()
    
    def update_sensor_metrics(
        self,
        sensor_id: str,
        sensor_name: str,
        sensor_type: str,
        measurement_type: str,
        unit: str,
        value: float
    ):
        """
        Update sensor metrics.
        
        Args:
            sensor_id: Unique sensor identifier
            sensor_name: Human-readable sensor name
            sensor_type: Type of sensor
            measurement_type: Type of measurement
            unit: Unit of measurement
            value: The measured value
        """
        sensor_readings_total.labels(sensor_type=sensor_type).inc()
        sensor_value.labels(
            sensor_id=sensor_id,
            sensor_name=sensor_name,
            measurement_type=measurement_type,
            unit=unit
        ).set(value)
    
    def record_sensor_error(self, sensor_type: str):
        """
        Record a sensor reading error.
        
        Args:
            sensor_type: Type of sensor that had an error
        """
        sensor_reading_errors_total.labels(sensor_type=sensor_type).inc()
    
    def update_output_state(self, output_id: str, output_name: str, state: bool):
        """
        Update output state metric.
        
        Args:
            output_id: Unique output identifier
            output_name: Human-readable output name
            state: Output state (True=on, False=off)
        """
        output_state.labels(
            output_id=output_id,
            output_name=output_name
        ).set(1 if state else 0)
    
    def update_system_uptime(self):
        """Update system uptime metric."""
        system_uptime_seconds.set(time.time() - self.start_time)
    
    def get_metrics(self) -> bytes:
        """
        Get current metrics in Prometheus format.
        
        Returns:
            Metrics data in Prometheus text format
        """
        return generate_latest(mycodo_registry)
    
    def get_content_type(self) -> str:
        """
        Get the content type for metrics endpoint.
        
        Returns:
            The content type string
        """
        return CONTENT_TYPE_LATEST


# Global metrics collector instance
metrics_collector = MetricsCollector()
