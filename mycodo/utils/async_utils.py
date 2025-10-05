# coding=utf-8
"""
Async utility functions for Mycodo controllers.

Provides async retry logic, timeout handling, and event loop management utilities.
"""
import asyncio
import logging
from functools import wraps
from typing import Any, Callable, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar('T')


async def async_retry(
    func: Callable[..., Any],
    *args,
    max_retries: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    max_delay: float = 60.0,
    exceptions: tuple = (Exception,),
    **kwargs
) -> Any:
    """
    Retry an async function with exponential backoff.

    Args:
        func: Async function to retry
        *args: Positional arguments to pass to func
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay between retries in seconds
        backoff_factor: Multiplier for delay after each retry
        max_delay: Maximum delay between retries in seconds
        exceptions: Tuple of exception types to catch and retry on
        **kwargs: Keyword arguments to pass to func

    Returns:
        The result of the function call

    Raises:
        The last exception encountered if all retries fail
    """
    delay = initial_delay
    last_exception = None

    for attempt in range(max_retries):
        try:
            return await func(*args, **kwargs)
        except exceptions as e:
            last_exception = e
            if attempt < max_retries - 1:
                logger.warning(
                    f"Attempt {attempt + 1}/{max_retries} failed for {func.__name__}: {e}. "
                    f"Retrying in {delay:.1f}s..."
                )
                await asyncio.sleep(delay)
                delay = min(delay * backoff_factor, max_delay)
            else:
                logger.error(
                    f"All {max_retries} attempts failed for {func.__name__}. "
                    f"Last error: {e}"
                )

    raise last_exception


async def async_timeout(coro, timeout_sec: float, timeout_result: Any = None) -> Any:
    """
    Execute a coroutine with a timeout.

    Args:
        coro: Coroutine to execute
        timeout_sec: Timeout in seconds
        timeout_result: Result to return on timeout (if None, raises TimeoutError)

    Returns:
        Result of the coroutine or timeout_result

    Raises:
        asyncio.TimeoutError: If timeout occurs and timeout_result is None
    """
    try:
        return await asyncio.wait_for(coro, timeout=timeout_sec)
    except asyncio.TimeoutError:
        if timeout_result is not None:
            logger.warning(f"Operation timed out after {timeout_sec}s, returning default result")
            return timeout_result
        raise


def async_context_manager(async_enter_func: Callable, async_exit_func: Callable):
    """
    Decorator to create an async context manager from enter and exit functions.

    Example:
        @async_context_manager
        async def my_resource():
            # Setup code
            resource = await setup()
            yield resource
            # Cleanup code
            await cleanup(resource)
    """
    class AsyncContextManager:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs
            self.resource = None
            self.generator = None

        async def __aenter__(self):
            self.generator = async_enter_func(*self.args, **self.kwargs)
            self.resource = await self.generator.__anext__()
            return self.resource

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            try:
                await self.generator.__anext__()
            except StopAsyncIteration:
                pass
            return False

    return AsyncContextManager


class AsyncEventLoopManager:
    """
    Manages event loops for controllers.

    Provides utilities to get or create event loops and run async functions
    in a controlled manner.
    """

    @staticmethod
    def get_or_create_event_loop() -> asyncio.AbstractEventLoop:
        """
        Get the current event loop or create a new one if none exists.

        Returns:
            asyncio.AbstractEventLoop: The event loop
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop

    @staticmethod
    def run_async(coro, timeout: Optional[float] = None) -> Any:
        """
        Run an async coroutine in a synchronous context.

        Args:
            coro: Coroutine to run
            timeout: Optional timeout in seconds

        Returns:
            Result of the coroutine

        Raises:
            asyncio.TimeoutError: If timeout is specified and exceeded
        """
        loop = AsyncEventLoopManager.get_or_create_event_loop()
        if timeout:
            coro = asyncio.wait_for(coro, timeout=timeout)
        return loop.run_until_complete(coro)

    @staticmethod
    def create_task_if_loop_running(coro) -> Optional[asyncio.Task]:
        """
        Create a task if an event loop is currently running.

        Args:
            coro: Coroutine to create task from

        Returns:
            asyncio.Task or None if no loop is running
        """
        try:
            loop = asyncio.get_running_loop()
            return loop.create_task(coro)
        except RuntimeError:
            logger.debug("No event loop running, cannot create task")
            return None


def run_in_executor(func: Callable[..., T], *args, **kwargs) -> asyncio.Future:
    """
    Run a synchronous function in an executor to avoid blocking the event loop.

    Args:
        func: Synchronous function to run
        *args: Positional arguments
        **kwargs: Keyword arguments

    Returns:
        Future that resolves to the function result
    """
    loop = asyncio.get_event_loop()
    return loop.run_in_executor(None, lambda: func(*args, **kwargs))
