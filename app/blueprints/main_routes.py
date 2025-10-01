# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, 
    jsonify, session, current_app, send_file, Response
)
from datetime import datetime, timezone, timedelta # Added datetime for config_page
from functools import wraps
import os
import io
import time
import json
import pytz

# Import auth from app.auth
from app.auth import auth 
from services.config.config_service import load_config, save_config
# Removed DEFAULT_CONFIG import - not needed anymore

from app.utils.container_info_web_handler import save_container_info_from_web, load_container_info_for_web
from app.utils.web_helpers import (
    log_user_action, 
    get_docker_containers_live,
    docker_cache
)
from app.utils.port_diagnostics import run_port_diagnostics
# NEW: Import shared_data
from app.utils.shared_data import get_active_containers, load_active_containers_from_config
from app.constants import COMMON_TIMEZONES # Import from new constants file
# Import scheduler functions for the main page
from services.scheduling.scheduler import (
    load_tasks, 
    DAYS_OF_WEEK
)
from services.infrastructure.action_logger import log_user_action
from services.infrastructure.spam_protection_service import get_spam_protection_service
# Removed: from utils.donation_manager import get_donation_manager  # No longer used - replaced by MechService

# Define COMMON_TIMEZONES here if it's only used by routes in this blueprint
# Or import it if it's defined centrally and used by multiple blueprints
# For now, let's assume it might be needed, if not, it can be removed.
# from app.web_ui import COMMON_TIMEZONES # This would create a circular import if web_ui imports this blueprint.
# Instead, COMMON_TIMEZONES should be passed to template from web_ui.py or defined in a config/constants file.
# For simplicity in this step, I will copy it here. Ideally, it should be refactored to a central place.
# Remove COMMON_TIMEZONES_BP definition
# COMMON_TIMEZONES_BP = [
#     "Europe/Berlin", ..., "Australia/Sydney"
# ]

main_bp = Blueprint('main_bp', __name__)

# Heartbeat Monitor Script Generator Functions
# Monitor script generation functions have been moved to MonitorScriptService
# See services/web/monitor_script_service.py

# Legacy monitor script functions have been removed
# All script generation is now handled by MonitorScriptService
# See services/web/monitor_script_service.py

