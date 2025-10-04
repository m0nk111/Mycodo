# Contributing to Mycodo Modernization

Thank you for your interest in contributing to the Mycodo modernization effort!

## 📖 Getting Started

1. **Read the Documentation**
   - Start with [MODERNIZATION_SUMMARY.md](../MODERNIZATION_SUMMARY.md)
   - Read the [MODERNIZATION_ROADMAP.md](../MODERNIZATION_ROADMAP.md)
   - Check [QUICK_START.md](../QUICK_START.md) for setup

2. **Choose an Issue**
   - Review open issues labeled `modernization`
   - Check dependencies before starting
   - Comment on the issue to claim it

3. **Set Up Environment**
   ```bash
   # Install Python 3.10+
   python3.10 -m venv env
   source env/bin/activate
   
   # Install dependencies
   pip install -r install/requirements.txt
   pip install -r install/requirements-modern.txt
   ```

## 🔧 Development Workflow

### 1. Create Feature Branch

```bash
git checkout -b issue-N-short-description
```

### 2. Make Changes

Follow the design documents in this directory:
- Async changes: See [async-architecture.md](async-architecture.md)
- Type hints: See [type-hints.md](type-hints.md)
- Tests: See [testing.md](testing.md)

### 3. Test Your Changes

```bash
# Type checking
mypy mycodo/your_module.py

# Run tests
pytest -v

# Check coverage
pytest --cov=mycodo
```

### 4. Submit Pull Request

- Reference the issue number
- Describe what changed and why
- Include test results
- Update documentation if needed

## 📋 Code Standards

### Type Hints (Issue #3)

```python
from typing import Optional, List, Dict

def get_sensor_data(
    sensor_id: str,
    limit: int = 100
) -> Optional[List[Dict[str, float]]]:
    """Get sensor data with type hints."""
    pass
```

### Async/Await (Issue #2)

```python
import asyncio

async def read_sensor(sensor_id: str) -> float:
    """Read sensor asynchronously."""
    await asyncio.sleep(0.1)  # Simulate I/O
    return 25.5
```

### Testing (Issue #12)

```python
import pytest

@pytest.mark.asyncio
async def test_read_sensor():
    """Test async sensor reading."""
    result = await read_sensor("sensor-001")
    assert result > 0
```

## 🚦 Pull Request Process

1. **Before Submitting**
   - [ ] Code follows style guide
   - [ ] Type hints added
   - [ ] Tests written and passing
   - [ ] Documentation updated
   - [ ] mypy passes
   - [ ] No merge conflicts

2. **Review Process**
   - At least one approval required
   - CI must pass
   - Discussion and iteration welcome

3. **After Merge**
   - Update issue status
   - Close related issues
   - Celebrate! 🎉

## 🐛 Reporting Issues

Found a bug in the modernization code?

1. Check existing issues first
2. Create new issue with:
   - Clear title
   - Steps to reproduce
   - Expected vs actual behavior
   - Environment details

## 💬 Communication

- **GitHub Issues:** Technical discussions
- **Pull Requests:** Code reviews
- **Weekly Meetings:** Progress updates (TBD)

## 🎯 Our Goals

- **Performance:** 10x improvement
- **Code Quality:** 80%+ coverage, 100% type hints
- **Developer Experience:** Fast, clear, maintainable
- **Operations:** Easy deployment, monitoring

## 📚 Resources

- [Python asyncio](https://docs.python.org/3/library/asyncio.html)
- [mypy](https://mypy.readthedocs.io/)
- [pytest](https://docs.pytest.org/)
- [FastAPI](https://fastapi.tiangolo.com/)
- [Pydantic](https://docs.pydantic.dev/)

## ❓ Questions?

- Read [QUICK_START.md](../QUICK_START.md)
- Comment on your issue
- Ask in pull request discussions

Thank you for contributing to Mycodo! 🌱
