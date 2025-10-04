# coding=utf-8
"""Tests for async controller base classes."""
import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from testfixtures import LogCapture

from mycodo.abstract_base_controller import AbstractBaseController
from mycodo.controllers.base_controller import AbstractController


# Configure pytest to handle async tests
pytestmark = pytest.mark.asyncio


class TestAbstractBaseControllerAsync:
    """Tests for async methods in AbstractBaseController."""

    async def test_async_initialize(self):
        """Test async initialization."""
        controller = AbstractBaseController(unique_id="test-123", testing=True)
        
        await controller.async_initialize()
        
        assert controller._is_async_initialized is True

    async def test_async_start_calls_initialize(self):
        """Test async_start calls async_initialize if not initialized."""
        controller = AbstractBaseController(unique_id="test-456", testing=True)
        
        assert controller._is_async_initialized is False
        await controller.async_start()
        assert controller._is_async_initialized is True

    async def test_async_start_skips_if_initialized(self):
        """Test async_start skips initialization if already done."""
        controller = AbstractBaseController(unique_id="test-789", testing=True)
        
        await controller.async_initialize()
        initial_value = controller._is_async_initialized
        
        await controller.async_start()
        
        assert controller._is_async_initialized == initial_value

    async def test_async_stop(self):
        """Test async_stop executes without error."""
        controller = AbstractBaseController(unique_id="test-stop", testing=True)
        
        # Should not raise any exception
        await controller.async_stop()

    async def test_async_health_check(self):
        """Test async health check returns expected format."""
        controller = AbstractBaseController(unique_id="test-health", testing=True)
        
        health = await controller.async_health_check()
        
        assert isinstance(health, dict)
        assert 'healthy' in health
        assert 'message' in health
        assert health['healthy'] is True

    async def test_async_try_initialize_success_first_attempt(self):
        """Test async_try_initialize succeeds on first attempt."""
        controller = AbstractBaseController(unique_id="test-retry", testing=True)
        
        # Should succeed without error
        await controller.async_try_initialize(tries=3, wait_sec=0.01)
        
        assert controller._is_async_initialized is True

    async def test_async_try_initialize_with_retries(self):
        """Test async_try_initialize retries on failure."""
        controller = AbstractBaseController(unique_id="test-retry-fail", testing=True)
        
        # Mock async_initialize to fail twice then succeed
        original_init = controller.async_initialize
        call_count = [0]
        
        async def failing_init():
            call_count[0] += 1
            if call_count[0] < 3:
                raise ValueError("Initialization failed")
            await original_init()
        
        controller.async_initialize = failing_init
        
        with LogCapture() as log_cap:
            await controller.async_try_initialize(tries=3, wait_sec=0.01)
        
        assert call_count[0] == 3
        assert controller._is_async_initialized is True

    async def test_async_try_initialize_max_retries_exceeded(self):
        """Test async_try_initialize gives up after max retries."""
        controller = AbstractBaseController(unique_id="test-max-retry", testing=True)
        
        async def always_fail():
            raise ValueError("Always fails")
        
        controller.async_initialize = always_fail
        
        with LogCapture() as log_cap:
            await controller.async_try_initialize(tries=2, wait_sec=0.01)
        
        # Should have logged errors
        assert any('Error initializing' in str(record) for record in log_cap.records)


class TestAbstractControllerAsync:
    """Tests for async methods in AbstractController."""

    async def test_async_run_with_async_methods(self):
        """Test async_run uses async methods when available."""
        ready = MagicMock()
        
        class TestController(AbstractController):
            def __init__(self):
                super().__init__(ready, unique_id="test-async-run", name="TestController")
                self.initialize_called = False
                self.loop_called = False
                self.finally_called = False
                self.running = True
                self.loop_count = 0
            
            async def async_initialize_variables(self):
                self.initialize_called = True
            
            async def async_loop(self):
                self.loop_called = True
                self.loop_count += 1
                if self.loop_count >= 2:
                    self.running = False
            
            async def async_run_finally(self):
                self.finally_called = True
        
        controller = TestController()
        
        await controller.async_run()
        
        assert controller.initialize_called is True
        assert controller.loop_called is True
        assert controller.finally_called is True
        assert controller.loop_count == 2

    async def test_async_run_fallback_to_sync(self):
        """Test async_run falls back to sync methods when async not available."""
        ready = MagicMock()
        
        class TestController(AbstractController):
            def __init__(self):
                super().__init__(ready, unique_id="test-sync-fallback", name="TestController")
                self.initialize_called = False
                self.loop_called = False
                self.finally_called = False
                self.running = True
                self.loop_count = 0
            
            def initialize_variables(self):
                self.initialize_called = True
            
            def loop(self):
                self.loop_called = True
                self.loop_count += 1
                if self.loop_count >= 2:
                    self.running = False
            
            def run_finally(self):
                self.finally_called = True
        
        controller = TestController()
        
        await controller.async_run()
        
        assert controller.initialize_called is True
        assert controller.loop_called is True
        assert controller.finally_called is True

    async def test_async_run_handles_exceptions(self):
        """Test async_run handles exceptions gracefully."""
        ready = MagicMock()
        
        class TestController(AbstractController):
            def __init__(self):
                super().__init__(ready, unique_id="test-exception", name="TestController")
                self.running = True
                self.loop_count = 0
            
            async def async_initialize_variables(self):
                pass
            
            async def async_loop(self):
                self.loop_count += 1
                if self.loop_count == 1:
                    raise ValueError("Test exception")
                self.running = False
            
            async def async_run_finally(self):
                pass
        
        controller = TestController()
        
        with LogCapture() as log_cap:
            await controller.async_run()
        
        # Should have logged the error but continued
        assert controller.loop_count == 2


class TestAsyncIntegration:
    """Integration tests for async controller lifecycle."""

    async def test_full_async_lifecycle(self):
        """Test full async lifecycle from initialization to stop."""
        controller = AbstractBaseController(unique_id="test-lifecycle", testing=True)
        
        # Initialize
        await controller.async_initialize()
        assert controller._is_async_initialized is True
        
        # Start
        await controller.async_start()
        
        # Health check
        health = await controller.async_health_check()
        assert health['healthy'] is True
        
        # Stop
        await controller.async_stop()

    async def test_concurrent_operations(self):
        """Test multiple async operations can run concurrently."""
        controller1 = AbstractBaseController(unique_id="test-concurrent-1", testing=True)
        controller2 = AbstractBaseController(unique_id="test-concurrent-2", testing=True)
        
        # Run both initializations concurrently
        await asyncio.gather(
            controller1.async_initialize(),
            controller2.async_initialize()
        )
        
        assert controller1._is_async_initialized is True
        assert controller2._is_async_initialized is True