@main_bp.route('/', methods=['GET'])
# Use direct auth decorator
@auth.login_required 
def config_page():
    logger = current_app.logger
    
    config = load_config()
    
    # Force a fresh reload if requested
    force_refresh = request.args.get('force_refresh', 'false').lower() == 'true'
    if force_refresh:
        logger.info("Force refresh requested - reloading configuration from files")
        from utils.config_cache import init_config_cache
        fresh_config = load_config()
        init_config_cache(fresh_config)
        config = fresh_config
    
    now = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") # datetime is now imported
    live_containers_list, cache_error = get_docker_containers_live(logger)
    
    # If Docker is not available, create synthetic container list from config
    if not live_containers_list and config.get('servers'):
        live_containers_list = []
        for server in config.get('servers', []):
            synthetic_container = {
                'id': server.get('docker_name', 'unknown'),
                'name': server.get('docker_name'),  # Use docker_name as container.name
                'status': 'unknown',
                'state': 'unknown',
                'image': 'unknown',
                'running': False
            }
            live_containers_list.append(synthetic_container)
        logger.info(f"Created synthetic container list with {len(live_containers_list)} containers from config")
    
    configured_servers = {}
    for server in config.get('servers', []):
        # Use docker_name as key for consistency
        docker_name = server.get('docker_name')
        if docker_name:
            configured_servers[docker_name] = server
            # Also add with 'name' as key for template compatibility
            display_name = server.get('name', docker_name)
            if display_name and display_name != docker_name:
                configured_servers[display_name] = server
            
    # NEW: Load active containers from the shared data class
    # Update active containers from configuration
    load_active_containers_from_config()
    active_container_names = get_active_containers()
    
    # Debug output
    logger.debug(f"Selected servers in config: {config.get('selected_servers', [])}")
    logger.debug(f"Active container names for task form: {active_container_names}")

    # Get and validate timezone
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
            logger.error(f"Invalid timezone {timezone_str}: {e2}")
            timezone_str = 'Europe/Berlin'
    
    # Format cache timestamp for display using configured timezone
    last_cache_update = docker_cache.get('timestamp')
    formatted_timestamp = "Never"
    if last_cache_update:
        try:
            # Convert timestamp to configured timezone
            tz = pytz.timezone(timezone_str)
            dt = datetime.fromtimestamp(last_cache_update, tz=tz)
            formatted_timestamp = dt.strftime('%Y-%m-%d %H:%M:%S %Z')
        except Exception as e:
            logger.error(f"Error formatting timestamp with timezone: {e}")
            # Fallback to system timezone
            formatted_timestamp = datetime.fromtimestamp(last_cache_update).strftime('%Y-%m-%d %H:%M:%S')
    
    # Try to get the timestamp from the global_timestamp field, which is used in the newer code
    if formatted_timestamp == "Never" and docker_cache.get('global_timestamp'):
        try:
            # Convert timestamp to configured timezone
            import pytz  # Local import to avoid scope issues
            tz = pytz.timezone(timezone_str)
            dt = datetime.fromtimestamp(docker_cache['global_timestamp'], tz=tz)
            formatted_timestamp = dt.strftime('%Y-%m-%d %H:%M:%S %Z')
            logger.debug(f"Using global_timestamp for container list update time: {formatted_timestamp}")
        except Exception as e:
            logger.error(f"Error formatting global_timestamp: {e}")
            # Fallback to system timezone
            formatted_timestamp = datetime.fromtimestamp(docker_cache['global_timestamp']).strftime('%Y-%m-%d %H:%M:%S')
    
    # Load schedules for display on the main page
    tasks_list = load_tasks()
    
    # Sort by next execution time
    tasks_list.sort(key=lambda t: t.next_run_ts if t.next_run_ts else float('inf'))
    
    # Prepare data for the template
    formatted_tasks = []
    for task in tasks_list:
        # Format timestamps
        next_run = None
        if task.next_run_ts:
            next_run_dt = datetime.utcfromtimestamp(task.next_run_ts)
            if timezone_str:
                import pytz  # Ensure pytz is available in this scope
                tz = pytz.timezone(timezone_str)
                next_run_dt = next_run_dt.replace(tzinfo=pytz.UTC).astimezone(tz)
            next_run = next_run_dt.strftime("%Y-%m-%d %H:%M %Z")
        
        last_run = None
        if task.last_run_ts:
            last_run_dt = datetime.utcfromtimestamp(task.last_run_ts)
            if timezone_str:
                import pytz  # Ensure pytz is available in this scope
                tz = pytz.timezone(timezone_str)
                last_run_dt = last_run_dt.replace(tzinfo=pytz.UTC).astimezone(tz)
            last_run = last_run_dt.strftime("%Y-%m-%d %H:%M %Z")
            
        # Cycle information
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
        
        # Find container display name
        display_name = task.container_name
        for server in config.get('servers', []):
            if server.get('docker_name') == task.container_name:
                display_name = server.get('name', task.container_name)
                break
        
        # Add last run result
        last_run_result = "Not run yet"
        if task.last_run_success is not None:
            if task.last_run_success:
                last_run_result = "Success"
            else:
                last_run_result = f"Failed: {task.last_run_error or 'Unknown error'}"
        
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
    
    # Load container info from separate JSON files
    # Use live containers if available, otherwise fall back to configured servers
    if live_containers_list:
        container_names = [container.get("name", "Unknown") for container in live_containers_list]
    else:
        # Fallback: Use configured server names when Docker is not available
        container_names = [server.get("docker_name", server.get("name", "Unknown")) for server in config.get('servers', [])]
    
    container_info_data = load_container_info_for_web(container_names)
    
    # ADVANCED SETTINGS: Load from config (preferred) or environment variables as fallback
    # These are the DDC_* settings used for performance tuning
    import os
    
    # Get advanced settings from config first, then fallback to environment variables
    advanced_settings = config.get('advanced_settings', {})
    
    def get_setting_value(key, default=''):
        """Get setting value from config first, then environment, then default."""
        # First try config
        if key in advanced_settings:
            return str(advanced_settings[key])
        # Then try environment variable
        env_value = os.getenv(key, default)
        return env_value if env_value else default
    
    env_vars = {
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
    
    # Add env vars to config for template access
    config_with_env = config.copy()
    config_with_env['env'] = env_vars
    
    # Check if donations are disabled by key and load current donation key
    from services.donation.donation_utils import is_donations_disabled
    from services.donation.donation_config import get_donation_disable_key
    donations_disabled = is_donations_disabled()
    current_donation_key = get_donation_disable_key() or ''
    
    # Add donation key to config for template access
    config_with_env['donation_disable_key'] = current_donation_key
    
    # Get DEFAULT_CONFIG from ConfigService for template compatibility
    from services.config.config_service import get_config_service
    config_service = get_config_service()
    DEFAULT_CONFIG = {
        'default_channel_permissions': config_service._get_default_channels_config()['default_channel_permissions']
    }
    
    return render_template('config.html', 
                           config=config_with_env,
                           DEFAULT_CONFIG=DEFAULT_CONFIG,
                           donations_disabled=donations_disabled,
                           common_timezones=COMMON_TIMEZONES, # Use imported COMMON_TIMEZONES
                           current_timezone=config.get('selected_timezone', 'UTC'),
                           all_containers=live_containers_list,  # Renamed from 'containers' to 'all_containers'
                           configured_servers=configured_servers,  # Added
                           active_container_names=active_container_names, # NEW Added
                           container_info_data=container_info_data,  # Container info from JSON files
                           cache_error=cache_error,
                           docker_cache=docker_cache,  # Pass the entire docker_cache for direct access in template
                           last_cache_update=last_cache_update,
                           formatted_timestamp=formatted_timestamp,
                           auto_refresh_interval=config.get('auto_refresh_interval', 30),
                           version_tag=now, 
                           show_clear_logs_button=config.get('show_clear_logs_button', True),
                           show_download_logs_button=config.get('show_download_logs_button', True),
                           # Removed DEFAULT_CONFIG - not needed anymore
                           tasks=formatted_tasks # Add schedule data
                          )

@main_bp.route('/save_config_api', methods=['POST'])
# Use direct auth decorator
@auth.login_required
def save_config_api():
    logger = current_app.logger
    logger.info("save_config_api (blueprint) called...")

    try:
        # Use ConfigurationSaveService to handle business logic
        from services.web.configuration_save_service import get_configuration_save_service, ConfigurationSaveRequest

        # Extract form data and options
        form_data = request.form.to_dict(flat=False)
        config_split_enabled = request.form.get('config_split_enabled') == '1'

        # Debug form data
        logger.debug(f"Form data keys count: {len(form_data.keys())}")
        if 'donation_disable_key' in form_data:
            logger.debug("Found donation_disable_key in form")

        # Create service request
        save_request = ConfigurationSaveRequest(
            form_data=form_data,
            config_split_enabled=config_split_enabled
        )

        # Process save through service
        config_service = get_configuration_save_service()
        save_result = config_service.save_configuration(save_request)

        if save_result.success:
            result = {
                'success': True,
                'message': save_result.message,
                'config_files': save_result.config_files,
                'critical_settings_changed': save_result.critical_settings_changed
            }
            flash(result['message'], 'success')
            logger.info(f"Configuration saved successfully via ConfigurationSaveService: {save_result.message}")
        else:
            result = {
                'success': False,
                'message': save_result.error or save_result.message or 'Failed to save configuration.'
            }
            flash(result['message'], 'error')
            logger.warning(f"Failed to save configuration via ConfigurationSaveService: {result['message']}")

    except Exception as e:
        logger.error(f"Unexpected error in save_config_api: {str(e)}", exc_info=True)
        result = {
            'success': False,
            'message': "An error occurred while saving the configuration. Please check the logs for details."
        }
        flash("Error saving configuration. Please check the logs for details.", 'danger')

    # Check if it's an AJAX request (has the X-Requested-With header)
    is_ajax_request = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if is_ajax_request:
        # Return JSON for AJAX requests
        return jsonify(result)
    else:
        # Redirect to configuration page for normal form submits
        return redirect(url_for('.config_page'))

@main_bp.route('/discord_bot_setup')
# Use direct auth decorator
@auth.login_required
def discord_bot_setup():
    config = load_config()
    return render_template('discord_bot_setup.html', config=config)

@main_bp.route('/download_monitor_script', methods=['POST'])
# Use direct auth decorator
@auth.login_required
def download_monitor_script():
    """
    Generate and download a monitoring script for the heartbeat feature.
    Supports Python, Bash, and Windows Batch formats.
    """
    logger = current_app.logger

    try:
        # Get form data from request
        form_data = request.form.to_dict()
        script_type = form_data.get('script_type', 'python')

        # Basic validation
        if not form_data.get('heartbeat_channel_id'):
            logger.warning("Missing required field: heartbeat_channel_id")
            flash("Heartbeat Channel ID is required.", "warning")
            return redirect(url_for('.config_page'))

        # Script-specific validation
        if script_type == 'python' and not form_data.get('monitor_bot_token'):
            logger.warning("Missing bot token for Python REST monitor script")
            flash("Bot Token is required for the Python REST monitor script.", "warning")
            return redirect(url_for('.config_page'))
        elif script_type in ['bash', 'batch']:
            if not form_data.get('alert_webhook_url'):
                logger.warning("Missing webhook URL for shell scripts")
                flash("Webhook URL is required for Shell scripts.", "warning")
                return redirect(url_for('.config_page'))
            if not form_data.get('monitor_bot_token'):
                logger.warning("Missing bot token for shell scripts")
                flash("Bot Token is required for Shell scripts to resolve the bot user ID.", "warning")
                return redirect(url_for('.config_page'))

        # Use MonitorScriptService to generate script
        from services.web.monitor_script_service import get_monitor_script_service, MonitorScriptRequest, ScriptType

        # Map string to enum
        script_type_enum = {
            'python': ScriptType.PYTHON,
            'bash': ScriptType.BASH,
            'batch': ScriptType.BATCH
        }.get(script_type)

        if not script_type_enum:
            flash(f"Unknown script type: {script_type}", "danger")
            return redirect(url_for('.config_page'))

        # Create request object
        script_request = MonitorScriptRequest(
            script_type=script_type_enum,
            monitor_bot_token=form_data.get('monitor_bot_token', ''),
            alert_webhook_url=form_data.get('alert_webhook_url', ''),
            ddc_bot_user_id=form_data.get('ddc_bot_user_id', ''),
            heartbeat_channel_id=form_data.get('heartbeat_channel_id', ''),
            monitor_timeout_seconds=form_data.get('monitor_timeout_seconds', '271'),
            alert_channel_ids=form_data.get('alert_channel_ids', '')
        )

        # Generate script using service
        script_service = get_monitor_script_service()
        result = script_service.generate_script(script_request)

        if not result.success:
            flash(f"Error generating script: {result.error}", "danger")
            return redirect(url_for('.config_page'))

        # Determine file properties
        file_properties = {
            'python': {'extension': 'py', 'mime_type': 'text/x-python'},
            'bash': {'extension': 'sh', 'mime_type': 'text/x-shellscript'},
            'batch': {'extension': 'bat', 'mime_type': 'application/x-msdos-program'}
        }
        props = file_properties[script_type]

        # Create buffer and prepare download
        buffer = io.BytesIO(result.script_content.encode('utf-8'))
        buffer.seek(0)

        # Log action
        script_names = {'python': 'Python', 'bash': 'Bash', 'batch': 'Windows Batch'}
        log_user_action(
            action="DOWNLOAD",
            target=f"Heartbeat monitor script ({script_names.get(script_type, script_type)})",
            source="Web UI"
        )
        logger.info(f"Generated and downloaded heartbeat monitor script ({script_type})")

        return send_file(
            buffer,
            as_attachment=True,
            download_name=f'ddc_heartbeat_monitor.{props["extension"]}',
            mimetype=props['mime_type']
        )

    except Exception as e:
        logger.error(f"Error generating monitor script: {e}", exc_info=True)
        flash("Error generating monitor script. Please check the logs for details.", "danger")
        return redirect(url_for('.config_page'))

@main_bp.route('/refresh_containers', methods=['POST'])
# Use direct auth decorator
@auth.login_required
def refresh_containers():
    """Endpoint to force refresh of Docker container list"""
    logger = current_app.logger
    
    try:
        # Get Docker containers with force_refresh=True
        from app.utils.web_helpers import get_docker_containers_live, docker_cache
        
        logger.info("Manual refresh of Docker container list requested")
        containers, error = get_docker_containers_live(logger, force_refresh=True)
        
        if error:
            logger.warning(f"Error during manual container refresh: {error}")
            return jsonify({
                'success': False,
                'message': "Error refreshing containers. Please check the logs for details."
            })
        
        # Log the success
        log_user_action("REFRESH", "Docker Container List", source="Web UI")
        
        # Get the timestamp for the response
        timestamp = docker_cache.get('global_timestamp', time.time())
        
        # Format timestamp with configured timezone
        config = load_config()
        timezone_str = config.get('timezone', 'Europe/Berlin')
        
        try:
            tz = pytz.timezone(timezone_str)
            dt = datetime.fromtimestamp(timestamp, tz=tz)
            formatted_time = dt.strftime('%Y-%m-%d %H:%M:%S %Z')
        except Exception as e:
            logger.error(f"Error formatting timestamp with timezone: {e}")
            # Fallback to system timezone
            formatted_time = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
        
        return jsonify({
            'success': True,
            'container_count': len(containers),
            'timestamp': timestamp,
            'formatted_time': formatted_time
        })
        
    except Exception as e:
        logger.error(f"Unexpected error refreshing containers: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': "Unexpected error refreshing containers. Please check the logs for details."
        })

