#!/usr/bin/env python
# coding=utf-8
"""
Example: Async Sensor Controller

This example demonstrates how to create an async sensor controller using
the new async/await architecture in Mycodo.

This is a simplified standalone example that demonstrates the async patterns
without requiring the full Mycodo installation.

Usage:
    python examples/async_sensor_example.py

Note: This example uses simplified versions of the async utilities for demonstration.
      In production, import from mycodo.utils.async_utils instead.
"""
import asyncio
import logging
import random

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


# Simplified async utilities for demonstration
async def async_retry(func, *args, max_retries=3, initial_delay=1.0, **kwargs):
    """Simplified retry function for demonstration."""
    for attempt in range(max_retries):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            if attempt < max_retries - 1:
                await asyncio.sleep(initial_delay)
            else:
                raise


async def async_timeout(coro, timeout_sec, timeout_result=None):
    """Simplified timeout function for demonstration."""
    try:
        return await asyncio.wait_for(coro, timeout=timeout_sec)
    except asyncio.TimeoutError:
        if timeout_result is not None:
            return timeout_result
        raise


class AsyncTemperatureSensor:
    """Example async temperature sensor controller."""

    def __init__(self, sensor_id="temp-001"):
        self.sensor_id = sensor_id
        self.reading_count = 0
        self.is_connected = False
        self.logger = logging.getLogger(f"sensor-{sensor_id}")
        self._is_async_initialized = False

    async def async_initialize(self):
        """Initialize the sensor connection."""
        self.logger.info(f"Initializing sensor {self.sensor_id}...")
        
        # Simulate connection with retry
        try:
            await async_retry(
                self._connect_sensor,
                max_retries=3,
                initial_delay=0.5
            )
            self.is_connected = True
            self.logger.info(f"Sensor {self.sensor_id} initialized successfully")
            self._is_async_initialized = True
        except Exception as e:
            self.logger.error(f"Failed to initialize sensor: {e}")
            raise

    async def _connect_sensor(self):
        """Simulate sensor connection."""
        await asyncio.sleep(0.1)
        # Simulate successful connection
        self.logger.debug("Sensor connected")

    async def async_start(self):
        """Start the sensor."""
        if not self._is_async_initialized:
            await self.async_initialize()
        self.logger.info(f"Starting sensor {self.sensor_id}")

    async def read_temperature(self):
        """Read temperature with timeout and retry."""
        if not self.is_connected:
            raise RuntimeError("Sensor not connected")

        try:
            # Read with timeout
            temperature = await async_timeout(
                self._do_read_temperature(),
                timeout_sec=2.0,
                timeout_result=None
            )
            
            if temperature is None:
                self.logger.warning("Temperature read timed out")
                return None
            
            self.reading_count += 1
            self.logger.info(f"Read #{self.reading_count}: {temperature:.2f}°C")
            return temperature
            
        except Exception as e:
            self.logger.error(f"Error reading temperature: {e}")
            return None

    async def _do_read_temperature(self):
        """Simulate reading temperature from sensor."""
        # Simulate I/O delay
        await asyncio.sleep(0.1)
        # Return simulated temperature reading
        return 20.0 + random.uniform(-5, 5)

    async def async_health_check(self):
        """Check sensor health."""
        return {
            'healthy': self.is_connected,
            'message': 'Sensor is running' if self.is_connected else 'Sensor not connected',
            'sensor_id': self.sensor_id,
            'connected': self.is_connected,
            'reading_count': self.reading_count
        }

    async def async_stop(self):
        """Stop the sensor."""
        self.logger.info(f"Stopping sensor {self.sensor_id}")
        self.is_connected = False


async def run_sensor_example():
    """Run the async sensor example."""
    print("=" * 60)
    print("Mycodo Async Sensor Example")
    print("=" * 60)
    print()

    # Create two sensors
    sensor1 = AsyncTemperatureSensor("sensor-001")
    sensor2 = AsyncTemperatureSensor("sensor-002")

    try:
        # Initialize both sensors concurrently
        print("Initializing sensors...")
        await asyncio.gather(
            sensor1.async_initialize(),
            sensor2.async_initialize()
        )
        print()

        # Start sensors
        print("Starting sensors...")
        await asyncio.gather(
            sensor1.async_start(),
            sensor2.async_start()
        )
        print()

        # Read from sensors multiple times
        print("Reading from sensors (5 iterations)...")
        for i in range(5):
            print(f"\nIteration {i + 1}:")
            # Read from both sensors concurrently
            results = await asyncio.gather(
                sensor1.read_temperature(),
                sensor2.read_temperature()
            )
            await asyncio.sleep(0.5)  # Wait between readings

        print()

        # Check health of both sensors
        print("Checking sensor health...")
        health1, health2 = await asyncio.gather(
            sensor1.async_health_check(),
            sensor2.async_health_check()
        )
        
        print(f"\nSensor 1 Health: {health1}")
        print(f"Sensor 2 Health: {health2}")
        print()

    finally:
        # Stop sensors
        print("Stopping sensors...")
        await asyncio.gather(
            sensor1.async_stop(),
            sensor2.async_stop()
        )
        print()

    print("=" * 60)
    print("Example completed successfully!")
    print("=" * 60)


def main():
    """Main entry point."""
    try:
        # Run the async example
        asyncio.run(run_sensor_example())
    except KeyboardInterrupt:
        print("\nExample interrupted by user")
    except Exception as e:
        print(f"\nError running example: {e}")
        raise


if __name__ == "__main__":
    main()
