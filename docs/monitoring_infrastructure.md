# Phase 2: Logging & Monitoring Infrastructure

## Overview

Mycodo now includes comprehensive logging and monitoring infrastructure using structured logging with `structlog` and metrics collection with Prometheus.

## Features

### Structured Logging

All logs are now available in structured JSON format for easy parsing and aggregation.

#### Configuration

Structured logging is configured via environment variables:

- `MYCODO_JSON_LOGS`: Set to `true` to enable JSON output (default: `false` for console output)
- `MYCODO_LOG_LEVEL`: Set log level (DEBUG, INFO, WARNING, ERROR, CRITICAL) (default: INFO)

Example:
```bash
export MYCODO_JSON_LOGS=true
export MYCODO_LOG_LEVEL=INFO
```

#### Log Format

JSON logs include:
- `timestamp`: ISO 8601 timestamp
- `level`: Log level (debug, info, warning, error, critical)
- `logger`: Logger name
- `event`: Event description
- `app`: Application name (mycodo)
- Additional context fields (request_id, user_id, etc.)

Example JSON log entry:
```json
{
  "timestamp": "2024-01-01T12:00:00.000000Z",
  "level": "info",
  "logger": "mycodo.daemon",
  "event": "sensor_reading",
  "app": "mycodo",
  "request_id": "abc123",
  "sensor_id": "sensor_001",
  "sensor_type": "DHT22",
  "value": 22.5,
  "unit": "celsius"
}
```

### Request Correlation

All Flask HTTP requests automatically include correlation IDs for tracing:
- Each request generates a unique `request_id`
- Request ID is available in logs for that request
- Request ID is included in response headers as `X-Request-ID`

### Health Checks

Three health check endpoints are available:

#### `/health`
Comprehensive health check for all system components.

Response (200 OK):
```json
{
  "status": "healthy",
  "uptime_seconds": 12345.67,
  "checks": {
    "database": {
      "status": "healthy",
      "message": "Database connection successful"
    },
    "gpio": {
      "status": "healthy",
      "message": "GPIO available"
    },
    "daemon": {
      "status": "healthy",
      "message": "Daemon is running"
    }
  }
}
```

Status codes:
- `200`: System is healthy
- `503`: System is unhealthy

#### `/health/live`
Kubernetes liveness probe - checks if the application is running.

Response (200 OK):
```json
{
  "status": "alive",
  "uptime_seconds": 12345.67
}
```

#### `/health/ready`
Kubernetes readiness probe - checks if the application is ready to serve traffic.

Response (200 OK):
```json
{
  "status": "ready",
  "message": "Application is ready to serve traffic"
}
```

Status codes:
- `200`: Application is ready
- `503`: Application is not ready

### Prometheus Metrics

Metrics are exposed at `/metrics` in Prometheus text format.

#### Available Metrics

**Application Info:**
- `mycodo_application_info`: Application version and Python version

**HTTP Metrics:**
- `mycodo_http_requests_total`: Total HTTP requests (by method, endpoint, status)
- `mycodo_http_request_duration_seconds`: HTTP request latency histogram

**Error Metrics:**
- `mycodo_errors_total`: Total errors (by component, error type)

**Sensor Metrics:**
- `mycodo_active_sensors`: Number of active sensors
- `mycodo_sensor_readings_total`: Total sensor readings (by type)
- `mycodo_sensor_reading_errors_total`: Total sensor reading errors (by type)
- `mycodo_sensor_value`: Current sensor value (by sensor_id, type, unit)

**Output Metrics:**
- `mycodo_active_outputs`: Number of active outputs
- `mycodo_output_state`: Output state (0=off, 1=on)
- `mycodo_output_duration_seconds_total`: Total output on time

**Controller Metrics:**
- `mycodo_active_controllers`: Number of active controllers (by type)
- `mycodo_pid_setpoint`: PID controller setpoint
- `mycodo_pid_current_value`: PID controller current value
- `mycodo_pid_output`: PID controller output

**System Metrics:**
- `mycodo_system_uptime_seconds`: System uptime
- `mycodo_daemon_uptime_seconds`: Daemon uptime
- `mycodo_database_connections`: Number of database connections

## Integration

### Log Aggregation with Loki

To integrate with Grafana Loki for log aggregation:

1. Install Promtail on your Mycodo system
2. Configure Promtail to scrape JSON logs:

```yaml
# promtail-config.yaml
server:
  http_listen_port: 9080
  grpc_listen_port: 0

positions:
  filename: /tmp/positions.yaml

clients:
  - url: http://loki:3100/loki/api/v1/push

scrape_configs:
  - job_name: mycodo
    static_configs:
      - targets:
          - localhost
        labels:
          job: mycodo
          __path__: /var/log/mycodo/*.log
    pipeline_stages:
      - json:
          expressions:
            timestamp: timestamp
            level: level
            logger: logger
            event: event
      - labels:
          level:
          logger:
      - timestamp:
          source: timestamp
          format: RFC3339Nano
```

3. Start Promtail:
```bash
promtail -config.file=promtail-config.yaml
```

### Log Aggregation with Elasticsearch

To integrate with Elasticsearch:

1. Install Filebeat on your Mycodo system
2. Configure Filebeat to parse JSON logs:

```yaml
# filebeat.yml
filebeat.inputs:
  - type: log
    enabled: true
    paths:
      - /var/log/mycodo/*.log
    json.keys_under_root: true
    json.add_error_key: true

output.elasticsearch:
  hosts: ["localhost:9200"]
  index: "mycodo-%{+yyyy.MM.dd}"

setup.template.name: "mycodo"
setup.template.pattern: "mycodo-*"
```

3. Start Filebeat:
```bash
filebeat -c filebeat.yml
```

### Prometheus Scraping

To scrape metrics with Prometheus:

1. Add Mycodo to your Prometheus configuration:

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'mycodo'
    static_configs:
      - targets: ['localhost:8080']
    metrics_path: /metrics
    scrape_interval: 15s
```

2. Reload Prometheus configuration

### Kubernetes Deployment

For Kubernetes deployments, configure liveness and readiness probes:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: mycodo
spec:
  containers:
  - name: mycodo
    image: mycodo:latest
    ports:
    - containerPort: 8080
    livenessProbe:
      httpGet:
        path: /health/live
        port: 8080
      initialDelaySeconds: 30
      periodSeconds: 10
    readinessProbe:
      httpGet:
        path: /health/ready
        port: 8080
      initialDelaySeconds: 5
      periodSeconds: 5
```

## Grafana Dashboards

Dashboard templates are available in the `docs/grafana_dashboards/` directory:

- `system_metrics.json`: System-level metrics (CPU, memory, uptime)
- `sensor_metrics.json`: Sensor readings and health
- `error_dashboard.json`: Error rates and types

### Importing Dashboards

1. Open Grafana
2. Navigate to Dashboards → Import
3. Upload the JSON file or paste its contents
4. Select your Prometheus data source
5. Click Import

## Log Retention

Configure log retention based on your needs:

**For file-based logs:**
- Use logrotate to manage log files
- Example configuration in `/etc/logrotate.d/mycodo`:

```
/var/log/mycodo/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
}
```

**For Loki:**
- Configure retention in Loki settings:
```yaml
# loki-config.yaml
limits_config:
  retention_period: 168h  # 7 days
```

**For Elasticsearch:**
- Use Index Lifecycle Management (ILM) policies
- Configure retention in Kibana

## Usage Examples

### Using Structured Logging in Code

```python
from mycodo.utils.logging_config import get_logger, bind_context

logger = get_logger(__name__)

# Simple logging
logger.info("sensor_reading", sensor_id="DHT22_001", temperature=22.5, humidity=65.0)

# With context
bind_context(user_id="user123")
logger.warning("threshold_exceeded", sensor_id="DHT22_001", value=35.0, threshold=30.0)
```

### Recording Custom Metrics

```python
from mycodo.utils.metrics import metrics_collector

# Record sensor reading
metrics_collector.update_sensor_metrics(
    sensor_id="DHT22_001",
    sensor_name="Living Room Temp",
    sensor_type="DHT22",
    measurement_type="temperature",
    unit="celsius",
    value=22.5
)

# Record error
metrics_collector.record_error(
    component="sensor_controller",
    error_type="TimeoutError"
)
```

## Troubleshooting

### Logs Not Appearing in JSON Format

Check environment variables:
```bash
echo $MYCODO_JSON_LOGS
# Should output: true
```

### Metrics Endpoint Not Accessible

1. Check that the Flask application is running
2. Verify the endpoint exists:
```bash
curl http://localhost:8080/metrics
```

### Health Check Failing

Check individual component status:
```bash
curl http://localhost:8080/health | jq .
```

Review the `checks` object to identify which component is unhealthy.

## References

- [Structlog Documentation](https://www.structlog.org/)
- [Prometheus Client Python](https://github.com/prometheus/client_python)
- [Grafana Loki](https://grafana.com/oss/loki/)
- [Prometheus](https://prometheus.io/)
