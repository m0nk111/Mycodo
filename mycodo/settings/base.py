# -*- coding: utf-8 -*-
"""
Base Pydantic Settings for Mycodo Configuration

This module defines the core configuration structure using Pydantic Settings.
All configuration values are type-safe and can be overridden via environment variables.
"""

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional, Literal

from pydantic import Field, field_validator, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """Database configuration settings."""
    
    model_config = SettingsConfigDict(
        env_prefix='MYCODO_DB_',
        case_sensitive=False,
        env_file='.env',
        env_file_encoding='utf-8',
        extra='ignore'
    )
    
    # Database name and paths
    database_name: str = Field(default="mycodo.db", description="SQLite database filename")
    
    # InfluxDB settings
    influxdb_name: str = Field(default='influxdb', description="InfluxDB database name")
    influxdb_version: str = Field(default='', description="InfluxDB version")
    influxdb_host: str = Field(default='localhost', description="InfluxDB host")
    influxdb_port: int = Field(default=0, description="InfluxDB port")
    influxdb_retention_policy: str = Field(default='', description="InfluxDB retention policy")


class PathSettings(BaseSettings):
    """Path configuration settings."""
    
    model_config = SettingsConfigDict(
        env_prefix='MYCODO_PATH_',
        case_sensitive=False,
        env_file='.env',
        env_file_encoding='utf-8',
        extra='ignore'
    )
    
    # Base install directory
    install_directory: str = Field(
        default_factory=lambda: os.path.abspath(
            os.path.dirname(os.path.realpath(__file__)) + '/../..'
        ),
        description="Mycodo installation directory"
    )
    
    # Log directory
    log_path: str = Field(default='/var/log/mycodo', description="Log file directory")
    
    # Lock directory
    lock_path: str = Field(default='/var/lock', description="Lock file directory")
    
    # Run directory
    run_path: str = Field(default='/var/run', description="Run file directory")
    
    # Backup directory
    backup_path: str = Field(default='/var/Mycodo-backups', description="Backup directory")
    
    # 1-Wire device path
    path_1wire: str = Field(default='/sys/bus/w1/devices/', description="1-Wire device path")
    
    @computed_field
    @property
    def database_path(self) -> str:
        """Database directory path."""
        return os.path.join(self.install_directory, 'databases')
    
    @computed_field
    @property
    def cameras_path(self) -> str:
        """Cameras directory path."""
        return os.path.join(self.install_directory, 'cameras')
    
    @computed_field
    @property
    def note_attachments_path(self) -> str:
        """Note attachments directory path."""
        return os.path.join(self.install_directory, 'note_attachments')
    
    @computed_field
    @property
    def controllers_path(self) -> str:
        """Controllers module path."""
        return os.path.join(self.install_directory, 'mycodo/controllers')
    
    @computed_field
    @property
    def functions_path(self) -> str:
        """Functions module path."""
        return os.path.join(self.install_directory, 'mycodo/functions')
    
    @computed_field
    @property
    def actions_path(self) -> str:
        """Actions module path."""
        return os.path.join(self.install_directory, 'mycodo/actions')
    
    @computed_field
    @property
    def inputs_path(self) -> str:
        """Inputs module path."""
        return os.path.join(self.install_directory, 'mycodo/inputs')
    
    @computed_field
    @property
    def outputs_path(self) -> str:
        """Outputs module path."""
        return os.path.join(self.install_directory, 'mycodo/outputs')
    
    @computed_field
    @property
    def widgets_path(self) -> str:
        """Widgets module path."""
        return os.path.join(self.install_directory, 'mycodo/widgets')


class LoggingSettings(BaseSettings):
    """Logging configuration settings."""
    
    model_config = SettingsConfigDict(
        env_prefix='MYCODO_LOG_',
        case_sensitive=False,
        env_file='.env',
        env_file_encoding='utf-8',
        extra='ignore'
    )
    
    # Log file paths (computed from log_path)
    path: str = Field(default='/var/log/mycodo', description="Log directory")
    
    @computed_field
    @property
    def login_log_file(self) -> str:
        """Login log file path."""
        return os.path.join(self.path, 'login.log')
    
    @computed_field
    @property
    def daemon_log_file(self) -> str:
        """Daemon log file path."""
        return os.path.join(self.path, 'mycodo.log')
    
    @computed_field
    @property
    def keepup_log_file(self) -> str:
        """Keepup log file path."""
        return os.path.join(self.path, 'mycodokeepup.log')
    
    @computed_field
    @property
    def backup_log_file(self) -> str:
        """Backup log file path."""
        return os.path.join(self.path, 'mycodobackup.log')
    
    @computed_field
    @property
    def dependency_log_file(self) -> str:
        """Dependency log file path."""
        return os.path.join(self.path, 'mycododependency.log')
    
    @computed_field
    @property
    def upgrade_log_file(self) -> str:
        """Upgrade log file path."""
        return os.path.join(self.path, 'mycodoupgrade.log')


