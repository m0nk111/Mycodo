# Phase 2: Logging & Monitoring Infrastructure - Implementation Summary

## Overview

Phase 2 implements comprehensive logging and monitoring infrastructure for Mycodo using industry-standard tools:
- **Structured Logging:** `structlog` for JSON-formatted logs with context propagation
- **Metrics Collection:** `prometheus_client` for application and system metrics
- **Health Checks:** Kubernetes-compatible health endpoints
- **Log Aggregation:** Ready for integration with Loki, Elasticsearch, or other log aggregation systems

## What Was Implemented

### 1. Structured Logging System

**Files Created:**
- `mycodo/utils/logging_config.py` - Structured logging configuration and utilities

**Features:**
- JSON and console output formats
- Automatic context binding (request_id, user_id, etc.)
- Thread-safe context propagation
- Compatible with existing logging infrastructure

**Configuration:**
```bash
# Enable JSON logging (default: false for console output)
export MYCODO_JSON_LOGS=true

# Set log level (default: INFO)
export MYCODO_LOG_LEVEL=DEBUG
```

### 2. Prometheus Metrics Collection

**Files Created:**
- `mycodo/utils/metrics.py` - Prometheus metrics definitions and collector

**Metrics Exposed:**
- **HTTP Metrics:** Request counts, durations, status codes
- **Sensor Metrics:** Active sensors, readings, errors, current values
- **Output Metrics:** Active outputs, states, duration
- **Controller Metrics:** Active controllers by type
- **PID Metrics:** Setpoints, current values, outputs
- **System Metrics:** Uptime, database connections
- **Error Metrics:** Error counts by component and type

**Endpoint:** `/metrics` (Prometheus text format)

### 3. Health Check System

**Files Created:**
- `mycodo/utils/health.py` - Health check utilities
- `mycodo/mycodo_flask/routes_monitoring.py` - Health and metrics endpoints

**Endpoints:**

| Endpoint | Purpose | Use Case |
|----------|---------|----------|
| `/health` | Comprehensive health check | General monitoring |
| `/health/live` | Liveness probe | Kubernetes liveness |
| `/health/ready` | Readiness probe | Kubernetes readiness |
| `/metrics` | Prometheus metrics | Metrics scraping |

**Health Checks:**
- Database connectivity
- GPIO availability (on Raspberry Pi)
- Daemon status
- System uptime

### 4. Request Correlation

**Files Created:**
- `mycodo/mycodo_flask/middleware.py` - Flask middleware for logging and metrics

**Features:**
- Automatic request ID generation
- Request ID in logs and response headers (`X-Request-ID`)
- Request duration tracking
- Error tracking and metrics

### 5. Grafana Dashboards

**Files Created:**
- `docs/grafana_dashboards/system_metrics.json` - System-level dashboard
- `docs/grafana_dashboards/sensor_metrics.json` - Sensor monitoring dashboard
- `docs/grafana_dashboards/error_dashboard.json` - Error tracking dashboard

**Dashboard Features:**
- HTTP request metrics and latency
- Sensor readings and states
- Output states
- Error rates by component and type
- System uptime

### 6. Documentation

**Files Created:**
- `docs/monitoring_infrastructure.md` - Comprehensive monitoring documentation
- `docs/structured_logging_examples.md` - Code examples and migration guide

**Documentation Covers:**
- Configuration and setup
- Log aggregation with Loki/Elasticsearch
- Prometheus scraping configuration
- Kubernetes deployment
- Usage examples
- Migration strategy

## Integration Points

### Updated Files

1. **`install/requirements.txt`**
   - Added `structlog==24.1.0`
   - Added `prometheus_client==0.20.0`

2. **`mycodo/mycodo_flask/app.py`**
   - Integrated structured logging setup
   - Registered monitoring blueprint
   - Set up request middleware
   - Initialize metrics with app info

3. **`mycodo/mycodo_daemon.py`**
   - Added structured logging support
   - Maintained backward compatibility with existing logging

## Usage Examples

### Structured Logging

```python
from mycodo.utils.logging_config import get_logger, bind_context

logger = get_logger(__name__)

# Simple logging
logger.info("sensor_reading", sensor_id="DHT22_001", temperature=22.5)

# With context
bind_context(user_id="user123")
logger.warning("threshold_exceeded", value=35.0)
```

### Recording Metrics

```python
from mycodo.utils.metrics import metrics_collector

# Record sensor reading
metrics_collector.update_sensor_metrics(
    sensor_id="DHT22_001",
    sensor_name="Living Room",
    sensor_type="DHT22",
    measurement_type="temperature",
    unit="celsius",
    value=22.5
)
```

