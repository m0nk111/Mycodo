# coding=utf-8
"""
Health check utilities for Mycodo.

This module provides health check functionality for monitoring
the status of various system components.
"""
import os
import time
from typing import Dict, Any

from mycodo.config import SQL_DATABASE_MYCODO
from mycodo.databases.utils import session_scope


class HealthChecker:
    """Health check utility for system components."""
    
    def __init__(self):
        """Initialize the health checker."""
        self.start_time = time.time()
    
    def check_database(self) -> Dict[str, Any]:
        """
        Check database connectivity and health.
        
        Returns:
            Dictionary with status and details
        """
        try:
            # Try to connect to the database
            with session_scope(f'sqlite:///{SQL_DATABASE_MYCODO}') as session:
                # Execute a simple query
                result = session.execute("SELECT 1").fetchone()
                if result and result[0] == 1:
                    return {
                        'status': 'healthy',
                        'message': 'Database connection successful',
                        'details': {
                            'database_path': SQL_DATABASE_MYCODO,
                            'database_exists': os.path.exists(SQL_DATABASE_MYCODO)
                        }
                    }
            return {
                'status': 'unhealthy',
                'message': 'Database query failed'
            }
        except Exception as e:
            return {
                'status': 'unhealthy',
                'message': f'Database connection failed: {str(e)}',
                'error': str(e)
            }
    
    def check_gpio(self) -> Dict[str, Any]:
        """
        Check GPIO availability.
        
        Returns:
            Dictionary with status and details
        """
        try:
            # Try to import RPi.GPIO
            import RPi.GPIO as GPIO
            return {
                'status': 'healthy',
                'message': 'GPIO available',
                'details': {
                    'gpio_available': True,
                    'gpio_version': GPIO.VERSION if hasattr(GPIO, 'VERSION') else 'unknown'
                }
            }
        except ImportError:
            return {
                'status': 'degraded',
                'message': 'GPIO not available (not on Raspberry Pi)',
                'details': {
                    'gpio_available': False
                }
            }
        except Exception as e:
            return {
                'status': 'unhealthy',
                'message': f'GPIO check failed: {str(e)}',
                'error': str(e)
            }
    
    def check_daemon(self) -> Dict[str, Any]:
        """
        Check if Mycodo daemon is running.
        
        Returns:
            Dictionary with status and details
        """
        try:
            from mycodo.mycodo_client import DaemonControl
            control = DaemonControl()
            # Try to get daemon status
            ram_use = control.ram_use()
            if ram_use is not None:
                return {
                    'status': 'healthy',
                    'message': 'Daemon is running',
                    'details': {
                        'ram_use_mb': ram_use
                    }
                }
            return {
                'status': 'unhealthy',
                'message': 'Unable to communicate with daemon'
            }
        except Exception as e:
            return {
                'status': 'unhealthy',
                'message': f'Daemon check failed: {str(e)}',
                'error': str(e)
            }
    
    def get_uptime(self) -> float:
        """
        Get application uptime in seconds.
        
        Returns:
            Uptime in seconds
        """
        return time.time() - self.start_time
    
    def check_all(self) -> Dict[str, Any]:
        """
        Perform all health checks.
        
        Returns:
            Dictionary with overall status and individual check results
        """
        database_check = self.check_database()
        gpio_check = self.check_gpio()
        daemon_check = self.check_daemon()
        
        # Determine overall status
        checks = [database_check, gpio_check, daemon_check]
        if all(c['status'] == 'healthy' for c in checks):
            overall_status = 'healthy'
        elif any(c['status'] == 'unhealthy' for c in checks):
            overall_status = 'unhealthy'
        else:
            overall_status = 'degraded'
        
        return {
            'status': overall_status,
            'uptime_seconds': self.get_uptime(),
            'checks': {
                'database': database_check,
                'gpio': gpio_check,
                'daemon': daemon_check
            }
        }


# Global health checker instance
health_checker = HealthChecker()
