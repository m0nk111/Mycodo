# Async/Await Architecture in Mycodo

This document describes the async/await architecture implemented in Mycodo to improve concurrency and resource utilization.

## Overview

Mycodo now supports asynchronous programming patterns for core I/O operations. This allows controllers to perform non-blocking operations, improving system responsiveness and enabling efficient concurrent execution.

## Key Components

### 1. Async Base Controller Classes

#### AbstractBaseController

The `AbstractBaseController` class now includes async lifecycle methods:

```python
from mycodo.abstract_base_controller import AbstractBaseController

class MyController(AbstractBaseController):
    async def async_initialize(self):
        """Async initialization - called once at startup"""
        await super().async_initialize()
        # Your async initialization code here
        
    async def async_start(self):
        """Start the controller asynchronously"""
        await super().async_start()
        # Your async startup code here
        
    async def async_stop(self):
        """Stop the controller asynchronously"""
        await super().async_stop()
        # Your async cleanup code here
        
    async def async_health_check(self):
        """Check controller health status"""
        health = await super().async_health_check()
        # Add custom health checks
        return health
```

#### AbstractController

The `AbstractController` class provides an `async_run()` method that can use async versions of lifecycle methods:

```python
from mycodo.controllers.base_controller import AbstractController

class MyController(AbstractController):
    async def async_initialize_variables(self):
        """Async version of initialize_variables"""
        # Initialize variables asynchronously
        pass
        
    async def async_loop(self):
        """Async version of the main loop"""
        # Your async loop logic
        await asyncio.sleep(self.sample_rate)
        
    async def async_run_finally(self):
        """Async cleanup after loop completes"""
        # Cleanup code
        pass
```

### 2. Async Utility Functions

The `mycodo.utils.async_utils` module provides helpful async utilities:

#### Async Retry with Exponential Backoff

```python
from mycodo.utils.async_utils import async_retry

async def read_sensor():
    # Sensor reading logic
    return value

# Retry up to 3 times with exponential backoff
result = await async_retry(
    read_sensor,
    max_retries=3,
    initial_delay=1.0,
    backoff_factor=2.0,
    max_delay=60.0,
    exceptions=(IOError, TimeoutError)
)
```

#### Async Timeout Handling

```python
from mycodo.utils.async_utils import async_timeout

async def slow_operation():
    # Some potentially slow operation
    return result

# Execute with timeout
result = await async_timeout(
    slow_operation(),
    timeout_sec=5.0,
    timeout_result="default_value"  # Optional default on timeout
)
```

#### Event Loop Management

```python
from mycodo.utils.async_utils import AsyncEventLoopManager

# Get or create event loop
loop = AsyncEventLoopManager.get_or_create_event_loop()

# Run async function in sync context
result = AsyncEventLoopManager.run_async(my_async_func(), timeout=10.0)

# Create task if loop is running
task = AsyncEventLoopManager.create_task_if_loop_running(my_coroutine())
```

#### Run Sync Function in Executor

```python
from mycodo.utils.async_utils import run_in_executor

# Run blocking sync function without blocking event loop
result = await run_in_executor(blocking_function, arg1, arg2)
```

## Best Practices

### 1. Use Async for I/O Operations

Async/await is best suited for I/O-bound operations:
- Network requests (HTTP, MQTT)
- Database queries
- File I/O
- Sensor readings
- Serial communication

### 2. Avoid Blocking Calls

Never use blocking calls in async functions:

```python
# ❌ Bad - blocks event loop
async def bad_example():
    time.sleep(1)  # Blocking!
    
# ✓ Good - non-blocking
async def good_example():
    await asyncio.sleep(1)  # Non-blocking
```

### 3. Use run_in_executor for CPU-Bound Work

If you must perform CPU-intensive work in an async context:

```python
from mycodo.utils.async_utils import run_in_executor

async def process_data():
    # Run CPU-intensive work in thread pool
    result = await run_in_executor(heavy_computation, data)
    return result
```

