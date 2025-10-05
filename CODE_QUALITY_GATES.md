# Code Quality Gates for Mycodo Modernization

**Version:** 1.0  
**Effective Date:** 2025-10-05  
**Scope:** All pull requests targeting master branch

## Overview

This document defines the minimum quality standards that all code contributions must meet before being merged into the Mycodo master branch. These gates are especially important for the ongoing modernization effort where multiple GitHub Copilot coding agents work in parallel.

## 1. Automated Testing Requirements

### Test Coverage
- **New Code:** Minimum 80% line coverage required
- **Modified Code:** Minimum 70% line coverage required
- **Critical Modules:** (controllers, database, config) require 90% coverage
- **Exemptions:** UI/templates, migrations, external integrations

### Test Quality Standards
- All tests must pass on Python 3.9, 3.10, and 3.11
- Unit tests must run in <5 seconds total
- Integration tests must complete within 30 seconds
- No flaky tests allowed (must pass 10 consecutive runs)
- Async tests must use pytest-asyncio properly

### Test Organization
```
mycodo/tests/
├── software_tests/          # Unit tests
│   ├── test_<module>.py
│   └── test_async_*.py     # Async-specific tests
├── integration_tests/       # Integration tests
└── fixtures/                # Shared fixtures
```

## 2. Type Checking Requirements

### MyPy Configuration
- **New Modules:** Must pass mypy in strict mode
- **Modified Modules:** Must not introduce new type errors
- **Legacy Code:** Type stubs allowed, gradual typing accepted

### Type Annotation Coverage
- All public functions/methods must have type hints
- Return types mandatory for functions >5 lines
- Complex types (Union, Optional, TypedDict) must use typing module
- Generic types encouraged (List[str] not list)

### Strict Mode Requirements (New Code Only)
```ini
[mypy]
python_version = 3.11
disallow_untyped_defs = True
disallow_any_untyped = True
disallow_any_generics = True
warn_return_any = True
warn_unused_ignores = True
```

## 3. Code Style and Linting

### Formatting Standards
- **Tool:** Black (line length: 120)
- **Import Sorting:** isort with black profile
- **Docstrings:** Google style, mandatory for public APIs

### Linting Rules
- **Primary:** Ruff (replaces flake8, pylint, isort)
- **Max Complexity:** 18 (per function)
- **Max Line Length:** 120 characters
- **Enforced Rules:**
  - B: flake8-bugbear (likely bugs)
  - C: McCabe complexity
  - E/W: PEP 8 errors and warnings
  - F: Pyflakes (unused imports, undefined names)

### Ignored Rules
- E203: whitespace before ':' (conflicts with Black)
- E501: line too long (handled by Black)
- W503: line break before binary operator
- F401: unused imports in __init__.py
- F403: wildcard imports in type stubs

## 4. Documentation Requirements

### Code Documentation
- **Public APIs:** Comprehensive docstrings with examples
- **Complex Logic:** Inline comments explaining "why", not "what"
- **Type Annotations:** Serve as inline documentation

### PR Documentation
Every PR must include:
1. **SUMMARY.md or PHASE_N_SUMMARY.md:**
   - Implementation overview
   - Key design decisions
   - Breaking changes (if any)
   - Migration guide (if needed)

2. **Updated docs/ folder:**
   - Architecture docs for new patterns
   - API docs for new endpoints
   - User guides for new features

3. **CHANGELOG entry:**
   - Added to unreleased section
   - Follows Keep a Changelog format
   - Links to GitHub issue

### Example Docstring
```python
async def retry_async_operation(
    operation: Callable[[], Awaitable[T]],
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
) -> T:
    """Retry an async operation with exponential backoff.
    
    Args:
        operation: Async callable to retry
        max_attempts: Maximum retry attempts (default: 3)
        delay: Initial delay in seconds (default: 1.0)
        backoff: Backoff multiplier (default: 2.0)
    
    Returns:
        Result of successful operation
    
    Raises:
        Exception: Last exception if all attempts fail
    
    Example:
        >>> async def fetch_data():
        ...     return await api.get("/data")
        >>> result = await retry_async_operation(fetch_data, max_attempts=5)
    """
```

## 5. Architecture and Design Standards

### Async/Await Patterns (New Code)
- Use async/await for I/O operations
- No blocking calls in async functions
- Use asyncio.create_task() for background work
- Proper exception handling with try/except
- Resource cleanup with async context managers

### Configuration Management (New Code)
- Use Pydantic models for config validation
- Environment variables via pydantic-settings
- No hardcoded secrets or credentials
- Validate config on startup

### Error Handling
- Custom exceptions for domain errors
- Proper logging with context
- No bare except: clauses
- Re-raise with context preservation

### Dependency Management
- New dependencies must be justified in PR
- Pin exact versions in requirements.txt
- Security scanning required
- License compatibility checked

## 6. Breaking Changes Policy

### Definition
A breaking change is any modification that:
- Removes or renames public API
- Changes function signatures
- Alters expected behavior
- Requires user action to upgrade

### Required Process
1. **Discussion:** Post RFC issue first
2. **Deprecation Path:** Minimum 2 release cycle
3. **Migration Guide:** Step-by-step instructions
4. **Backward Compatibility:** Maintain if possible
5. **Documentation:** Update all affected docs

### Deprecation Example
```python
import warnings
from typing import Optional

def old_function(param: str) -> str:
    """Deprecated: Use new_function() instead.
    
    .. deprecated:: 8.17.0
        Use :func:`new_function` instead. Will be removed in 9.0.0.
    """
    warnings.warn(
        "old_function is deprecated, use new_function instead",
        DeprecationWarning,
        stacklevel=2
    )
    return new_function(param)
```

