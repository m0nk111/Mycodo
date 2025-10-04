# Mycodo Examples

This directory contains examples demonstrating various Mycodo features and patterns.

## Async/Await Examples

### async_sensor_example.py

Demonstrates the async/await architecture for sensor controllers.

**Features demonstrated:**
- Async initialization and lifecycle methods
- Concurrent sensor operations with `asyncio.gather()`
- Async retry logic for connection handling
- Timeout handling for sensor reads
- Health checks
- Proper resource cleanup

**Usage:**
```bash
python examples/async_sensor_example.py
```

**Expected output:**
The example creates two temperature sensors, initializes them concurrently, reads from them multiple times, checks their health, and cleanly shuts them down.

**Key takeaways:**
1. Multiple sensors can be initialized and read from concurrently
2. Async operations don't block each other
3. Proper error handling and logging throughout
4. Clean startup and shutdown procedures

## More Examples

Additional examples will be added here as new features are implemented.

## Contributing Examples

When contributing examples:
1. Keep them simple and focused on one feature
2. Include clear docstrings
3. Add error handling
4. Document expected output
5. Make them runnable standalone when possible