### Health Checks

```bash
# Check overall health
curl http://localhost:8080/health

# Liveness probe
curl http://localhost:8080/health/live

# Readiness probe
curl http://localhost:8080/health/ready
```

### Metrics

```bash
# Get Prometheus metrics
curl http://localhost:8080/metrics
```

## Deployment

### Docker

```dockerfile
ENV MYCODO_JSON_LOGS=true
ENV MYCODO_LOG_LEVEL=INFO
```

### Kubernetes

```yaml
apiVersion: v1
kind: Pod
spec:
  containers:
  - name: mycodo
    env:
    - name: MYCODO_JSON_LOGS
      value: "true"
    - name: MYCODO_LOG_LEVEL
      value: "INFO"
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

### Prometheus

```yaml
scrape_configs:
  - job_name: 'mycodo'
    static_configs:
      - targets: ['localhost:8080']
    metrics_path: /metrics
    scrape_interval: 15s
```

## Testing

### Manual Testing

1. **Start Mycodo** with structured logging:
   ```bash
   export MYCODO_JSON_LOGS=true
   python mycodo/mycodo_flask/app.py
   ```

2. **Test health endpoints:**
   ```bash
   curl http://localhost:8080/health | jq .
   curl http://localhost:8080/health/live
   curl http://localhost:8080/health/ready
   ```

3. **Test metrics endpoint:**
   ```bash
   curl http://localhost:8080/metrics
   ```

4. **Check logs** for JSON format:
   ```bash
   tail -f /var/log/mycodo/mycodo.log
   ```

### Automated Tests

Tests are located in `mycodo/tests/software_tests/test_mycodo_flask/test_monitoring.py`:
- Health endpoint tests
- Liveness probe tests
- Readiness probe tests
- Metrics endpoint tests

## Migration Strategy

### For Developers

1. **Gradual Migration:**
   - The system is backward compatible with existing logging
   - New code should use structured logging
   - Existing code can be migrated incrementally

2. **Priority Areas for Migration:**
   - Sensor controllers
   - Output controllers
   - PID controllers
   - Error handling in daemon
   - Critical Flask routes

3. **Keep print() statements in:**
   - CLI tools (mycodo_client.py)
   - User-facing scripts
   - Development/debug scripts

### For System Administrators

1. **Configuration:**
   - Set `MYCODO_JSON_LOGS=true` for production
   - Set `MYCODO_LOG_LEVEL=INFO` for production
   - Use `DEBUG` only for troubleshooting

2. **Log Aggregation:**
   - Configure Promtail or Filebeat for log collection
   - Set up appropriate log retention policies
   - Use provided Grafana dashboards

3. **Monitoring:**
   - Configure Prometheus to scrape metrics
   - Import Grafana dashboards
   - Set up alerts for critical metrics

## Success Criteria (from Issue)

- [x] All logs available in JSON format
- [x] Metrics exposed on /metrics endpoint
- [x] Grafana dashboards created and functional
- [x] Log correlation working (request IDs)
- [x] Documentation complete

## Benefits

1. **Improved Observability:**
   - Structured logs are easily searchable and parseable
   - Metrics provide real-time system insights
   - Health checks enable proactive monitoring

2. **Better Debugging:**
   - Request correlation via request IDs
   - Contextual information in every log entry
   - Stack traces in structured format

3. **Production Ready:**
   - Kubernetes-compatible health checks
   - Prometheus metrics for alerting
   - Integration with standard observability tools

4. **Scalability:**
   - Efficient log aggregation with Loki/Elasticsearch
   - Metrics-based horizontal pod autoscaling
   - Distributed tracing ready (via request IDs)

## Future Enhancements

1. **Distributed Tracing:**
   - Integrate OpenTelemetry for full distributed tracing
   - Add span context propagation

2. **Advanced Metrics:**
   - Add custom metrics for specific sensor types
   - Add business metrics (e.g., automation success rates)

3. **Log Sampling:**
   - Implement log sampling for high-volume logs
   - Add dynamic log level adjustment

4. **Alert Rules:**
   - Provide Prometheus alert rule templates
   - Add pre-configured alerts for common issues

## Support

For questions or issues:
1. Check the documentation in `docs/monitoring_infrastructure.md`
2. Review examples in `docs/structured_logging_examples.md`
3. Open an issue on GitHub with the `monitoring` label
