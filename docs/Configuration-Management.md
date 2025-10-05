# Configuration Management with Pydantic Settings

## Overview

Mycodo now uses **Pydantic Settings** for modern, type-safe configuration management. This provides:

- ✅ Type validation and checking
- ✅ Environment variable support
- ✅ `.env` file support
- ✅ Clear validation error messages
- ✅ Multiple environment support (dev, test, prod)
- ✅ Backward compatibility with existing code

## Quick Start

### Using Default Configuration

No changes needed! The system works with sensible defaults:

```python
from mycodo.settings import get_settings

settings = get_settings()
print(settings.version)  # '8.16.2'
print(settings.database.database_name)  # 'mycodo.db'
```

### Environment Variable Overrides

Override any setting using environment variables with the `MYCODO_` prefix:

```bash
# Set database name
export MYCODO_DB_DATABASE_NAME=custom.db

# Set log path
export MYCODO_LOG_PATH=/custom/log/path

# Set security settings
export MYCODO_SECURITY_LOGIN_ATTEMPTS=10
export MYCODO_SECURITY_LOGIN_BAN_SECONDS=1200
```

### Using .env File

Create a `.env` file in the project root:

```bash
# Copy the example file
cp .env.example .env

# Edit with your settings
nano .env
```

Example `.env` file:

```ini
MYCODO_ENVIRONMENT=production
MYCODO_DB_DATABASE_NAME=mycodo.db
MYCODO_SERVICE_FORCE_HTTPS=true
MYCODO_SECURITY_LOGIN_ATTEMPTS=5
```

## Configuration Categories

### 1. General Settings

```bash
MYCODO_VERSION=8.16.2
MYCODO_ENVIRONMENT=production  # Options: development, testing, production
```

### 2. Database Settings

```bash
# SQLite
MYCODO_DB_DATABASE_NAME=mycodo.db

# InfluxDB
MYCODO_DB_INFLUXDB_NAME=influxdb
MYCODO_DB_INFLUXDB_HOST=localhost
MYCODO_DB_INFLUXDB_PORT=8086
MYCODO_DB_INFLUXDB_VERSION=2
MYCODO_DB_INFLUXDB_RETENTION_POLICY=autogen
```

### 3. Path Settings

```bash
MYCODO_PATH_INSTALL_DIRECTORY=/home/mycodo/Mycodo
MYCODO_PATH_LOG_PATH=/var/log/mycodo
MYCODO_PATH_LOCK_PATH=/var/lock
MYCODO_PATH_RUN_PATH=/var/run
MYCODO_PATH_BACKUP_PATH=/var/Mycodo-backups
MYCODO_PATH_PATH_1WIRE=/sys/bus/w1/devices/
```

### 4. Logging Settings

```bash
MYCODO_LOG_PATH=/var/log/mycodo
```

All log files are computed from this base path:
- `login.log` - Login attempts
- `mycodo.log` - Main daemon log
- `mycodokeepup.log` - Keepup service log
- `mycodobackup.log` - Backup log
- `mycododependency.log` - Dependency installation log
- `mycodoupgrade.log` - Upgrade log

### 5. Security Settings

```bash
# Login restrictions
MYCODO_SECURITY_LOGIN_ATTEMPTS=5
MYCODO_SECURITY_LOGIN_BAN_SECONDS=600

# Session settings
MYCODO_SECURITY_WTF_CSRF_TIME_LIMIT=604800  # 7 days
MYCODO_SECURITY_REMEMBER_COOKIE_DURATION_DAYS=90
```

### 6. Service Settings

```bash
# Flask web server
MYCODO_SERVICE_FORCE_HTTPS=true
MYCODO_SERVICE_ENABLE_FLASK_PROFILER=false

# Pyro5 daemon
MYCODO_SERVICE_PYRO_URI=PYRO:mycodo.pyro_server@127.0.0.1:9080
MYCODO_SERVICE_RPYC_TIMEOUT=30

# Docker (set automatically by Docker)
DOCKER_CONTAINER=TRUE

# Statistics
MYCODO_SERVICE_STATS_INTERVAL=86400
MYCODO_SERVICE_STATS_HOST=fungi.kylegabriel.com
MYCODO_SERVICE_STATS_PORT=8086
MYCODO_SERVICE_STATS_DATABASE=mycodo_stats

# Upgrades
MYCODO_SERVICE_UPGRADE_CHECK_INTERVAL=172800
MYCODO_SERVICE_FORCE_UPGRADE_MASTER=false
```

### 7. Hardware Settings

```bash
# Network connectivity test
MYCODO_HARDWARE_NET_TEST_IP=8.8.8.8
MYCODO_HARDWARE_NET_TEST_PORT=53
MYCODO_HARDWARE_NET_TEST_TIMEOUT=3
```

## Different Environments

### Development Environment