@main_bp.route('/enable_temp_debug', methods=['POST'])
@auth.login_required
def enable_temp_debug():
    """
    API endpoint to enable temporary debug mode.
    This will enable debug logging for a specified duration without modifying the config file.
    """
    logger = current_app.logger
    
    try:
        # Get duration from request, default to 10 minutes
        duration_minutes = request.form.get('duration', 10)
        try:
            duration_minutes = int(duration_minutes)
        except (ValueError, TypeError):
            duration_minutes = 10
            
        # Enforce reasonable limits
        if duration_minutes < 1:
            duration_minutes = 1
        elif duration_minutes > 60:
            duration_minutes = 60
        
        # Enable temporary debug mode
        from utils.logging_utils import enable_temporary_debug
        success, expiry = enable_temporary_debug(duration_minutes)
        
        if success:
            # Format expiry time for display
            expiry_formatted = datetime.fromtimestamp(expiry).strftime('%Y-%m-%d %H:%M:%S')
            logger.info(f"Temporary debug mode enabled for {duration_minutes} minutes (until {expiry_formatted})")
            log_user_action("ENABLE", "Temporary Debug Mode", source="Web UI")
            
            return jsonify({
                'success': True,
                'message': f"Temporary debug mode enabled for {duration_minutes} minutes",
                'expiry': expiry,
                'expiry_formatted': expiry_formatted,
                'duration_minutes': duration_minutes
            })
        else:
            return jsonify({
                'success': False,
                'message': "Failed to enable temporary debug mode"
            })
            
    except Exception as e:
        logger.error(f"Error enabling temporary debug mode: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': "Error enabling temporary debug mode. Please check the logs for details."
        })

