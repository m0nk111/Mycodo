# Modernization Quick Start Guide

This guide helps you get started with the Mycodo modernization effort.

## 📚 First Steps

### 1. Read the Documentation

Start with these documents in order:

1. **[MODERNIZATION_SUMMARY.md](MODERNIZATION_SUMMARY.md)** - Overview and benefits (5 min read)
2. **[MODERNIZATION_ROADMAP.md](MODERNIZATION_ROADMAP.md)** - Detailed roadmap (15 min read)
3. **[AGENT_ASSIGNMENT_PLAN.md](AGENT_ASSIGNMENT_PLAN.md)** - Team assignments (5 min read)

### 2. Understand the Architecture

Choose the topic you'll be working on:

- **Async/Await:** Read [docs/modernization/async-architecture.md](docs/modernization/async-architecture.md)
- **Type Hints:** Read [docs/modernization/type-hints.md](docs/modernization/type-hints.md)
- **Testing:** Read [docs/modernization/testing.md](docs/modernization/testing.md)

### 3. Set Up Your Environment

```bash
# Clone the repository (if not already done)
git clone https://github.com/m0nk111/Mycodo.git
cd Mycodo

# Create a feature branch for your issue
git checkout -b issue-N-short-description

# Set up Python virtual environment
python3.10 -m venv env
source env/bin/activate

# Install dependencies
pip install -r install/requirements.txt
pip install -r install/requirements-testing.txt
pip install -r install/requirements-modern.txt

# Copy environment template
cp .env.example .env
```

## 🔧 Development Tools

### Type Checking with mypy

```bash
# Check entire codebase
mypy mycodo

# Check specific module
mypy mycodo/controllers

# Check your changes only
mypy $(git diff --name-only --diff-filter=AM | grep '\.py$')
```

### Testing with pytest

```bash
# Run all tests
pytest

# Run unit tests only (fast)
pytest -m unit

# Run with coverage
pytest --cov=mycodo --cov-report=html

# Run async tests
pytest -m asyncio

# Run specific test file
pytest mycodo/tests/test_controllers.py
```

### Code Formatting

```bash
# Format code with black
black mycodo/

# Lint with ruff
ruff check mycodo/
```

## 📋 Issue Assignment

Find your issue based on your expertise:

### Backend Specialists
- **Issue #2** - Async/Await Architecture (CRITICAL PATH)
- **Issue #4** - Database Layer (SQLAlchemy 2.0)
- **Issue #6** - Event Bus Architecture
- **Issue #7** - Plugin System

### API Developers
- **Issue #5** - FastAPI REST API
- **Issue #10** - Security & Authentication

### Frontend Developers
- **Issue #9** - Vue.js 3 SPA

### DevOps Engineers
- **Issue #11** - Logging & Monitoring
- **Issue #13** - Docker & Kubernetes

### QA Engineers
- **Issue #12** - Testing Infrastructure

### Generalist Developers
- **Issue #3** - Type Hints (can be done incrementally)
- **Issue #8** - Configuration Management (Pydantic)
- **Issue #14** - Documentation

## 🚀 Working on an Issue

### Step 1: Create Feature Branch

```bash
git checkout -b issue-2-async-await
```

### Step 2: Make Changes

Follow the design document for your issue. Example for Issue #3 (Type Hints):

```python
# Before (no type hints)
def get_temperature(sensor_id):
    sensor = load_sensor(sensor_id)
    return sensor.read()

# After (with type hints)
from typing import Optional

def get_temperature(sensor_id: str) -> Optional[float]:
    """Get temperature reading from sensor."""
    sensor: Sensor = load_sensor(sensor_id)
    return sensor.read()
```

### Step 3: Test Your Changes

```bash
# Run type checking
mypy mycodo/your_module.py

# Run tests
pytest mycodo/tests/test_your_module.py

# Run all tests
pytest -m "not hardware"
```

### Step 4: Commit and Push

```bash
# Stage changes
git add .

# Commit with descriptive message
git commit -m "Issue #3: Add type hints to controller module"

# Push to GitHub
git push origin issue-3-type-hints
```

### Step 5: Create Pull Request

1. Go to GitHub repository
2. Click "New Pull Request"
3. Select your branch
4. Add description:
   - What issue does this address?
   - What changes were made?
   - How to test it?
5. Link to the issue: "Closes #3"

## 📊 Progress Tracking

Update the issue status regularly:

```markdown
- [x] Read issue description
- [x] Set up development environment
- [x] Implement feature X
- [ ] Write tests for feature X
- [ ] Update documentation
- [ ] Create pull request
```

## 🔍 Code Review Guidelines

When reviewing others' code:

### For Async Code (Issue #2, #4, #5)
- ✅ Check for `async def` on I/O functions
- ✅ Verify `await` is used for async calls
- ✅ No blocking `time.sleep()` - use `asyncio.sleep()`
- ✅ Proper exception handling for `CancelledError`

### For Type Hints (Issue #3)
- ✅ All function parameters have types
- ✅ All function return values have types
- ✅ Complex types use `typing` module
- ✅ No `# type: ignore` without explanation

### For Tests (Issue #12)
- ✅ Test covers happy path
- ✅ Test covers error cases
- ✅ Mocks are used for external dependencies
- ✅ Tests are fast (<1 second each)

## 🐛 Common Issues

### Issue: Import errors with new dependencies

```bash
# Solution: Reinstall requirements
pip install -r install/requirements-modern.txt
```

### Issue: mypy complains about missing stubs

```bash
# Solution: Add to mypy.ini
[mypy-package_name.*]
ignore_missing_imports = True
```

### Issue: Async tests not running

```bash
# Solution: Install pytest-asyncio
pip install pytest-asyncio

# Or mark test explicitly
@pytest.mark.asyncio
async def test_my_function():
    result = await my_async_function()
    assert result is not None
```

## 📞 Getting Help

### Resources
- **Slack/Discord:** #mycodo-modernization channel
- **GitHub Issues:** Comment on your assigned issue
- **Documentation:** Check [docs/modernization/](docs/modernization/)
- **Weekly Meetings:** Monday 2 PM UTC (TBD)

### Common Questions

**Q: Can I start working on an issue immediately?**  
A: Check dependencies first! Some issues require others to be completed.

**Q: How do I know if my changes break existing functionality?**  
A: Run the full test suite with `pytest`. All tests should pass.

**Q: What if I disagree with the design document?**  
A: Discuss in the issue comments before implementing. Design is flexible!

**Q: How much should I refactor existing code?**  
A: Minimal changes! Only refactor what's necessary for your issue.

## ✅ Checklist for Completing an Issue

Before marking your issue as complete:

- [ ] All code changes are committed
- [ ] Type hints added (if applicable)
- [ ] Tests written and passing
- [ ] Documentation updated
- [ ] mypy passes (no errors)
- [ ] pytest passes (all tests)
- [ ] Code reviewed by at least one other developer
- [ ] Pull request merged to main branch

## 🎯 Goals

Remember our objectives:

- **Performance:** 10x improvement in concurrent operations
- **Code Quality:** 80%+ test coverage, 100% type hints
- **Developer Experience:** Fast development, clear errors
- **Operations:** Easy deployment, zero-downtime updates

## 🚀 Let's Build the Future of Mycodo!

Your contributions are making Mycodo faster, more maintainable, and better for everyone. Thank you for being part of this modernization effort!

---

**Questions?** Read the [MODERNIZATION_SUMMARY.md](MODERNIZATION_SUMMARY.md) or ask in the issue comments.

**Status Updates:** Track progress in [docs/modernization/README.md](docs/modernization/README.md)