```bash
export MYCODO_ENVIRONMENT=development
export MYCODO_SERVICE_FORCE_HTTPS=false
export MYCODO_LOG_PATH=/tmp/mycodo-dev/logs
```

### Testing Environment

```bash
export MYCODO_ENVIRONMENT=testing
export MYCODO_DB_DATABASE_NAME=test.db
```

### Production Environment

```bash
export MYCODO_ENVIRONMENT=production
export MYCODO_SERVICE_FORCE_HTTPS=true
```

## Validation

Pydantic automatically validates configuration values:

### Type Checking

```python
# ✓ Valid
MYCODO_SECURITY_LOGIN_ATTEMPTS=5  # Integer

# ✗ Invalid - will raise validation error
MYCODO_SECURITY_LOGIN_ATTEMPTS=invalid
```

### Range Validation

```python
# ✓ Valid
MYCODO_SECURITY_LOGIN_ATTEMPTS=5  # >= 1

# ✗ Invalid - must be >= 1
MYCODO_SECURITY_LOGIN_ATTEMPTS=0
```

### Port Validation

```python
# ✓ Valid
MYCODO_SERVICE_STATS_PORT=8086  # 1-65535

# ✗ Invalid - port out of range
MYCODO_SERVICE_STATS_PORT=99999
```

## Secret Management

### Never Commit Secrets

```bash
# Add to .gitignore (already done)
.env
.env.local
.env.*.local
```

### Environment-Based Secrets (Recommended)

For cloud/container deployments:

```bash
export FLASK_SECRET_KEY=your-secret-key-here
export DATABASE_PASSWORD=your-db-password
```

### File-Based Secrets (Docker Secrets)

For Docker deployments:

```bash
# Mount secrets as files
docker run -v /run/secrets:/run/secrets mycodo
```

### Secret Rotation

Secrets can be rotated by:
1. Setting new environment variable values
2. Restarting the application
3. Pydantic will load the new values

## Backward Compatibility

All existing code continues to work without changes:

```python
# Old way (still works)
from mycodo import config
print(config.MYCODO_VERSION)
print(config.INSTALL_DIRECTORY)
print(config.LOG_PATH)

# New way (recommended)
from mycodo.settings import get_settings
settings = get_settings()
print(settings.version)
print(settings.paths.install_directory)
print(settings.logging.path)
```

## Testing

### Running Tests

```bash
# Install dependencies
pip install pydantic pydantic-settings pytest

# Run configuration tests
pytest mycodo/tests/software_tests/test_pydantic_settings.py -v
```

### Manual Testing

```python
from mycodo.settings import get_settings

# Get settings
settings = get_settings()

# Test overrides
import os
os.environ['MYCODO_DB_DATABASE_NAME'] = 'test.db'

# Clear cache and reload
get_settings.cache_clear()
settings = get_settings()

assert settings.database.database_name == 'test.db'
```

## Troubleshooting

### Configuration Not Loading

1. Check environment variables are set:
   ```bash
   env | grep MYCODO_
   ```

2. Check .env file exists and is readable:
   ```bash
   ls -la .env
   cat .env
   ```

3. Clear settings cache:
   ```python
   from mycodo.settings import get_settings
   get_settings.cache_clear()
   ```

### Validation Errors

Pydantic provides clear error messages:

```python
ValidationError: 1 validation error for Settings
database.influxdb_port
  Input should be less than or equal to 65535 [type=less_than_equal, input_value=99999]
```

Fix by providing a valid value within the specified range.

### Import Errors

If you get import errors:

```bash
# Install required dependencies
pip install pydantic pydantic-settings
```

## Best Practices

1. **Use Environment Variables**: For different deployments
2. **Use .env Files**: For local development
3. **Never Commit Secrets**: Use .gitignore for .env files
4. **Validate Early**: Settings are validated on startup
5. **Use Type Hints**: Leverage IDE autocomplete with typed settings
6. **Document Custom Settings**: Add comments to .env files
7. **Test Configuration**: Write tests for custom settings

## Migration Guide

### For Existing Code

No changes needed! Existing code using `mycodo.config` continues to work.

### For New Code

Use the new Pydantic settings for better type safety:

```python
# Before
from mycodo.config import INSTALL_DIRECTORY, LOG_PATH

# After
from mycodo.settings import get_settings
settings = get_settings()
install_dir = settings.paths.install_directory
log_path = settings.logging.path
```

## Future Enhancements

- [ ] Configuration file formats (YAML/TOML)
- [ ] Configuration validation on save
- [ ] Web UI for configuration management
- [ ] Configuration change notifications
- [ ] Configuration history/versioning
- [ ] Remote configuration management

## References

- [Pydantic Settings Documentation](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
- [Environment Variables Best Practices](https://12factor.net/config)
- [Docker Secrets](https://docs.docker.com/engine/swarm/secrets/)