class SecuritySettings(BaseSettings):
    """Security configuration settings."""
    
    model_config = SettingsConfigDict(
        env_prefix='MYCODO_SECURITY_',
        case_sensitive=False,
        env_file='.env',
        env_file_encoding='utf-8',
        extra='ignore'
    )
    
    # Login restrictions
    login_attempts: int = Field(default=5, ge=1, description="Maximum login attempts before ban")
    login_ban_seconds: int = Field(default=600, ge=1, description="Login ban duration in seconds")
    
    # Session settings
    wtf_csrf_time_limit: int = Field(
        default=60 * 60 * 24 * 7,
        ge=1,
        description="CSRF token time limit in seconds"
    )
    remember_cookie_duration_days: int = Field(
        default=90,
        ge=1,
        description="Remember cookie duration in days"
    )


class ServiceSettings(BaseSettings):
    """Service configuration settings."""
    
    model_config = SettingsConfigDict(
        env_prefix='MYCODO_SERVICE_',
        case_sensitive=False,
        env_file='.env',
        env_file_encoding='utf-8',
        extra='ignore'
    )
    
    # Flask settings
    force_https: bool = Field(default=True, description="Force HTTPS for Flask")
    enable_flask_profiler: bool = Field(default=False, description="Enable Flask profiler")
    
    # Pyro5 settings
    pyro_uri: Optional[str] = Field(default=None, description="Pyro5 URI override")
    rpyc_timeout: int = Field(default=30, ge=1, description="RPyC timeout in seconds")
    
    # Docker detection
    docker_container: bool = Field(
        default_factory=lambda: os.environ.get('DOCKER_CONTAINER', 'FALSE') == 'TRUE',
        description="Running in Docker container"
    )
    
    # Statistics service
    stats_interval: int = Field(default=86400, ge=60, description="Statistics interval in seconds")
    stats_host: str = Field(default='fungi.kylegabriel.com', description="Statistics host")
    stats_port: int = Field(default=8086, ge=1, le=65535, description="Statistics port")
    stats_database: str = Field(default='mycodo_stats', description="Statistics database name")
    
    # Upgrade check
    upgrade_check_interval: int = Field(
        default=172800,
        ge=3600,
        description="Upgrade check interval in seconds"
    )
    force_upgrade_master: bool = Field(
        default=False,
        description="Force upgrade to master branch"
    )
    
    @computed_field
    @property
    def pyro_uri_computed(self) -> str:
        """Compute Pyro5 URI based on Docker status."""
        if self.pyro_uri:
            return self.pyro_uri
        if self.docker_container:
            return 'PYRO:mycodo.pyro_server@mycodo_daemon:9080'
        return 'PYRO:mycodo.pyro_server@127.0.0.1:9080'


class HardwareSettings(BaseSettings):
    """Hardware/GPIO configuration settings."""
    
    model_config = SettingsConfigDict(
        env_prefix='MYCODO_HARDWARE_',
        case_sensitive=False,
        env_file='.env',
        env_file_encoding='utf-8',
        extra='ignore'
    )
    
    # Network test settings
    net_test_ip: str = Field(default='8.8.8.8', description="Network test IP")
    net_test_port: int = Field(default=53, ge=1, le=65535, description="Network test port")
    net_test_timeout: int = Field(default=3, ge=1, description="Network test timeout in seconds")


class Settings(BaseSettings):
    """Main Mycodo configuration settings."""
    
    model_config = SettingsConfigDict(
        env_prefix='MYCODO_',
        case_sensitive=False,
        env_file='.env',
        env_file_encoding='utf-8',
        extra='ignore'
    )
    
    # Version information
    version: str = Field(default='8.16.2', description="Mycodo version")
    alembic_version: str = Field(default='5966b3569c89', description="Alembic version")
    
    # Environment
    environment: Literal['development', 'testing', 'production'] = Field(
        default='production',
        description="Application environment"
    )
    
    # Nested settings
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    paths: PathSettings = Field(default_factory=PathSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    services: ServiceSettings = Field(default_factory=ServiceSettings)
    hardware: HardwareSettings = Field(default_factory=HardwareSettings)
    
    @field_validator('version')
    @classmethod
    def validate_version(cls, v: str) -> str:
        """Validate version format."""
        if not v or len(v.split('.')) < 2:
            raise ValueError('Version must be in format X.Y.Z')
        return v


@lru_cache()
def get_settings() -> Settings:
    """
    Get cached settings instance.
    
    This function uses LRU cache to ensure settings are loaded only once.
    Settings can be overridden via environment variables or .env file.
    
    Returns:
        Settings: Configured settings instance
    """
    return Settings()