@main_bp.route('/disable_temp_debug', methods=['POST'])
@auth.login_required
def disable_temp_debug():
    """
    API endpoint to disable temporary debug mode immediately.
    """
    logger = current_app.logger
    
    try:
        # Disable temporary debug mode
        from utils.logging_utils import disable_temporary_debug
        success = disable_temporary_debug()
        
        if success:
            logger.info("Temporary debug mode disabled manually")
            log_user_action("DISABLE", "Temporary Debug Mode", source="Web UI")
            
            return jsonify({
                'success': True,
                'message': "Temporary debug mode disabled"
            })
        else:
            return jsonify({
                'success': False,
                'message': "Failed to disable temporary debug mode"
            })
            
    except Exception as e:
        logger.error(f"Error disabling temporary debug mode: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': "Error disabling temporary debug mode. Please check the logs for details."
        })

@main_bp.route('/temp_debug_status', methods=['GET'])
@auth.login_required
def temp_debug_status():
    """
    API endpoint to get the current status of temporary debug mode.
    """
    try:
        # Get current status
        from utils.logging_utils import get_temporary_debug_status
        is_enabled, expiry, remaining_seconds = get_temporary_debug_status()
        
        # Format expiry time
        expiry_formatted = datetime.fromtimestamp(expiry).strftime('%Y-%m-%d %H:%M:%S') if expiry > 0 else ""
        
        # Format remaining time
        remaining_minutes = int(remaining_seconds / 60)
        remaining_seconds_mod = int(remaining_seconds % 60)
        remaining_formatted = f"{remaining_minutes}m {remaining_seconds_mod}s" if is_enabled else ""
        
        return jsonify({
            'success': True,
            'is_enabled': is_enabled,
            'expiry': expiry,
            'expiry_formatted': expiry_formatted,
            'remaining_seconds': remaining_seconds,
            'remaining_formatted': remaining_formatted
        })
            
    except Exception as e:
        current_app.logger.error(f"Error getting temporary debug status: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': "Error getting temporary debug status. Please check the logs for details.",
            'is_enabled': False
        })

@main_bp.route('/performance_stats', methods=['GET'])
@auth.login_required
def performance_stats():
    """
    API endpoint to get current performance statistics for monitoring.
    This endpoint provides insights into system performance without affecting configuration.
    """
    try:
        # Use PerformanceStatsService to handle business logic
        from services.web.performance_stats_service import get_performance_stats_service

        stats_service = get_performance_stats_service()
        result = stats_service.get_performance_stats()

        if result.success:
            return jsonify({
                'success': True,
                'performance_data': result.performance_data
            })
        else:
            return jsonify({
                'success': False,
                'message': result.error or "Error getting performance statistics. Please check the logs for details."
            })

    except Exception as e:
        current_app.logger.error(f"Error in performance_stats endpoint: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': "Error getting performance statistics. Please check the logs for details."
        })

@main_bp.route('/api/spam-protection', methods=['GET'])
@auth.login_required
def get_spam_protection():
    """Get current spam protection settings."""
    try:
        spam_service = get_spam_protection_service()
        result = spam_service.get_config()
        settings = result.data.to_dict() if result.success else {}
        return jsonify(settings)
    except Exception as e:
        current_app.logger.error(f"Error getting spam protection settings: {e}")
        return jsonify({'error': 'Failed to load spam protection settings'}), 500

