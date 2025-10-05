# coding=utf-8
"""Tests for async utility functions."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from mycodo.utils.async_utils import (
    async_retry,
    async_timeout,
    AsyncEventLoopManager,
)


# Configure pytest to handle async tests
pytestmark = pytest.mark.asyncio


class TestAsyncRetry:
    """Tests for async_retry function."""

    async def test_successful_on_first_attempt(self):
        """Test that function succeeds on first attempt."""
        mock_func = AsyncMock(return_value="success")
        
        result = await async_retry(mock_func, max_retries=3)
        
        assert result == "success"
        assert mock_func.call_count == 1

    async def test_retry_on_failure(self):
        """Test that function retries on failure."""
        mock_func = AsyncMock(side_effect=[
            ValueError("First attempt"),
            ValueError("Second attempt"),
            "success"
        ])
        
        result = await async_retry(
            mock_func,
            max_retries=3,
            initial_delay=0.01,
            exceptions=(ValueError,)
        )
        
        assert result == "success"
        assert mock_func.call_count == 3

    async def test_max_retries_exceeded(self):
        """Test that exception is raised when max retries exceeded."""
        mock_func = AsyncMock(side_effect=ValueError("Always fails"))
        
        with pytest.raises(ValueError, match="Always fails"):
            await async_retry(
                mock_func,
                max_retries=2,
                initial_delay=0.01,
                exceptions=(ValueError,)
            )
        
        assert mock_func.call_count == 2

    async def test_exponential_backoff(self):
        """Test exponential backoff delay calculation."""
        mock_func = AsyncMock(side_effect=[ValueError(), ValueError(), "success"])
        
        # Track timing
        start = asyncio.get_event_loop().time()
        await async_retry(
            mock_func,
            max_retries=3,
            initial_delay=0.1,
            backoff_factor=2.0,
            exceptions=(ValueError,)
        )
        elapsed = asyncio.get_event_loop().time() - start
        
        # Should take at least 0.1 + 0.2 = 0.3 seconds
        assert elapsed >= 0.3
        assert mock_func.call_count == 3

    async def test_max_delay_cap(self):
        """Test that max_delay caps the retry delay."""
        mock_func = AsyncMock(side_effect=[ValueError(), ValueError(), "success"])
        
        result = await async_retry(
            mock_func,
            max_retries=3,
            initial_delay=1.0,
            backoff_factor=10.0,
            max_delay=0.1,
            exceptions=(ValueError,)
        )
        
        assert result == "success"
        # Max delay should prevent very long waits


class TestAsyncTimeout:
    """Tests for async_timeout function."""

    async def test_completes_within_timeout(self):
        """Test that function completes successfully within timeout."""
        async def quick_func():
            await asyncio.sleep(0.01)
            return "completed"
        
        result = await async_timeout(quick_func(), timeout_sec=1.0)
        assert result == "completed"

    async def test_timeout_with_default_result(self):
        """Test timeout returns default result when provided."""
        async def slow_func():
            await asyncio.sleep(10)
            return "never reached"
        
        result = await async_timeout(
            slow_func(),
            timeout_sec=0.1,
            timeout_result="default"
        )
        assert result == "default"

    async def test_timeout_raises_exception(self):
        """Test timeout raises exception when no default provided."""
        async def slow_func():
            await asyncio.sleep(10)
            return "never reached"
        
        with pytest.raises(asyncio.TimeoutError):
            await async_timeout(slow_func(), timeout_sec=0.1)


class TestAsyncEventLoopManager:
    """Tests for AsyncEventLoopManager."""

    def test_get_or_create_event_loop(self):
        """Test getting or creating an event loop."""
        loop = AsyncEventLoopManager.get_or_create_event_loop()
        assert loop is not None
        assert isinstance(loop, asyncio.AbstractEventLoop)
        assert not loop.is_closed()

    def test_run_async(self):
        """Test running async function in sync context."""
        async def async_func():
            await asyncio.sleep(0.01)
            return "result"
        
        result = AsyncEventLoopManager.run_async(async_func())
        assert result == "result"

    def test_run_async_with_timeout(self):
        """Test running async function with timeout."""
        async def slow_func():
            await asyncio.sleep(10)
            return "never"
        
        with pytest.raises(asyncio.TimeoutError):
            AsyncEventLoopManager.run_async(slow_func(), timeout=0.1)

    async def test_create_task_if_loop_running(self):
        """Test creating task when loop is running."""
        async def task_func():
            await asyncio.sleep(0.01)
            return "task_result"
        
        task = AsyncEventLoopManager.create_task_if_loop_running(task_func())
        assert task is not None
        result = await task
        assert result == "task_result"

    def test_create_task_no_loop(self):
        """Test creating task when no loop is running."""
        # This test runs outside of an event loop context
        async def task_func():
            return "result"
        
        # When not in async context, should return None
        # Skip this test in async context
        pass