### 4. Proper Error Handling

Always handle exceptions in async code:

```python
async def safe_operation():
    try:
        result = await risky_async_call()
        return result
    except Exception as e:
        self.logger.exception(f"Operation failed: {e}")
        return None
```

### 5. Use Async Context Managers

For resource management:

```python
class AsyncResource:
    async def __aenter__(self):
        # Setup
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        # Cleanup
        pass

async def use_resource():
    async with AsyncResource() as resource:
        await resource.do_something()
```

## Migration Guide

### Converting Sync Controllers to Async

1. **Add async lifecycle methods**:
   ```python
   # Before
   def initialize_variables(self):
       self.setup()
   
   # After
   async def async_initialize_variables(self):
       await self.async_setup()
   ```

2. **Update loop method**:
   ```python
   # Before
   def loop(self):
       data = self.read_sensor()
       self.process(data)
   
   # After
   async def async_loop(self):
       data = await self.async_read_sensor()
       await self.async_process(data)
   ```

3. **Use async_run instead of run**:
   ```python
   # Run the async version
   await controller.async_run()
   ```

### Backward Compatibility

The async methods are **optional** and work alongside existing sync methods:
- If async methods exist, `async_run()` will use them
- If only sync methods exist, `async_run()` will fall back to sync versions
- Existing controllers continue to work without changes

## Testing Async Code

Use `pytest-asyncio` for testing:

```python
import pytest

pytestmark = pytest.mark.asyncio

class TestAsyncController:
    async def test_async_operation(self):
        controller = MyController()
        await controller.async_initialize()
        
        result = await controller.async_operation()
        
        assert result is not None
```

## Dependencies

The async functionality requires these packages (already in requirements.txt):
- `aiohttp>=3.9.1` - Async HTTP client
- `aiomqtt>=2.0.1` - Async MQTT client
- `aiosqlite>=0.19.0` - Async SQLite support
- `pytest-asyncio>=0.21.1` - For async testing

## Performance Considerations

### Benefits
- Non-blocking I/O operations
- Better concurrency for multiple sensors/controllers
- Reduced CPU usage during I/O waits
- More responsive system

### Trade-offs
- Slightly more complex code
- Learning curve for async patterns
- Not beneficial for CPU-bound operations

## Examples

### Async Sensor Reading with Retry

```python
from mycodo.abstract_base_controller import AbstractBaseController
from mycodo.utils.async_utils import async_retry, async_timeout

class AsyncSensor(AbstractBaseController):
    async def async_initialize(self):
        await super().async_initialize()
        # Initialize sensor connection
        
    async def read_with_retry(self):
        """Read sensor with automatic retry on failure"""
        return await async_retry(
            self._read_sensor,
            max_retries=3,
            initial_delay=1.0,
            exceptions=(IOError,)
        )
    
    async def _read_sensor(self):
        """Internal sensor read with timeout"""
        return await async_timeout(
            self._do_read(),
            timeout_sec=5.0
        )
    
    async def _do_read(self):
        # Actual sensor reading logic
        await asyncio.sleep(0.1)  # Simulate I/O
        return 25.5
```

### Async HTTP Request

```python
import aiohttp
from mycodo.utils.async_utils import async_retry

async def fetch_data(url):
    """Fetch data from URL with retry"""
    async def _fetch():
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                return await response.json()
    
    return await async_retry(
        _fetch,
        max_retries=3,
        exceptions=(aiohttp.ClientError,)
    )
```

## Future Enhancements

Planned improvements for async functionality:
- Async database connection pooling
- Async MQTT message handling
- Async event bus for inter-controller communication
- Async plugin system
- Performance monitoring and metrics

## Support

For questions or issues with async functionality:
1. Check this documentation
2. Review test files in `mycodo/tests/software_tests/test_async_*.py`
3. Open an issue on GitHub with the `async` label
