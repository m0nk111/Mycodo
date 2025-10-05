# Example: Integrating Structured Logging into Sensor Controllers

This document provides examples of how to integrate structured logging into Mycodo sensor controllers.

## Basic Usage in a Sensor Controller

```python
# Import structured logging
from mycodo.utils.logging_config import get_logger, bind_context

class MySensorController:
    def __init__(self, sensor_id):
        # Get a logger for this module
        self.logger = get_logger(__name__)
        self.sensor_id = sensor_id
        
        # Bind context that will be included in all logs from this controller
        bind_context(
            sensor_id=sensor_id,
            controller_type='sensor'
        )
        
        self.logger.info("sensor_controller_initialized")
    
    def read_sensor(self):
        """Read sensor value with structured logging."""
        try:
            # Simulate reading sensor
            value = self.get_temperature()
            
            # Log the reading with structured data
            self.logger.info(
                "sensor_reading_success",
                measurement_type="temperature",
                value=value,
                unit="celsius"
            )
            
            return value
            
        except Exception as e:
            # Log errors with full context
            self.logger.error(
                "sensor_reading_failed",
                error_type=type(e).__name__,
                error_message=str(e),
                exc_info=True  # Include stack trace
            )
            raise
```

## Using with Prometheus Metrics

```python
from mycodo.utils.logging_config import get_logger
from mycodo.utils.metrics import metrics_collector

class MySensorController:
    def __init__(self, sensor_id, sensor_name, sensor_type):
        self.logger = get_logger(__name__)
        self.sensor_id = sensor_id
        self.sensor_name = sensor_name
        self.sensor_type = sensor_type
    
    def read_sensor(self):
        """Read sensor and update both logs and metrics."""
        try:
            value = self.get_temperature()
            
            # Log the reading
            self.logger.info(
                "sensor_reading",
                sensor_id=self.sensor_id,
                sensor_type=self.sensor_type,
                value=value
            )
            
            # Update Prometheus metrics
            metrics_collector.update_sensor_metrics(
                sensor_id=self.sensor_id,
                sensor_name=self.sensor_name,
                sensor_type=self.sensor_type,
                measurement_type="temperature",
                unit="celsius",
                value=value
            )
            
            return value
            
        except Exception as e:
            # Log error
            self.logger.error(
                "sensor_reading_error",
                sensor_id=self.sensor_id,
                error=str(e),
                exc_info=True
            )
            
            # Record error metric
            metrics_collector.record_sensor_error(
                sensor_type=self.sensor_type
            )
            
            metrics_collector.record_error(
                component='sensor_controller',
                error_type=type(e).__name__
            )
            
            raise
```

## State Change Logging

```python
from mycodo.utils.logging_config import get_logger

class OutputController:
    def __init__(self, output_id, output_name):
        self.logger = get_logger(__name__)
        self.output_id = output_id
        self.output_name = output_name
        self.state = False
    
    def turn_on(self):
        """Turn on output with state change logging."""
        previous_state = self.state
        
        # Perform the action
        self.state = True
        
        # Log the state change
        self.logger.info(
            "output_state_changed",
            output_id=self.output_id,
            output_name=self.output_name,
            previous_state=previous_state,
            new_state=self.state,
            action="turn_on"
        )
        
        # Update metrics
        from mycodo.utils.metrics import metrics_collector
        metrics_collector.update_output_state(
            output_id=self.output_id,
            output_name=self.output_name,
            state=self.state
        )
```

## PID Controller Logging

```python
from mycodo.utils.logging_config import get_logger

class PIDController:
    def __init__(self, pid_id, pid_name):
        self.logger = get_logger(__name__)
        self.pid_id = pid_id
        self.pid_name = pid_name
    
    def calculate_output(self, setpoint, current_value):
        """Calculate PID output with logging."""
        # Calculate PID values
        error = setpoint - current_value
        output = self.calculate_pid(error)
        
        # Log PID calculation
        self.logger.debug(
            "pid_calculation",
            pid_id=self.pid_id,
            pid_name=self.pid_name,
            setpoint=setpoint,
            current_value=current_value,
            error=error,
            output=output
        )
        
        return output
```

## Request Context in Flask Routes

The middleware automatically adds request context to all logs during HTTP requests:

```python
from flask import Blueprint
from mycodo.utils.logging_config import get_logger

blueprint = Blueprint('my_routes', __name__)
logger = get_logger(__name__)

@blueprint.route('/sensor/<sensor_id>/read')
def read_sensor(sensor_id):
    # Request ID is automatically included in all logs
    logger.info("reading_sensor_via_api", sensor_id=sensor_id)
    
    # Additional context can be added
    from mycodo.utils.logging_config import bind_context
    bind_context(sensor_id=sensor_id)
    
    # All subsequent logs in this request will include sensor_id
    logger.debug("performing_sensor_read")
    
    # ... perform sensor read ...
    
    logger.info("sensor_read_completed", value=22.5)
    
    return {"value": 22.5}
```

## Example Log Output

When `MYCODO_JSON_LOGS=true`, logs will look like:

```json
{
  "timestamp": "2024-01-15T10:30:45.123456Z",
  "level": "info",
  "logger": "mycodo.controllers.sensor",
  "event": "sensor_reading_success",
  "app": "mycodo",
  "sensor_id": "DHT22_001",
  "controller_type": "sensor",
  "measurement_type": "temperature",
  "value": 22.5,
  "unit": "celsius"
}
```

With console output (`MYCODO_JSON_LOGS=false`):

```
2024-01-15T10:30:45.123456Z [info     ] sensor_reading_success         app=mycodo controller_type=sensor measurement_type=temperature sensor_id=DHT22_001 unit=celsius value=22.5
```

## Migration Strategy

To migrate existing logging code:

1. **Replace simple logs:**
   ```python
   # Old
   logger.info(f"Sensor {sensor_id} reading: {value}")
   
   # New
   logger.info("sensor_reading", sensor_id=sensor_id, value=value)
   ```

2. **Replace error logs:**
   ```python
   # Old
   logger.error(f"Error reading sensor: {str(e)}")
   
   # New
   logger.error("sensor_reading_error", error=str(e), exc_info=True)
   ```

3. **Add structured context:**
   ```python
   # Old
   logger.info(f"Processing sensor {sensor_id}")
   
   # New
   from mycodo.utils.logging_config import bind_context
   bind_context(sensor_id=sensor_id)
   logger.info("processing_sensor")
   ```

4. **Keep print() for CLI tools:**
   - CLI scripts (mycodo_client.py) can keep print() statements for user output
   - Only replace print() in daemon, controllers, and web application code

## Best Practices

1. **Use event names as the first parameter:** `logger.info("event_name", key=value)`
2. **Include relevant context:** sensor_id, user_id, output_id, etc.
3. **Use consistent naming:** snake_case for event names and keys
4. **Don't include sensitive data:** passwords, API keys, etc.
5. **Use appropriate log levels:**
   - DEBUG: Detailed information for debugging
   - INFO: General informational messages
   - WARNING: Warning messages for potentially harmful situations
   - ERROR: Error messages for failed operations
   - CRITICAL: Critical errors that may cause system failure
