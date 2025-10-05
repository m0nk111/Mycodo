# Testing Infrastructure Documentation

## Overview

This document describes the testing strategy and infrastructure for Mycodo modernization.

**Related Issue:** #12  
**Status:** Infrastructure Ready  
**Dependencies:** None

---

## Test Categories

### Unit Tests
- Fast, isolated tests
- No external dependencies
- Mock all I/O operations
- Target: 80% coverage

### Integration Tests
- Test component interactions
- Database, API, plugins
- Use test database
- Target: Key workflows covered

### Hardware Tests
- Require actual hardware
- Raspberry Pi GPIO tests
- Sensor integration tests
- Run manually or in hardware CI

---

## Configuration

Testing is configured in `pytest.ini`:

```ini
[pytest]
testpaths = mycodo/tests
asyncio_mode = auto
markers =
    unit: Unit tests
    integration: Integration tests
    hardware: Hardware tests
```

---

## Usage

### Running tests

```bash
# Run all tests
pytest

# Run unit tests only
pytest -m unit

# Run with coverage
pytest --cov=mycodo --cov-report=html

# Run async tests
pytest -m asyncio

# Run specific test file
pytest mycodo/tests/test_controllers.py

# Run specific test
pytest mycodo/tests/test_controllers.py::test_input_controller
```

---

## Writing Tests

### Unit Test Example

```python
import pytest
from mycodo.controllers import InputController

@pytest.mark.unit
def test_input_controller_init():
    """Test input controller initialization."""
    controller = InputController(unique_id="test-001")
    assert controller.unique_id == "test-001"
```

### Async Test Example

```python
import pytest
from mycodo.controllers import AsyncInputController

@pytest.mark.asyncio
async def test_async_input_controller():
    """Test async input controller."""
    controller = AsyncInputController(unique_id="test-001")
    await controller.initialize()
    assert controller.sensor is not None
```

---

## Test Fixtures

Common test fixtures are defined in `conftest.py`:

```python
import pytest
from mycodo.databases import create_test_db

@pytest.fixture
def test_db():
    """Provide test database."""
    db = create_test_db()
    yield db
    db.cleanup()
```

---

## CI/CD Integration

GitHub Actions workflow for testing:

```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.10'
      - run: pip install -r requirements-testing.txt
      - run: pytest --cov=mycodo
```

---

## References

- [pytest Documentation](https://docs.pytest.org/)
- [pytest-asyncio](https://pytest-asyncio.readthedocs.io/)
- [pytest-cov](https://pytest-cov.readthedocs.io/)