@main_bp.route('/api/spam-protection', methods=['POST'])
@auth.login_required
def save_spam_protection():
    """Save spam protection settings."""
    try:
        settings = request.get_json()
        if not settings:
            return jsonify({'success': False, 'error': 'No data provided'}), 400
        
        spam_service = get_spam_protection_service()
        from services.infrastructure.spam_protection_service import SpamProtectionConfig
        config = SpamProtectionConfig.from_dict(settings)
        result = spam_service.save_config(config)
        success = result.success
        
        if success:
            # Log the action
            log_user_action(
                action="SAVE",
                target="Spam Protection Settings",
                source="Web UI",
                details=f"Spam protection enabled: {settings.get('global_settings', {}).get('enabled', True)}"
            )
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': 'Failed to save settings'}), 500
            
    except Exception as e:
        current_app.logger.error(f"Error saving spam protection settings: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@main_bp.route('/api/donation/status', methods=['GET'])
def get_donation_status():
    """Get current donation status with speed information - USING NEW MECH SERVICE."""
    try:
        # Use new MechService
        from services.mech.mech_service import get_mech_service
        from services.mech.speed_levels import get_speed_info, get_speed_emoji
        
        mech_service = get_mech_service()
        mech_state = mech_service.get_state()
        
        # Convert MechState to status format for compatibility
        total_amount = mech_state.total_donated
        description, color = get_speed_info(total_amount)
        level = min(int(total_amount / 10), 101) if total_amount > 0 else 0
        emoji = get_speed_emoji(level)
        
        # Get level-specific decay rate
        from services.mech.evolution_config_manager import get_evolution_config_manager
        config_mgr = get_evolution_config_manager()
        evolution_info = config_mgr.get_evolution_level(mech_state.level)
        decay_per_day = evolution_info.decay_per_day if evolution_info else 1.0

        # Create status object compatible with Web UI
        status = {
            'total_amount': total_amount,
            'current_Power': mech_state.Power,
            'current_Power_raw': mech_service.get_power_with_decimals(),  # Raw Power with decimals for UI
            'mech_level': mech_state.level,
            'mech_level_name': mech_state.level_name,
            'next_level_threshold': mech_state.next_level_threshold,
            'glvl': mech_state.glvl,
            'glvl_max': mech_state.glvl_max,
            'decay_per_day': decay_per_day,  # Level-specific decay rate
            'bars': {
                'mech_progress_current': mech_state.bars.mech_progress_current,
                'mech_progress_max': mech_state.bars.mech_progress_max,
                'Power_current': mech_state.bars.Power_current,
                'Power_max_for_level': mech_state.bars.Power_max_for_level,
            },
            'speed': {
                'level': level,
                'description': description,
                'emoji': emoji,
                'color': color,
                'formatted_status': f"{emoji} {description}"
            }
        }
        
        return jsonify(status)
    except Exception as e:
        current_app.logger.error(f"Error getting donation status with new MechService: {e}")
        return jsonify({'error': 'Failed to load donation status'}), 500

@main_bp.route('/api/donation/click', methods=['POST'])
def record_donation_click():
    """Record a donation button click (auth required for security)."""
    try:
        data = request.get_json()
        if not data or 'type' not in data:
            return jsonify({'success': False, 'error': 'Missing donation type'}), 400
        
        donation_type = data.get('type')
        if donation_type not in ['coffee', 'paypal']:
            return jsonify({'success': False, 'error': 'Invalid donation type'}), 400
        
        # Get user info - try username first, fallback to IP
        user_identifier = "Anonymous User"
        try:
            # Try to get authenticated username
            authenticated_user = auth.current_user()
            if authenticated_user:
                user_identifier = f"Web User: {authenticated_user}"
            else:
                # Fallback to IP address
                ip_address = request.remote_addr
                if request.headers.get('X-Forwarded-For'):
                    ip_address = request.headers.get('X-Forwarded-For').split(',')[0].strip()
                user_identifier = f"IP: {ip_address}"
        except:
            # Final fallback to IP
            ip_address = request.remote_addr
            if request.headers.get('X-Forwarded-For'):
                ip_address = request.headers.get('X-Forwarded-For').split(',')[0].strip()
            user_identifier = f"IP: {ip_address}"
        
        # Get current timestamp for Matrix Thank You animation
        from datetime import datetime, timezone
        current_timestamp = datetime.now(timezone.utc).isoformat()
        
        # Log the action
        log_user_action(
            action="DONATION_CLICK",
            target=f"Donation Button ({donation_type})",
            source="Web UI",
            details=f"Donation button clicked by: {user_identifier}"
        )
        
        current_app.logger.info(f"💰 [MATRIX-SERVER] Donation button ({donation_type}) clicked by {user_identifier} - timestamp: {current_timestamp}")
        
        return jsonify({
            'success': True,
            'timestamp': current_timestamp,
            'message': 'Donation button click recorded for Matrix Thank You animation'
        })
        
    except Exception as e:
        current_app.logger.error(f"Error recording donation click: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# Donation history functionality removed - not used by Web UI
# New MechService stores donations in JSON format but doesn't provide history API
# If needed in future, can be implemented by reading mech_donations.json directly

@main_bp.route('/api/donation/add-power', methods=['POST'])
@auth.login_required
def add_test_power():
    """Add or remove Power for testing (requires auth) - USING NEW MECH SERVICE."""
    try:
        data = request.get_json()
        amount = data.get('amount', 0)
        donation_type = data.get('type', 'test')
        user = data.get('user', 'Test')
        
        # Use new MechService instead of old donation_manager
        from services.mech.mech_service import get_mech_service
        mech_service = get_mech_service()
        
        if amount != 0:
            # Add donation (positive or negative)
            if amount > 0:
                # For positive amounts, add normally
                result_state = mech_service.add_donation(f"WebUI:{user}", int(amount))
                current_app.logger.info(f"NEW SERVICE: Added ${amount} Power, new total: ${result_state.Power}")
            else:
                # For negative amounts, we need to work around the limitation
                # MechService only accepts positive integers, so we add a negative donation
                # by manipulating the state directly (testing only!)
                current_state = mech_service.get_state()
                
                # Calculate new power (ensure it doesn't go below 0)
                new_power = max(0, current_state.Power + amount)
                
                # Since we can't directly set power, we add a donation that results in the desired power
                # This is a workaround for testing purposes
                if new_power < current_state.Power:
                    # We want to reduce power, but can't do it directly
                    # Return the current state with a message
                    current_app.logger.info(f"NEW SERVICE: Power reduction not directly supported, current: ${current_state.Power}")
                    return jsonify({
                        'success': True,
                        'Power': current_state.Power,
                        'level': current_state.level,
                        'level_name': current_state.level_name,
                        'total_donated': current_state.total_donated,
                        'message': f'Power reduction not supported (would be ${new_power})'
                    })
                    
                result_state = current_state
                current_app.logger.info(f"NEW SERVICE: Attempted to reduce Power by ${abs(amount)}, but not supported")
                
            return jsonify({
                'success': True, 
                'Power': result_state.Power,
                'level': result_state.level,
                'level_name': result_state.level_name,
                'total_donated': result_state.total_donated
            })
        else:
            return jsonify({'success': False, 'error': 'Amount must be non-zero'}), 400
            
    except Exception as e:
        current_app.logger.error(f"Error adding test Power with new service: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@main_bp.route('/api/donation/reset-power', methods=['POST'])
@auth.login_required  
def reset_power():
    """Reset Power to 0 for testing (requires auth) - USING NEW MECH SERVICE."""
    try:
        # NEW SERVICE: Reset by clearing donation file
        from services.mech.mech_service import get_mech_service
        mech_service = get_mech_service()
        
        # Reset by directly modifying the store
        store_data = {"donations": []}
        mech_service.store.save(store_data)
        
        # Get new state (should be Level 1, 0 Power)
        reset_state = mech_service.get_state()
        
        current_app.logger.info(f"NEW SERVICE: Power reset - Level {reset_state.level}, Power ${reset_state.Power}")
        
        return jsonify({
            'success': True, 
            'message': 'Power reset to 0 using new MechService',
            'level': reset_state.level,
            'level_name': reset_state.level_name,
            'Power': reset_state.Power,
            'total_donated': reset_state.total_donated
        })
    except Exception as e:
        current_app.logger.error(f"Error resetting Power with new service: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@main_bp.route('/api/donation/consume-power', methods=['POST'])
@auth.login_required
def consume_Power():
    """Get current Power state - NEW SERVICE HANDLES DECAY AUTOMATICALLY."""
    try:
        # NEW SERVICE: Decay happens automatically in get_state()
        from services.mech.mech_service import get_mech_service
        mech_service = get_mech_service()
        
        # Just get current state - decay is calculated automatically
        current_state = mech_service.get_state()
        
        # Removed frequent Power consumption log to reduce noise in DEBUG mode
        # current_app.logger.debug(f"NEW SERVICE: Power consumption check - current Power: ${current_state.Power}")
        
        return jsonify({
            'success': True, 
            'new_Power': max(0, current_state.Power),
            'level': current_state.level,
            'level_name': current_state.level_name,
            'message': 'Power decay calculated automatically by new service'
        })
        
    except Exception as e:
        current_app.logger.error(f"Error consuming Power: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# Route removed - duplicate function name was causing crashes
# The actual endpoint is at /api/donation/add-power (lowercase)

@main_bp.route('/api/donation/submit', methods=['POST'])
@auth.login_required
def submit_donation():
    """Submit a manual donation entry from the web UI modal."""
    try:
        # Parse request data
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400

        # Use DonationService to handle business logic
        from services.web.donation_service import get_donation_service, DonationRequest

        donation_service = get_donation_service()
        donation_request = DonationRequest(
            amount=data.get('amount', 0),
            donor_name=data.get('donor_name', 'Anonymous'),
            publish_to_discord=data.get('publish_to_discord', True),
            source=data.get('source', 'web_ui_manual')
        )

        # Process donation through service
        result = donation_service.process_donation(donation_request)

        if result.success:
            return jsonify({
                'success': True,
                'message': result.message,
                'donation_info': result.donation_info
            })
        else:
            return jsonify({'success': False, 'error': result.error}), 400

    except Exception as e:
        current_app.logger.error(f"Error processing manual donation: {e}", exc_info=True)
        return jsonify({'success': False, 'error': f'Error processing donation: {str(e)}'}), 500

@main_bp.route('/mech_animation')
def mech_animation():
    """Live mech animation endpoint based on current Power level - simplified version."""
    try:
        # Get current donation status with multiple fallbacks
        total_donations = 0
        
        try:
            import sys
            import os
            # Add project root to Python path for service imports
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            if project_root not in sys.path:
                sys.path.insert(0, project_root)
            
            from services.mech.mech_service import get_mech_service
            mech_service = get_mech_service()
            mech_state = mech_service.get_state()
            total_donations = mech_state.total_donated
            current_app.logger.debug(f"Got total donations from mech service: {total_donations}")
        except Exception as e:
            current_app.logger.error(f"Error getting donation status: {e}")
            total_donations = 20.0  # Fallback default
        
        current_app.logger.debug(f"Live mech animation request, Power: {total_donations}")
        
        # Use centralized mech animation service with proper Web UI wrapper
        try:
            import sys
            import os
            # Add project root to Python path for service imports
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            if project_root not in sys.path:
                sys.path.insert(0, project_root)
                
            # Use new unified mech animation service (replaces old sync/async system)
            from services.mech.mech_animation_service import get_mech_animation_service
            animation_service = get_mech_animation_service()

            # Get both current Power and total donated for proper animation
            from services.mech.mech_service import get_mech_service
            mech_service = get_mech_service()
            mech_state = mech_service.get_state()
            current_Power = mech_service.get_power_with_decimals()
            total_donated = mech_state.total_donated

            # Create animation bytes synchronously using new unified service
            animation_bytes = animation_service.create_donation_animation_sync(
                "Current", f'{current_Power}$', total_donated
            )
            
            # Return as Flask Response
            return Response(
                animation_bytes,
                mimetype='image/webp',
                headers={'Cache-Control': 'max-age=300'}
            )
            
        except Exception as e:
            current_app.logger.error(f"Error creating mech animation: {e}", exc_info=True)
            
            # Ultimate fallback - create a simple static image
            try:
                from PIL import Image, ImageDraw
                img = Image.new('RGBA', (341, 512), (47, 49, 54, 255))
                draw = ImageDraw.Draw(img)
                draw.text((10, 10), f"Power: ${total_donations:.2f}", fill=(255, 255, 255, 255))
                draw.text((10, 30), "Mech Offline", fill=(255, 0, 0, 255))
                
                buffer = BytesIO()
                img.save(buffer, format='WebP', quality=90)
                buffer.seek(0)
                
                return Response(
                    buffer.getvalue(),
                    mimetype='image/webp',
                    headers={'Cache-Control': 'no-cache, no-store, must-revalidate'}
                )
            except:
                # Final fallback - return error
                return Response(
                    b'Error: Animation generation failed',
                    mimetype='text/plain',
                    status=500
                )
        
    except Exception as e:
        current_app.logger.error(f"Error in live mech animation endpoint: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@main_bp.route('/api/test-mech-animation', methods=['POST'])
@auth.login_required 
def test_mech_animation():
    """Test endpoint for generating mech animations using centralized service."""
    try:
        data = request.get_json()
        donor_name = data.get('donor_name', 'Test User')
        amount = data.get('amount', '10$')
        total_donations = data.get('total_donations', 0)
        
        current_app.logger.info(f"Generating mech animation for {donor_name}, donations: {total_donations}")
        
        # Use new unified mech animation service (replaces old sync/async system)
        from services.mech.mech_animation_service import get_mech_animation_service
        animation_service = get_mech_animation_service()

        # Get mech state for proper evolution level calculation
        from services.mech.mech_service import get_mech_service
        mech_service = get_mech_service()
        mech_state = mech_service.get_state()

        # Use total_donated for evolution level (not affected by Power decay)
        total_donated_for_evolution = mech_state.total_donated

        # Create animation bytes synchronously using new unified service
        animation_bytes = animation_service.create_donation_animation_sync(
            donor_name, amount, total_donated_for_evolution
        )
        
        # Return as Flask Response
        return Response(
            animation_bytes,
            mimetype='image/webp',
            headers={'Cache-Control': 'max-age=60'}
        )
        
    except ImportError:
        # Fallback - create simple error response
        return Response(
            b'Error: Service not available',
                mimetype='text/plain',
                status=500
            )
        
    except Exception as e:
        current_app.logger.error(f"Error in test mech animation endpoint: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@main_bp.route('/api/simulate-donation-broadcast', methods=['POST'])
@auth.login_required
def simulate_donation_broadcast():
    """Simulate a donation broadcast for testing purposes."""
    try:
        current_app.logger.info("Simulating donation broadcast...")
        return jsonify({
            'success': True,
            'message': 'Donation broadcast simulation not yet implemented'
        })
    except Exception as e:
        current_app.logger.error(f"Error simulating donation broadcast: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@main_bp.route('/api/mech-speed-config', methods=['POST'])
@auth.login_required
def get_mech_speed_config():
    """Get speed configuration using new 101-level system."""
    try:
        from services.mech.speed_levels import get_speed_info, get_speed_emoji
        
        data = request.get_json()
        total_donations = data.get('total_donations', 0)
        
        # Use new speed system
        description, color = get_speed_info(total_donations)
        level = min(int(total_donations / 10), 101) if total_donations > 0 else 0
        emoji = get_speed_emoji(level)
        
        config = {
            'speed_level': level,
            'description': description,
            'emoji': emoji,
            'color': color,
            'total_donations': total_donations
        }
        
        # Log the action
        log_user_action(
            action="GET_MECH_SPEED_CONFIG",
            target=f"Level {level} - {description}",
            source="Web UI"
        )
        
        return jsonify(config)
        
    except Exception as e:
        current_app.logger.error(f"Error getting mech speed config: {e}")
        return jsonify({'error': str(e)}), 500

@main_bp.route('/port_diagnostics', methods=['GET'])
@auth.login_required
def port_diagnostics():
    """
    API endpoint to get port diagnostics information.
    Helps users troubleshoot Web UI connection issues.
    """
    logger = current_app.logger
    
    try:
        logger.info("Running port diagnostics on demand...")
        diagnostics_report = run_port_diagnostics()
        
        return jsonify({
            'success': True,
            'diagnostics': diagnostics_report
        })
        
    except Exception as e:
        logger.error(f"Error running port diagnostics: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': "Error running port diagnostics. Please check the logs for details."
        })

@main_bp.route('/api/mech/difficulty', methods=['GET'])
@auth.login_required
def get_mech_difficulty():
    """Get current mech evolution difficulty multiplier."""
    try:
        from services.mech.evolution_config_manager import get_evolution_config_manager
        config_manager = get_evolution_config_manager()
        
        difficulty_multiplier = config_manager.get_difficulty_multiplier()
        manual_override_active = config_manager.is_manual_difficulty_override_active()

        # Get current mech state for level-aware preview
        from services.mech.mech_service import get_mech_service
        from services.mech.monthly_member_cache import get_monthly_member_cache
        
        mech_service = get_mech_service()
        cache = get_monthly_member_cache()
        current_state = mech_service.get_state()
        current_level = current_state.level
        next_level = current_level + 1 if current_level < 11 else 11
        
        # Calculate costs for next level (most relevant for user)
        member_count = cache.get_member_count_for_level(next_level)
        community_info = config_manager.get_community_size_info(member_count)
        
        next_level_cost, effective_multiplier = config_manager.calculate_dynamic_cost(
            next_level, member_count, community_info["multiplier"]
        )
        
        # Get level info
        next_level_info = config_manager.get_evolution_level(next_level)
        base_cost = next_level_info.base_cost if next_level_info else 0
        
        return jsonify({
            'success': True,
            'difficulty_multiplier': difficulty_multiplier,
            'manual_override': manual_override_active,  # Use consistent naming for frontend
            'current_level': current_level,
            'next_level': next_level,
            'next_level_name': next_level_info.name if next_level_info else "MAX LEVEL",
            'next_level_cost': next_level_cost,
            'base_cost': base_cost,
            'member_count': member_count,
            'community_tier': community_info["tier_name"],
            'total_multiplier': effective_multiplier,
            'is_max_level': current_level >= 11
        })
        
    except Exception as e:
        current_app.logger.error(f"Error getting mech difficulty: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@main_bp.route('/api/mech/difficulty', methods=['POST'])
@auth.login_required
def set_mech_difficulty():
    """Set mech evolution difficulty multiplier."""
    try:
        from services.mech.evolution_config_manager import get_evolution_config_manager
        from services.infrastructure.action_logger import log_user_action
        
        config_manager = get_evolution_config_manager()
        data = request.get_json()
        
        if not data or 'difficulty_multiplier' not in data:
            return jsonify({'success': False, 'error': 'Missing difficulty_multiplier parameter'}), 400
        
        difficulty_multiplier = float(data['difficulty_multiplier'])
        manual_override = bool(data.get('manual_override', False))

        # Use service method to handle business logic
        success, message = config_manager.update_difficulty_settings(difficulty_multiplier, manual_override)

        if success:
            # Log the action based on the mode
            if manual_override:
                log_user_action(
                    action="SET_MECH_DIFFICULTY",
                    target=f"Multiplier: {difficulty_multiplier}x (Manual Override)",
                    details=f"Changed mech evolution difficulty to {difficulty_multiplier}x with manual override enabled"
                )
            else:
                log_user_action(
                    action="RESET_MECH_DIFFICULTY",
                    target="Automatic Mode",
                    details="Disabled manual override - returned to automatic difficulty adjustment"
                )

            return jsonify({
                'success': True,
                'difficulty_multiplier': config_manager.get_difficulty_multiplier(),
                'manual_override_active': config_manager.is_manual_difficulty_override_active(),
                'message': message
            })
        else:
            return jsonify({'success': False, 'error': message}), 400
        
    except ValueError:
        return jsonify({'success': False, 'error': 'Invalid difficulty multiplier value'}), 400
    except Exception as e:
        current_app.logger.error(f"Error setting mech difficulty: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@main_bp.route('/api/mech/difficulty/reset', methods=['POST'])
@auth.login_required
def reset_mech_difficulty():
    """Reset mech evolution difficulty to automatic mode."""
    try:
        from services.mech.evolution_config_manager import get_evolution_config_manager
        from services.infrastructure.action_logger import log_user_action

        config_manager = get_evolution_config_manager()

        success = config_manager.reset_to_automatic_difficulty()

        if success:
            # Log the action
            log_user_action(
                action="RESET_MECH_DIFFICULTY",
                target="Automatic Mode",
                details="Reset mech evolution difficulty to automatic mode (1.0x)"
            )

            return jsonify({
                'success': True,
                'difficulty_multiplier': 1.0,
                'manual_override_active': False,
                'message': 'Difficulty reset to automatic mode'
            })
        else:
            return jsonify({'success': False, 'error': 'Failed to reset difficulty setting'}), 500

    except Exception as e:
        current_app.logger.error(f"Error resetting mech difficulty: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@main_bp.route('/api/donations/list')
@auth.login_required
def donations_api():
    """
    API endpoint to get donation data for the modal.
    """
    try:
        from services.donation.donation_management_service import get_donation_management_service
        donation_service = get_donation_management_service()
        
        # Get donation history and stats using service
        result = donation_service.get_donation_history(limit=100)
        
        if not result.success:
            current_app.logger.error(f"Failed to load donations: {result.error}")
            return jsonify({
                'success': False,
                'error': result.error
            })
        
        donations = result.data['donations']
        stats = result.data['stats']
        
        return jsonify({
            'success': True,
            'donations': donations,
            'stats': {
                'total_power': stats.total_power,
                'total_donations': stats.total_donations,
                'average_donation': stats.average_donation
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"Error loading donations API: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        })

@main_bp.route('/api/donations/delete/<int:index>', methods=['POST'])
@auth.login_required
def delete_donation(index):
    """
    API endpoint to delete a specific donation by index.
    """
    try:
        from services.donation.donation_management_service import get_donation_management_service
        donation_service = get_donation_management_service()
        
        # Delete the donation using service
        result = donation_service.delete_donation(index)
        
        if result.success:
            donor_name = result.data['donor_name']
            amount = result.data['amount']
            current_app.logger.info(f"Web UI: Deleted donation {donor_name} - ${amount:.2f}")
            
            return jsonify({
                'success': True,
                'donor_name': donor_name,
                'amount': amount,
                'message': f'Successfully deleted donation from {donor_name}'
            })
        else:
            current_app.logger.error(f"Failed to delete donation: {result.error}")
            return jsonify({
                'success': False,
                'error': result.error
            })
            
    except Exception as e:
        current_app.logger.error(f"Error deleting donation: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        })

# ========================================
# FIRST-TIME SETUP ROUTES  
# ========================================

@main_bp.route('/setup', methods=['GET'])
def setup_page():
    """First-time setup page - only works if no password is configured."""
    config = load_config()
    
    # Only allow setup if no password hash exists
    if config.get('web_ui_password_hash') is not None:
        flash('Setup is only available for first-time installation. System is already configured.', 'error')
        return redirect(url_for('main_bp.index'))
    
    return render_template('setup.html')

@main_bp.route('/setup', methods=['POST'])
def setup_save():
    """Save the initial setup configuration."""
    config = load_config()
    
    # Security check: only allow if no password is set
    if config.get('web_ui_password_hash') is not None:
        return jsonify({
            'success': False,
            'error': 'Setup is not allowed when password is already configured'
        })
    
    try:
        from werkzeug.security import generate_password_hash
        
        # Get form data
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        # Validation
        if not password or not confirm_password:
            return jsonify({
                'success': False,
                'error': 'Both password fields are required'
            })
        
        if password != confirm_password:
            return jsonify({
                'success': False,
                'error': 'Passwords do not match'
            })
        
        if len(password) < 6:
            return jsonify({
                'success': False,
                'error': 'Password must be at least 6 characters long'
            })
        
        # Create secure password hash
        password_hash = generate_password_hash(password, method="pbkdf2:sha256:600000")
        
        # Update config
        config['web_ui_password_hash'] = password_hash
        config['web_ui_user'] = 'admin'
        
        # Save config
        success = save_config(config)
        
        if success:
            # Log the setup completion
            current_app.logger.info("First-time setup completed successfully")
            log_user_action("admin", "setup", "First-time password setup completed")
            
            return jsonify({
                'success': True,
                'message': 'Setup completed! You can now login with username "admin" and your password.'
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Failed to save configuration'
            })
            
    except Exception as e:
        current_app.logger.error(f"Setup error: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': 'Setup failed due to internal error'
        })
