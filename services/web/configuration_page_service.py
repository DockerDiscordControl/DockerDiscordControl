#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Configuration Page Service                     #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""
Configuration Page Service - Handles complex configuration page data preparation and assembly
"""

import os
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Days of week for schedule display
DAYS_OF_WEEK = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# Common timezones for template
COMMON_TIMEZONES = [
    'UTC', 'US/Eastern', 'US/Central', 'US/Mountain', 'US/Pacific',
    'Europe/London', 'Europe/Berlin', 'Europe/Paris', 'Europe/Rome',
    'Asia/Tokyo', 'Asia/Shanghai', 'Australia/Sydney'
]


@dataclass
class ConfigurationPageRequest:
    """Represents a configuration page request."""
    force_refresh: bool = False


@dataclass
class ConfigurationPageResult:
    """Represents the result of configuration page data preparation."""
    success: bool
    template_data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class ConfigurationPageService:
    """Service for preparing configuration page data with complex business logic."""

    def __init__(self):
        self.logger = logger

    def prepare_page_data(self, request: ConfigurationPageRequest) -> ConfigurationPageResult:
        """
        Prepare comprehensive configuration page data.

        Args:
            request: ConfigurationPageRequest with page options

        Returns:
            ConfigurationPageResult with template data or error information
        """
        try:
            # Step 1: Load and prepare base configuration
            config = self._load_configuration(request.force_refresh)

            # Step 2: Get current timestamp for versioning
            current_timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

            # Step 3: Load and process Docker containers
            docker_data = self._process_docker_containers(config)

            # Step 4: Process active containers and server configuration
            server_data = self._process_server_configuration(config, docker_data['live_containers'])

            # Step 5: Validate and format timezone
            timezone_data = self._process_timezone_configuration(config)

            # Step 6: Format Docker cache timestamps
            cache_data = self._process_cache_timestamps(timezone_data['timezone_str'])

            # Step 7: Load and format scheduled tasks
            tasks_data = self._process_scheduled_tasks(config, timezone_data['timezone_str'])

            # Step 8: Load container info from JSON files
            container_info = self._load_container_info(docker_data['live_containers'], config)

            # Step 9: Prepare advanced settings
            advanced_settings = self._prepare_advanced_settings(config)

            # Step 10: Load donation settings
            donation_settings = self._load_donation_settings()

            # Step 11: Get default configuration for template compatibility
            default_config = self._get_default_configuration()

            # Step 12: Assemble final template data
            template_data = self._assemble_template_data(
                config, current_timestamp, docker_data, server_data, timezone_data,
                cache_data, tasks_data, container_info, advanced_settings,
                donation_settings, default_config
            )

            return ConfigurationPageResult(
                success=True,
                template_data=template_data
            )

        except Exception as e:
            self.logger.error(f"Error preparing configuration page data: {e}", exc_info=True)
            return ConfigurationPageResult(
                success=False,
                error=f"Error preparing page data: {str(e)}"
            )

    def _load_configuration(self, force_refresh: bool) -> Dict[str, Any]:
        """Load configuration with optional force refresh."""
        from services.config.config_service import load_config

        config = load_config()

        if force_refresh:
            self.logger.info("Force refresh requested - reloading configuration from files")
            from utils.config_cache import init_config_cache
            fresh_config = load_config()
            init_config_cache(fresh_config)
            config = fresh_config

        return config

    def _process_docker_containers(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Process Docker containers with synthetic fallback."""
        from app.utils.web_helpers import get_docker_containers_live

        live_containers_list, cache_error = get_docker_containers_live(self.logger)

        # Create synthetic container list if Docker is not available
        if not live_containers_list and config.get('servers'):
            live_containers_list = []
            for server in config.get('servers', []):
                synthetic_container = {
                    'id': server.get('docker_name', 'unknown'),
                    'name': server.get('docker_name'),
                    'status': 'unknown',
                    'state': 'unknown',
                    'image': 'unknown',
                    'running': False
                }
                live_containers_list.append(synthetic_container)
            self.logger.info(f"Created synthetic container list with {len(live_containers_list)} containers from config")

        return {
            'live_containers': live_containers_list,
            'cache_error': cache_error
        }

    def _process_server_configuration(self, config: Dict[str, Any], live_containers: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Process server configuration and active containers."""
        from app.utils.shared_data import load_active_containers_from_config, get_active_containers

        # Build configured servers mapping
        configured_servers = {}
        for server in config.get('servers', []):
            docker_name = server.get('docker_name')
            if docker_name:
                configured_servers[docker_name] = server
                # Also add with 'name' as key for template compatibility
                display_name = server.get('name', docker_name)
                if display_name and display_name != docker_name:
                    configured_servers[display_name] = server

        # Load active containers
        load_active_containers_from_config()
        active_container_names = get_active_containers()

        # Debug output
        self.logger.debug(f"Selected servers in config: {config.get('selected_servers', [])}")
        self.logger.debug(f"Active container names for task form: {active_container_names}")

        return {
            'configured_servers': configured_servers,
            'active_container_names': active_container_names
        }

    def _process_timezone_configuration(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and process timezone configuration."""
        timezone_str = config.get('timezone', 'Europe/Berlin')

        try:
            # Validate timezone using zoneinfo first
            from zoneinfo import ZoneInfo
            ZoneInfo(timezone_str)
        except Exception as e:
            try:
                # Fallback to pytz
                import pytz
                pytz.timezone(timezone_str)
            except Exception as e2:
                self.logger.error(f"Invalid timezone {timezone_str}: {e2}")
                timezone_str = 'Europe/Berlin'

        return {
            'timezone_str': timezone_str,
            'current_timezone': config.get('selected_timezone', 'UTC')
        }

    def _process_cache_timestamps(self, timezone_str: str) -> Dict[str, Any]:
        """Format Docker cache timestamps with timezone."""
        from app.utils.web_helpers import docker_cache

        last_cache_update = docker_cache.get('timestamp')
        formatted_timestamp = "Never"

        if last_cache_update:
            try:
                import pytz
                tz = pytz.timezone(timezone_str)
                dt = datetime.fromtimestamp(last_cache_update, tz=tz)
                formatted_timestamp = dt.strftime('%Y-%m-%d %H:%M:%S %Z')
            except Exception as e:
                self.logger.error(f"Error formatting timestamp with timezone: {e}")
                formatted_timestamp = datetime.fromtimestamp(last_cache_update).strftime('%Y-%m-%d %H:%M:%S')

        # Try global_timestamp if timestamp failed
        if formatted_timestamp == "Never" and docker_cache.get('global_timestamp'):
            try:
                import pytz
                tz = pytz.timezone(timezone_str)
                dt = datetime.fromtimestamp(docker_cache['global_timestamp'], tz=tz)
                formatted_timestamp = dt.strftime('%Y-%m-%d %H:%M:%S %Z')
                self.logger.debug(f"Using global_timestamp for container list update time: {formatted_timestamp}")
            except Exception as e:
                self.logger.error(f"Error formatting global_timestamp: {e}")
                formatted_timestamp = datetime.fromtimestamp(docker_cache['global_timestamp']).strftime('%Y-%m-%d %H:%M:%S')

        return {
            'last_cache_update': last_cache_update,
            'formatted_timestamp': formatted_timestamp,
            'docker_cache': docker_cache
        }

    def _process_scheduled_tasks(self, config: Dict[str, Any], timezone_str: str) -> Dict[str, Any]:
        """Load and format scheduled tasks with timezone conversion."""
        from services.scheduling.scheduler import load_tasks

        tasks_list = load_tasks()
        tasks_list.sort(key=lambda t: t.next_run_ts if t.next_run_ts else float('inf'))

        formatted_tasks = []
        for task in tasks_list:
            # Format timestamps with timezone
            next_run = self._format_task_timestamp(task.next_run_ts, timezone_str)
            last_run = self._format_task_timestamp(task.last_run_ts, timezone_str)

            # Process cycle information
            cycle_info = self._format_cycle_info(task)

            # Find container display name
            display_name = self._find_container_display_name(task.container_name, config)

            # Process last run result
            last_run_result = self._format_last_run_result(task)

            formatted_tasks.append({
                'id': task.task_id,
                'container_name': task.container_name,
                'display_name': display_name,
                'action': task.action,
                'cycle': task.cycle,
                'cycle_info': cycle_info,
                'next_run': next_run,
                'last_run': last_run,
                'created_by': task.created_by or "Unknown",
                'is_active': task.next_run_ts is not None,
                'last_run_result': last_run_result,
                'last_run_success': task.last_run_success
            })

        return {'formatted_tasks': formatted_tasks}

    def _format_task_timestamp(self, timestamp: Optional[float], timezone_str: str) -> Optional[str]:
        """Format task timestamp with timezone conversion."""
        if not timestamp:
            return None

        try:
            dt = datetime.utcfromtimestamp(timestamp)
            if timezone_str:
                import pytz
                tz = pytz.timezone(timezone_str)
                dt = dt.replace(tzinfo=pytz.UTC).astimezone(tz)
            return dt.strftime("%Y-%m-%d %H:%M %Z")
        except Exception as e:
            self.logger.error(f"Error formatting task timestamp: {e}")
            return None

    def _format_cycle_info(self, task) -> str:
        """Format task cycle information for display."""
        cycle_info = task.cycle

        if task.cycle == "weekly" and task.weekday_val is not None:
            day_name = DAYS_OF_WEEK[task.weekday_val] if 0 <= task.weekday_val < len(DAYS_OF_WEEK) else f"Day {task.weekday_val}"
            cycle_info = f"Weekly ({day_name})"
        elif task.cycle == "monthly" and task.day_val is not None:
            cycle_info = f"Monthly (Day {task.day_val})"
        elif task.cycle == "yearly" and task.month_val is not None and task.day_val is not None:
            month_display = task.month_val
            if isinstance(month_display, int) and 1 <= month_display <= 12:
                month_names = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
                month_display = month_names[month_display - 1]
            cycle_info = f"Yearly ({month_display} {task.day_val})"
        elif task.cycle == "daily":
            cycle_info = "Daily"
        elif task.cycle == "once":
            cycle_info = "Once"

        return cycle_info

    def _find_container_display_name(self, container_name: str, config: Dict[str, Any]) -> str:
        """Find display name for container from configuration."""
        for server in config.get('servers', []):
            if server.get('docker_name') == container_name:
                return server.get('name', container_name)
        return container_name

    def _format_last_run_result(self, task) -> str:
        """Format last run result for display."""
        if task.last_run_success is None:
            return "Not run yet"
        elif task.last_run_success:
            return "Success"
        else:
            return f"Failed: {task.last_run_error or 'Unknown error'}"

    def _load_container_info(self, live_containers: List[Dict[str, Any]], config: Dict[str, Any]) -> Dict[str, Any]:
        """Load container info from JSON files."""
        from app.utils.container_info_web_handler import load_container_info_for_web

        # Use live containers if available, otherwise fall back to configured servers
        if live_containers:
            container_names = [container.get("name", "Unknown") for container in live_containers]
        else:
            container_names = [server.get("docker_name", server.get("name", "Unknown")) for server in config.get('servers', [])]

        return load_container_info_for_web(container_names)

    def _prepare_advanced_settings(self, config: Dict[str, Any]) -> Dict[str, str]:
        """Prepare advanced settings with config and environment fallbacks."""
        advanced_settings = config.get('advanced_settings', {})

        def get_setting_value(key: str, default: str = '') -> str:
            """Get setting value from config first, then environment, then default."""
            if key in advanced_settings:
                return str(advanced_settings[key])
            env_value = os.getenv(key, default)
            return env_value if env_value else default

        return {
            'DDC_DOCKER_CACHE_DURATION': get_setting_value('DDC_DOCKER_CACHE_DURATION', '30'),
            'DDC_DOCKER_QUERY_COOLDOWN': get_setting_value('DDC_DOCKER_QUERY_COOLDOWN', '2'),
            'DDC_DOCKER_MAX_CACHE_AGE': get_setting_value('DDC_DOCKER_MAX_CACHE_AGE', '300'),
            'DDC_ENABLE_BACKGROUND_REFRESH': get_setting_value('DDC_ENABLE_BACKGROUND_REFRESH', 'true'),
            'DDC_BACKGROUND_REFRESH_INTERVAL': get_setting_value('DDC_BACKGROUND_REFRESH_INTERVAL', '30'),
            'DDC_BACKGROUND_REFRESH_LIMIT': get_setting_value('DDC_BACKGROUND_REFRESH_LIMIT', '50'),
            'DDC_BACKGROUND_REFRESH_TIMEOUT': get_setting_value('DDC_BACKGROUND_REFRESH_TIMEOUT', '30'),
            'DDC_MAX_CONTAINERS_DISPLAY': get_setting_value('DDC_MAX_CONTAINERS_DISPLAY', '100'),
            'DDC_SCHEDULER_CHECK_INTERVAL': get_setting_value('DDC_SCHEDULER_CHECK_INTERVAL', '120'),
            'DDC_MAX_CONCURRENT_TASKS': get_setting_value('DDC_MAX_CONCURRENT_TASKS', '3'),
            'DDC_TASK_BATCH_SIZE': get_setting_value('DDC_TASK_BATCH_SIZE', '5'),
            'DDC_LIVE_LOGS_REFRESH_INTERVAL': get_setting_value('DDC_LIVE_LOGS_REFRESH_INTERVAL', '5'),
            'DDC_LIVE_LOGS_MAX_REFRESHES': get_setting_value('DDC_LIVE_LOGS_MAX_REFRESHES', '12'),
            'DDC_LIVE_LOGS_TAIL_LINES': get_setting_value('DDC_LIVE_LOGS_TAIL_LINES', '50'),
            'DDC_LIVE_LOGS_TIMEOUT': get_setting_value('DDC_LIVE_LOGS_TIMEOUT', '120'),
            'DDC_LIVE_LOGS_ENABLED': get_setting_value('DDC_LIVE_LOGS_ENABLED', 'true'),
            'DDC_LIVE_LOGS_AUTO_START': get_setting_value('DDC_LIVE_LOGS_AUTO_START', 'false'),
            'DDC_FAST_STATS_TIMEOUT': get_setting_value('DDC_FAST_STATS_TIMEOUT', '10'),
            'DDC_SLOW_STATS_TIMEOUT': get_setting_value('DDC_SLOW_STATS_TIMEOUT', '30'),
            'DDC_CONTAINER_LIST_TIMEOUT': get_setting_value('DDC_CONTAINER_LIST_TIMEOUT', '15')
        }

    def _load_donation_settings(self) -> Dict[str, Any]:
        """Load donation-related settings."""
        try:
            from services.donation.donation_utils import is_donations_disabled
            from services.donation.donation_config import get_donation_disable_key

            return {
                'donations_disabled': is_donations_disabled(),
                'current_donation_key': get_donation_disable_key() or ''
            }
        except Exception as e:
            self.logger.warning(f"Could not load donation settings: {e}")
            return {
                'donations_disabled': False,
                'current_donation_key': ''
            }

    def _get_default_configuration(self) -> Dict[str, Any]:
        """Get default configuration for template compatibility."""
        try:
            from services.config.config_service import get_config_service
            config_service = get_config_service()
            return {
                'default_channel_permissions': config_service._get_default_channels_config()['default_channel_permissions']
            }
        except Exception as e:
            self.logger.warning(f"Could not get default configuration: {e}")
            return {'default_channel_permissions': {}}

    def _assemble_template_data(self, config: Dict[str, Any], timestamp: str, docker_data: Dict[str, Any],
                               server_data: Dict[str, Any], timezone_data: Dict[str, Any],
                               cache_data: Dict[str, Any], tasks_data: Dict[str, Any],
                               container_info: Dict[str, Any], advanced_settings: Dict[str, str],
                               donation_settings: Dict[str, Any], default_config: Dict[str, Any]) -> Dict[str, Any]:
        """Assemble final template data dictionary."""
        # Create config with environment variables
        config_with_env = config.copy()
        config_with_env['env'] = advanced_settings
        config_with_env['donation_disable_key'] = donation_settings['current_donation_key']

        return {
            'config': config_with_env,
            'DEFAULT_CONFIG': default_config,
            'donations_disabled': donation_settings['donations_disabled'],
            'common_timezones': COMMON_TIMEZONES,
            'current_timezone': timezone_data['current_timezone'],
            'all_containers': docker_data['live_containers'],
            'configured_servers': server_data['configured_servers'],
            'active_container_names': server_data['active_container_names'],
            'container_info_data': container_info,
            'cache_error': docker_data['cache_error'],
            'docker_cache': cache_data['docker_cache'],
            'last_cache_update': cache_data['last_cache_update'],
            'formatted_timestamp': cache_data['formatted_timestamp'],
            'auto_refresh_interval': config.get('auto_refresh_interval', 30),
            'version_tag': timestamp,
            'show_clear_logs_button': config.get('show_clear_logs_button', True),
            'show_download_logs_button': config.get('show_download_logs_button', True),
            'tasks': tasks_data['formatted_tasks']
        }


# Singleton instance
_configuration_page_service = None


def get_configuration_page_service() -> ConfigurationPageService:
    """Get the singleton ConfigurationPageService instance."""
    global _configuration_page_service
    if _configuration_page_service is None:
        _configuration_page_service = ConfigurationPageService()
    return _configuration_page_service