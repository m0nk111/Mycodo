# -*- coding: utf-8 -*-
"""
Mycodo Configuration Management with Pydantic Settings

This module provides modern configuration management using Pydantic Settings.
It supports environment variables, .env files, and type validation.
"""

from mycodo.settings.base import Settings
from mycodo.settings.base import get_settings

__all__ = ['Settings', 'get_settings']
