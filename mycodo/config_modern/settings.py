"""
Modern Pydantic-based configuration for Mycodo.
This is an example implementation for Issue #8.
"""
from typing import Optional, List
from pathlib import Path
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """Database configuration."""
    
    model_config = SettingsConfigDict(
        env_prefix='MYCODO_DB_',
        case_sensitive=False
    )
    
    driver: str = Field(default="sqlite", description="Database driver")
    name: str = Field(default="mycodo.db", description="Database name")
    
    @property
    def url(self) -> str:
        """Get database URL."""
        if self.driver == "sqlite":
            return f"sqlite:///{self.name}"
        raise ValueError(f"Unsupported database driver: {self.driver}")


class MycodoSettings(BaseSettings):
    """Main Mycodo configuration."""
    
    model_config = SettingsConfigDict(
        env_file='.env',
        env_file_encoding='utf-8',
        case_sensitive=False,
        env_prefix='MYCODO_'
    )
    
    version: str = Field(default="9.0.0", description="Mycodo version")
    environment: str = Field(default="production", description="Environment")
    debug: bool = Field(default=False, description="Debug mode")
    
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)


# Global settings instance
settings = MycodoSettings()