## 7. Git and PR Standards

### Commit Messages
Follow Conventional Commits:
```
<type>(<scope>): <subject>

<body>

<footer>
```

Types: feat, fix, docs, refactor, test, chore, perf
Scope: module name or feature area
Subject: imperative mood, lowercase, no period

### Branch Naming
- Feature: `feature/<issue-number>-short-description`
- Bugfix: `fix/<issue-number>-short-description`
- Copilot: `copilot/fix-<uuid>` (auto-generated)

### PR Requirements
- **Title:** Conventional commit format
- **Description:** Link to issue, describe changes
- **Size:** Prefer <500 lines, max 1000 lines
- **Reviews:** Minimum 1 approval required
- **CI:** All checks must pass
- **Conflicts:** Must be resolved before merge

### Merge Strategy
- **Default:** Squash and merge
- **Exceptions:** Feature branches with meaningful history
- **Cleanup:** Delete branch after merge

## 8. Security Requirements

### Code Security
- No hardcoded credentials or API keys
- Input validation on all external data
- SQL injection prevention (use parameterized queries)
- XSS prevention (escape user content)
- CSRF tokens on state-changing operations

### Dependency Security
- Run `safety check` on all dependencies
- Update vulnerable packages immediately
- Review security advisories weekly
- Use Dependabot or Renovate for automation

### Secrets Management
- Environment variables for secrets
- `.env` files never committed
- Use secrets manager for production
- Rotate credentials regularly

## 9. Performance Requirements

### Response Time
- API endpoints: <500ms p95
- Database queries: <100ms p95
- Background tasks: Complete within timeout
- Memory: No memory leaks in 24hr run

### Optimization Standards
- Profile before optimizing
- Document performance-critical sections
- Use caching where appropriate
- Lazy load heavy operations

### Monitoring
- All new endpoints must have metrics
- Log performance degradation
- Alert on threshold violations
- Track error rates

## 10. Review Process

### Automated Reviews
1. GitHub Actions CI runs automatically
2. Tests, type checking, linting must pass
3. Coverage report generated
4. Security scanning performed

### Human Review
Required for:
- All PRs from external contributors
- Breaking changes
- Architecture changes
- Performance-critical code

Review checklist:
- [ ] Code solves stated problem
- [ ] Tests cover edge cases
- [ ] Documentation complete
- [ ] No obvious bugs or issues
- [ ] Follows project patterns
- [ ] Performance acceptable
- [ ] Security considerations addressed

### Agent Review (Copilot PRs)
For GitHub Copilot agent PRs:
- Automated checks more critical (no human wrote code)
- Manual review focuses on architecture and design
- Test coverage especially important
- Documentation must be excellent

### Approval Requirements
- **Simple changes:** 1 approval
- **Complex changes:** 2 approvals
- **Breaking changes:** 3 approvals + RFC discussion
- **Security fixes:** Security team approval

## 11. Enforcement

### PR Checklist Template
```markdown
## PR Checklist

- [ ] Tests added/updated (80% coverage for new code)
- [ ] Type hints added (mypy passes)
- [ ] Code formatted (black, isort)
- [ ] Documentation updated
- [ ] CHANGELOG entry added
- [ ] No breaking changes (or migration guide provided)
- [ ] CI passes (all workflows green)
- [ ] Performance acceptable (if relevant)
- [ ] Security reviewed (if handling sensitive data)
```

### CI Enforcement
All workflows defined in `.github/workflows/`:
- `test.yml` - pytest with coverage
- `type-check.yml` - mypy validation
- `lint.yml` - ruff, black, isort
- `pr-checks.yml` - PR metadata validation

### Exception Process
If a PR cannot meet all gates:
1. Document reason in PR description
2. Get explicit approval from maintainer
3. Create follow-up issue to address
4. Add TODO comment with issue link

## 12. Decision Log

### Decisions Made (2025-10-05)

| Decision | Rationale | Impact |
|----------|-----------|--------|
| 80% coverage for new code | Balance quality and velocity | High bar for new modules |
| MyPy strict mode for new code | Catch bugs early | Gradual migration path |
| Black line length 120 | Fits modern monitors | More code per line |
| Squash merge default | Clean history | Lose detailed commit info |
| Async/await mandatory for new I/O | Modern Python best practice | Blocks sync code mixing |

### Pending Decisions

- **Test coverage tool:** pytest-cov vs coverage.py directly
- **Documentation hosting:** ReadTheDocs vs GitHub Pages
- **API versioning:** Semantic versioning policy
- **Database migration:** alembic best practices

## 13. Resources

### Tools Installation
```bash
pip install pytest pytest-asyncio pytest-cov pytest-mock
pip install mypy types-requests types-redis types-pyyaml
pip install ruff black isort
pip install safety bandit
```

### Pre-commit Hooks
See `.pre-commit-config.yaml` for automatic enforcement:
- black formatting
- isort import sorting
- trailing whitespace removal
- YAML validation

### Documentation
- [Ruff Rules](https://beta.ruff.rs/docs/rules/)
- [MyPy Documentation](https://mypy.readthedocs.io/)
- [Conventional Commits](https://www.conventionalcommits.org/)
- [Keep a Changelog](https://keepachangelog.com/)

---

**Approved by:** m0nk111  
**Review Date:** Quarterly (next: 2025-01-05)  
**Change History:** See Git history for modifications
