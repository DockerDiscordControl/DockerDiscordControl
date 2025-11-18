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
import os
import io
import time
import json

# Import auth from app.auth
from app.auth import auth 
from services.config.config_service import load_config, save_config
from app.utils.container_info_web_handler import save_container_info_from_web, load_container_info_for_web
from app.utils.web_helpers import (
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

main_bp = Blueprint('main_bp', __name__)


def _get_cached_mech_state(include_decimals=False):
    """Helper function to get mech state from cache with fallback to direct service."""
    try:
        # PERFORMANCE OPTIMIZATION: Try cache first
        from services.mech.mech_status_cache_service import get_mech_status_cache_service, MechStatusCacheRequest

        cache_service = get_mech_status_cache_service()
        cache_request = MechStatusCacheRequest(include_decimals=include_decimals)
        cache_result = cache_service.get_cached_status(cache_request)

        if cache_result.success:
            current_app.logger.info(f"WEB UI: Using cached mech status (age: {cache_result.cache_age_seconds:.1f}s)")
            # Create compatibility object from cache
            class CachedStateCompat:
                def __init__(self, cache_result):
                    self.level = cache_result.level
                    self.Power = cache_result.power
                    self.power = cache_result.power
                    self.total_donated = cache_result.total_donated
                    self.level_name = cache_result.name
                    self.name = cache_result.name
                    self.threshold = cache_result.threshold
                    self.speed = cache_result.speed
                    self.success = True
            return CachedStateCompat(cache_result)
        else:
            current_app.logger.info("WEB UI: Cache miss - falling back to direct service call")
            # Fallback to direct service call
            from services.mech.mech_service import get_mech_service, GetMechStateRequest
            mech_service = get_mech_service()
            state_request = GetMechStateRequest(include_decimals=include_decimals)
            state_result = mech_service.get_mech_state_service(state_request)

            if state_result.success:
                # Create compatibility object from service result
                class ServiceStateCompat:
                    def __init__(self, service_result):
                        self.level = service_result.level
                        self.Power = service_result.power
                        self.power = service_result.power
                        self.total_donated = service_result.total_donated
                        self.level_name = service_result.name
                        self.name = service_result.name
                        self.threshold = service_result.threshold
                        self.speed = service_result.speed
                        self.success = True
                return ServiceStateCompat(state_result)
            else:
                current_app.logger.error("Failed to get mech state from service")
                return None

    except (ImportError, AttributeError, RuntimeError) as e:
        # Service dependency errors (cache service, mech service unavailable)
        current_app.logger.error(f"Service dependency error getting cached mech state: {e}", exc_info=True)
        return None
    except (ValueError, TypeError, KeyError) as e:
        # Data processing errors (state conversion, attribute access)
        current_app.logger.error(f"Data error getting cached mech state: {e}", exc_info=True)
        return None


@main_bp.route('/', methods=['GET'])
# Use direct auth decorator
@auth.login_required
def config_page():
    logger = current_app.logger

    try:
        # Use ConfigurationPageService to handle business logic
        from services.web.configuration_page_service import get_configuration_page_service, ConfigurationPageRequest

        # Check for force refresh parameter
        force_refresh = request.args.get('force_refresh', 'false').lower() == 'true'

        # Create service request
        page_request = ConfigurationPageRequest(force_refresh=force_refresh)

        # Process page data through service
        page_service = get_configuration_page_service()
        result = page_service.prepare_page_data(page_request)

        if result.success:
            # Render template with service-prepared data
            return render_template('config.html', **result.template_data)
        else:
            logger.error(f"Failed to prepare configuration page data: {result.error}")
            # Fallback: render with minimal data
            return render_template('config.html',
                                 config={},
                                 error_message="Failed to load configuration data. Please check the logs.")

    except (ImportError, AttributeError, RuntimeError) as e:
        # Service dependency errors (configuration page service unavailable)
        logger.error(f"Service dependency error in config_page route: {e}", exc_info=True)
        return render_template('config.html',
                             config={},
                             error_message="Service error: Unable to load configuration services.")
    except (ValueError, TypeError, KeyError) as e:
        # Data processing errors (request parsing, template data)
        logger.error(f"Data error in config_page route: {e}", exc_info=True)
        return render_template('config.html',
                             config={},
                             error_message="Data error: Failed to process configuration data.")

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

        # Debug display_name values
        logger.info("[DISPLAY_NAME_SAVE_DEBUG] Checking display_name values in form:")
        for key in form_data.keys():
            if 'display_name_' in key:
                logger.info(f"[DISPLAY_NAME_SAVE_DEBUG] {key} = {repr(form_data[key])}")
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

    except (ImportError, AttributeError, RuntimeError) as e:
        # Service dependency errors (configuration save service unavailable)
        logger.error(f"Service dependency error in save_config_api: {str(e)}", exc_info=True)
        result = {
            'success': False,
            'message': "Service error: Unable to access configuration services."
        }
        flash("Service error: Unable to save configuration.", 'danger')
    except (ValueError, TypeError, KeyError) as e:
        # Data processing errors (request data parsing, validation)
        logger.error(f"Data error in save_config_api: {str(e)}", exc_info=True)
        result = {
            'success': False,
            'message': "Data error: Invalid configuration data provided."
        }
        flash("Data error: Invalid configuration data.", 'danger')

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

    except (ImportError, AttributeError, RuntimeError) as e:
        # Service dependency errors (monitor script service unavailable)
        logger.error(f"Service dependency error generating monitor script: {e}", exc_info=True)
        flash("Service error: Unable to generate monitor script.", "danger")
        return redirect(url_for('.config_page'))
    except (ValueError, TypeError, KeyError) as e:
        # Data processing errors (script type validation, template rendering)
        logger.error(f"Data error generating monitor script: {e}", exc_info=True)
        flash("Data error: Invalid script configuration.", "danger")
        return redirect(url_for('.config_page'))

@main_bp.route('/refresh_containers', methods=['POST'])
@auth.login_required
def refresh_containers():
    """Endpoint to force refresh of Docker container list - USING CONTAINER REFRESH SERVICE."""
    try:
        # Use new ContainerRefreshService for all business logic
        from services.web.container_refresh_service import get_container_refresh_service, ContainerRefreshRequest

        service = get_container_refresh_service()
        request_obj = ContainerRefreshRequest()

        # Perform refresh through service
        result = service.refresh_containers(request_obj)

        if result.success:
            return jsonify({
                'success': True,
                'container_count': result.container_count,
                'timestamp': result.timestamp,
                'formatted_time': result.formatted_time
            })
        else:
            # Log detailed error server-side, return generic message to user
            current_app.logger.error(f"Container refresh failed: {result.error}", exc_info=True)
            return jsonify({
                'success': False,
                'message': "Container refresh failed"
            })

    except (ImportError, AttributeError, RuntimeError) as e:
        # Service dependency errors (container refresh service unavailable)
        current_app.logger.error(f"Service dependency error in refresh_containers route: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': "Service error: Unable to access container refresh service."
        })
    except (ValueError, TypeError, KeyError) as e:
        # Data processing errors (result processing, timestamp formatting)
        current_app.logger.error(f"Data error in refresh_containers route: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': "Data error: Failed to process container data."
        })

@main_bp.route('/enable_temp_debug', methods=['POST'])
@auth.login_required
def enable_temp_debug():
    """Enable temporary debug mode using DiagnosticsService."""
    try:
        # Get duration from request
        duration_minutes = request.form.get('duration', 10)

        # Use DiagnosticsService for business logic
        from services.web.diagnostics_service import get_diagnostics_service, DebugModeRequest

        service = get_diagnostics_service()
        request_obj = DebugModeRequest(duration_minutes=duration_minutes)

        # Enable debug mode through service
        result = service.enable_temp_debug(request_obj)

        if result.success:
            return jsonify({
                'success': True,
                **result.data
            })
        else:
            # Log detailed error server-side, return generic message to user
            current_app.logger.error(f"Failed to enable temp debug: {result.error}", exc_info=True)
            return jsonify({
                'success': False,
                'message': "Failed to enable debug mode"
            }), 500

    except (ImportError, AttributeError, RuntimeError) as e:
        # Service dependency errors (diagnostics service unavailable)
        current_app.logger.error(f"Service dependency error in enable_temp_debug route: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': "Service error: Unable to access diagnostics service."
        }), 500
    except (ValueError, TypeError, KeyError) as e:
        # Data processing errors (duration parsing, request validation)
        current_app.logger.error(f"Data error in enable_temp_debug route: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': "Data error: Invalid debug mode configuration."
        }), 400

@main_bp.route('/disable_temp_debug', methods=['POST'])
@auth.login_required
def disable_temp_debug():
    """Disable temporary debug mode using DiagnosticsService."""
    try:
        # Use DiagnosticsService for business logic
        from services.web.diagnostics_service import get_diagnostics_service, DebugModeRequest

        service = get_diagnostics_service()
        request_obj = DebugModeRequest()

        # Disable debug mode through service
        result = service.disable_temp_debug(request_obj)

        if result.success:
            return jsonify({
                'success': True,
                **result.data
            })
        else:
            # Log detailed error server-side, return generic message to user
            current_app.logger.error(f"Failed to disable temp debug: {result.error}", exc_info=True)
            return jsonify({
                'success': False,
                'message': "Failed to disable debug mode"
            }), 500

    except (ImportError, AttributeError, RuntimeError) as e:
        # Service dependency errors (diagnostics service unavailable)
        current_app.logger.error(f"Service dependency error in disable_temp_debug route: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': "Service error: Unable to access diagnostics service."
        }), 500

@main_bp.route('/temp_debug_status', methods=['GET'])
@auth.login_required
def temp_debug_status():
    """Get temporary debug status using DiagnosticsService."""
    try:
        # Use DiagnosticsService for business logic
        from services.web.diagnostics_service import get_diagnostics_service, DebugStatusRequest

        service = get_diagnostics_service()
        request_obj = DebugStatusRequest()

        # Get debug status through service
        result = service.get_debug_status(request_obj)

        if result.success:
            return jsonify({
                'success': True,
                **result.data
            })
        else:
            # Log detailed error server-side, return generic message to user
            current_app.logger.error(f"Cache diagnostics failed: {result.error}", exc_info=True)
            return jsonify({
                'success': False,
                'message': "Failed to retrieve cache diagnostics"
            }), 500

    except (ImportError, AttributeError, RuntimeError) as e:
        # Service dependency errors (diagnostics service unavailable)
        current_app.logger.error(f"Service dependency error in temp_debug_status route: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': "Service error: Unable to access diagnostics service.",
            'is_enabled': False
        }), 500

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
            # Log detailed error server-side, return generic message to user
            current_app.logger.error(f"Performance statistics failed: {result.error}", exc_info=True)
            return jsonify({
                'success': False,
                'message': "Error getting performance statistics. Please check the logs for details."
            })

    except (ImportError, AttributeError, RuntimeError) as e:
        # Service dependency errors (performance stats service unavailable)
        current_app.logger.error(f"Service dependency error in performance_stats endpoint: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': "Service error: Unable to access performance statistics service."
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
    except (ImportError, AttributeError, RuntimeError) as e:
        # Service dependency errors (spam protection service unavailable)
        current_app.logger.error(f"Service dependency error getting spam protection settings: {e}", exc_info=True)
        return jsonify({'error': 'Service error: Unable to access spam protection service'}), 500

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
            
    except (ImportError, AttributeError, RuntimeError) as e:
        # Service dependency errors (spam protection service unavailable)
        current_app.logger.error(f"Service dependency error saving spam protection settings: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Service error: Unable to save spam protection settings'}), 500
    except (ValueError, TypeError, KeyError) as e:
        # Data processing errors (config validation, dict conversion)
        current_app.logger.error(f"Data error saving spam protection settings: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Data error: Invalid spam protection configuration'}), 400

@main_bp.route('/api/donation/status', methods=['GET'])
def get_donation_status():
    """Get current donation status with speed information - USING DONATION STATUS SERVICE."""
    try:
        # Use new DonationStatusService for all business logic
        from services.web.donation_status_service import get_donation_status_service, DonationStatusRequest

        service = get_donation_status_service()
        request_obj = DonationStatusRequest()

        # Get status through service
        result = service.get_donation_status(request_obj)

        if result.success:
            return jsonify(result.status_data)
        else:
            # Log detailed error but return generic message to user
            current_app.logger.error(f"Failed to get donation status: {result.error}")
            return jsonify({'error': 'Failed to get donation status'}), 500

    except (ImportError, AttributeError, RuntimeError) as e:
        # Service dependency errors (donation status service unavailable)
        current_app.logger.error(f"Service dependency error in get_donation_status route: {e}", exc_info=True)
        return jsonify({'error': 'Service error: Unable to access donation status service'}), 500
    except (ValueError, TypeError, KeyError) as e:
        # Data processing errors (status data formatting)
        current_app.logger.error(f"Data error in get_donation_status route: {e}", exc_info=True)
        return jsonify({'error': 'Data error: Failed to process donation status'}), 500

@main_bp.route('/api/donation/click', methods=['POST'])
def record_donation_click():
    """Record a donation button click - USING DONATION TRACKING SERVICE."""
    try:
        data = request.get_json()
        if not data or 'type' not in data:
            return jsonify({'success': False, 'error': 'Missing donation type'}), 400

        # Use new DonationTrackingService for all business logic
        from services.web.donation_tracking_service import get_donation_tracking_service, DonationClickRequest

        service = get_donation_tracking_service()
        request_obj = DonationClickRequest(
            donation_type=data.get('type'),
            request_object=request
        )

        # Track donation click through service
        result = service.record_donation_click(request_obj)

        if result.success:
            return jsonify({
                'success': True,
                'timestamp': result.timestamp,
                'message': result.message
            })
        else:
            # Log detailed error but return generic message to user
            current_app.logger.error(f"Failed to record donation click: {result.error}")
            return jsonify({
                'success': False,
                'error': 'Failed to record donation click'
            }), 400

    except (ImportError, AttributeError, RuntimeError) as e:
        # Service dependency errors (donation tracking service unavailable)
        current_app.logger.error(f"Service dependency error in record_donation_click route: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Service error: Unable to record donation click'}), 500
    except (ValueError, TypeError, KeyError) as e:
        # Data processing errors (request parsing, validation)
        current_app.logger.error(f"Data error in record_donation_click route: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Data error: Invalid click data'}), 400


@main_bp.route('/api/donation/add-power', methods=['POST'])
@auth.login_required
def add_test_power():
    """Add or remove Power for testing (requires auth) - USING NEW MECH SERVICE."""
    try:
        data = request.get_json()
        amount = data.get('amount', 0)
        donation_type = data.get('type', 'test')
        user = data.get('user', 'Test')

        # Validate amount is numeric
        try:
            amount = int(amount) if not isinstance(amount, int) else amount
        except (ValueError, TypeError):
            return jsonify({'error': f'Invalid amount: {amount} - must be numeric'}), 400

        # UNIFIED DONATION SERVICE: Centralized processing with guaranteed events
        from services.donation.unified_donation_service import process_test_donation

        if amount != 0:
            # Add donation (positive only - negative testing requires special handling)
            if amount > 0:
                # Use unified service for positive donations with automatic events
                donation_result = process_test_donation(user, amount)

                if not donation_result.success:
                    raise Exception(f"Test donation failed: {donation_result.error_message}")

                result_state = donation_result.new_state
                current_app.logger.info(f"UNIFIED SERVICE: Added ${amount} Power, new total: ${result_state.Power}")
            else:
                # For negative amounts, we need to work around the limitation
                # MechService only accepts positive integers, so we add a negative donation
                # by manipulating the state directly (testing only!)
                # PERFORMANCE OPTIMIZATION: Use cached mech state
                current_state = _get_cached_mech_state(include_decimals=False)
                if not current_state:
                    current_app.logger.error("Failed to get mech state for negative donation")
                    return jsonify({'error': 'Failed to get mech state'}), 500

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
            
    except (ImportError, AttributeError, RuntimeError) as e:
        # Service dependency errors (unified donation service unavailable)
        current_app.logger.error(f"Service dependency error adding test Power: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Service error: Unable to process test donation'}), 500
    except (ValueError, TypeError) as e:
        # Data processing errors (amount validation, state calculations)
        current_app.logger.error(f"Data error adding test Power: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Data error: Invalid donation amount'}), 400

@main_bp.route('/api/donation/reset-power', methods=['POST'])
@auth.login_required  
def reset_power():
    """Reset Power to 0 for testing (requires auth) - USING NEW MECH SERVICE."""
    try:
        # UNIFIED DONATION SERVICE: Reset with automatic event emission
        from services.donation.unified_donation_service import reset_all_donations

        reset_result = reset_all_donations(source='admin_reset')

        if not reset_result.success:
            # Log detailed error but return generic message to user
            current_app.logger.error(f"Failed to reset donations: {reset_result.error_message}")
            return jsonify({'success': False, 'error': 'Failed to reset donations'})
        
        # Get new state (should be Level 1, 0 Power) using CACHE FOR PERFORMANCE
        # PERFORMANCE OPTIMIZATION: Use cached mech state (will be fresh since we just reset)
        reset_state = _get_cached_mech_state(include_decimals=False)
        if not reset_state:
            current_app.logger.error("Failed to get reset state")
            return jsonify({'success': False, 'error': 'Failed to get reset state'})
        
        current_app.logger.info(f"NEW SERVICE: Power reset - Level {reset_state.level}, Power ${reset_state.Power}")
        
        return jsonify({
            'success': True, 
            'message': 'Power reset to 0 using new MechService',
            'level': reset_state.level,
            'level_name': reset_state.level_name,
            'Power': reset_state.Power,
            'total_donated': reset_state.total_donated
        })
    except (ImportError, AttributeError, RuntimeError) as e:
        # Service dependency errors (unified donation service unavailable)
        current_app.logger.error(f"Service dependency error resetting Power: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Service error: Unable to reset donations'}), 500

@main_bp.route('/api/donation/consume-power', methods=['POST'])
@auth.login_required
def consume_Power():
    """Get current Power state - USES CACHE FOR PERFORMANCE."""
    try:
        # PERFORMANCE OPTIMIZATION: Use cached mech state
        current_state = _get_cached_mech_state(include_decimals=False)
        if not current_state:
            return jsonify({'success': False, 'error': 'Failed to get current state'})
        
        # Removed frequent Power consumption log to reduce noise in DEBUG mode
        # current_app.logger.debug(f"NEW SERVICE: Power consumption check - current Power: ${current_state.Power}")
        
        return jsonify({
            'success': True, 
            'new_Power': max(0, current_state.Power),
            'level': current_state.level,
            'level_name': current_state.level_name,
            'message': 'Power decay calculated automatically by new service'
        })
        
    except (RuntimeError, AttributeError) as e:
        # Service/cache errors (mech state retrieval failures)
        current_app.logger.error(f"Service error consuming Power: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Service error: Unable to get Power state'}), 500


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
            # Log detailed error server-side, return generic message to user
            current_app.logger.error(f"Donation processing failed: {result.error}", exc_info=True)
            return jsonify({'success': False, 'error': 'Failed to process donation'}), 500

    except (ImportError, AttributeError, RuntimeError) as e:
        # Service dependency errors (donation service unavailable)
        current_app.logger.error(f"Service dependency error processing manual donation: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Service error: Unable to process donation'}), 500
    except (ValueError, TypeError, KeyError) as e:
        # Data processing errors (amount validation, request parsing)
        current_app.logger.error(f"Data error processing manual donation: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Data error: Invalid donation data'}), 400

@main_bp.route('/mech_animation')
def mech_animation():
    """Live mech animation endpoint using MechWebService."""
    try:
        # Use MechWebService for business logic
        from services.web.mech_web_service import get_mech_web_service, MechAnimationRequest

        service = get_mech_web_service()
        request_obj = MechAnimationRequest()

        # Get animation through service
        result = service.get_live_animation(request_obj)

        if result.success and result.animation_bytes:
            return Response(
                result.animation_bytes,
                mimetype=result.content_type,
                headers=result.cache_headers or {}
            )
        else:
            # Return error response based on result
            return Response(
                result.animation_bytes or b'Animation generation failed',
                mimetype=result.content_type,
                status=result.status_code
            )

    except (ImportError, AttributeError, RuntimeError) as e:
        # Service dependency errors (mech web service unavailable)
        current_app.logger.error(f"Service dependency error in mech_animation route: {e}", exc_info=True)
        return jsonify({'error': 'Service error: Unable to generate animation'}), 500
    except (ValueError, TypeError) as e:
        # Data processing errors (animation generation, response formatting)
        current_app.logger.error(f"Data error in mech_animation route: {e}", exc_info=True)
        return jsonify({'error': 'Data error: Animation generation failed'}), 500

@main_bp.route('/api/test-mech-animation', methods=['POST'])
@auth.login_required
def test_mech_animation():
    """Test endpoint for generating mech animations using MechWebService."""
    try:
        data = request.get_json()
        donor_name = data.get('donor_name', 'Test User')
        amount = data.get('amount', '10$')
        total_donations = data.get('total_donations', 0)

        current_app.logger.info(f"Generating test mech animation for {donor_name}, donations: {total_donations}")

        # Use MechWebService for business logic
        from services.web.mech_web_service import get_mech_web_service, MechTestAnimationRequest

        service = get_mech_web_service()
        request_obj = MechTestAnimationRequest(
            donor_name=donor_name,
            amount=amount,
            total_donations=total_donations
        )

        # Get test animation through service
        result = service.get_test_animation(request_obj)

        if result.success and result.animation_bytes:
            return Response(
                result.animation_bytes,
                mimetype=result.content_type,
                headers={'Cache-Control': 'max-age=60'}
            )
        else:
            # Return error response based on result
            return Response(
                result.animation_bytes or b'Error: Service not available',
                mimetype=result.content_type,
                status=result.status_code
            )

    except (ImportError, AttributeError, RuntimeError) as e:
        # Service dependency errors (mech web service unavailable)
        current_app.logger.error(f"Service dependency error in test_mech_animation route: {e}", exc_info=True)
        return jsonify({'error': 'Service error: Unable to generate test animation'}), 500
    except (ValueError, TypeError, KeyError) as e:
        # Data processing errors (request parsing, animation generation)
        current_app.logger.error(f"Data error in test_mech_animation route: {e}", exc_info=True)
        return jsonify({'error': 'Data error: Invalid test animation parameters'}), 400

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
    except RuntimeError as e:
        # Runtime errors (simulation failures)
        current_app.logger.error(f"Runtime error simulating donation broadcast: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Runtime error in simulation'}), 500

@main_bp.route('/api/mech-speed-config', methods=['POST'])
@auth.login_required
def get_mech_speed_config():
    """Get speed configuration using MechWebService."""
    try:
        data = request.get_json()
        total_donations = data.get('total_donations', 0)

        # Use MechWebService for business logic
        from services.web.mech_web_service import get_mech_web_service, MechSpeedConfigRequest

        service = get_mech_web_service()
        request_obj = MechSpeedConfigRequest(total_donations=total_donations)

        # Get speed config through service
        result = service.get_speed_config(request_obj)

        if result.success:
            return jsonify(result.data)
        else:
            # Log detailed error server-side, return generic message to user
            current_app.logger.error(f"Speed config request failed: {result.error}", exc_info=True)
            return jsonify({'error': 'Failed to get speed configuration'}), 500

    except (ImportError, AttributeError, RuntimeError) as e:
        # Service dependency errors (mech web service unavailable)
        current_app.logger.error(f"Service dependency error in get_mech_speed_config route: {e}", exc_info=True)
        return jsonify({'error': 'Service error: Unable to get speed config'}), 500
    except (ValueError, TypeError, KeyError) as e:
        # Data processing errors (donation amount parsing, config formatting)
        current_app.logger.error(f"Data error in get_mech_speed_config route: {e}", exc_info=True)
        return jsonify({'error': 'Data error: Invalid speed configuration'}), 400

@main_bp.route('/port_diagnostics', methods=['GET'])
@auth.login_required
def port_diagnostics():
    """Get port diagnostics using DiagnosticsService."""
    try:
        # Use DiagnosticsService for business logic
        from services.web.diagnostics_service import get_diagnostics_service, PortDiagnosticsRequest

        service = get_diagnostics_service()
        request_obj = PortDiagnosticsRequest()

        # Run diagnostics through service
        result = service.run_port_diagnostics(request_obj)

        if result.success:
            return jsonify({
                'success': True,
                **result.data
            })
        else:
            return jsonify({
                'success': False,
                'message': result.error
            }), result.status_code

    except (ImportError, AttributeError, RuntimeError) as e:
        # Service dependency errors (diagnostics service unavailable)
        current_app.logger.error(f"Service dependency error in port_diagnostics route: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': "Service error: Unable to run port diagnostics."
        }), 500

@main_bp.route('/api/mech/difficulty', methods=['GET'])
@auth.login_required
def get_mech_difficulty():
    """Get current mech evolution difficulty multiplier using MechWebService."""
    try:
        # Use MechWebService for business logic
        from services.web.mech_web_service import get_mech_web_service, MechDifficultyRequest

        service = get_mech_web_service()
        request_obj = MechDifficultyRequest(operation='get')

        # Get difficulty through service
        result = service.manage_difficulty(request_obj)

        if result.success:
            return jsonify(result.data)
        else:
            # Log detailed error server-side, return generic message to user
            current_app.logger.error(f"Difficulty get request failed: {result.error}", exc_info=True)
            return jsonify({'success': False, 'error': 'Failed to get difficulty settings'}), 500

    except (ImportError, AttributeError, RuntimeError) as e:
        # Service dependency errors (mech web service unavailable)
        current_app.logger.error(f"Service dependency error in get_mech_difficulty route: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Service error: Unable to get difficulty'}), 500

@main_bp.route('/api/mech/difficulty', methods=['POST'])
@auth.login_required
def set_mech_difficulty():
    """Set mech evolution difficulty multiplier using MechWebService."""
    try:
        data = request.get_json()

        if not data or 'difficulty_multiplier' not in data:
            return jsonify({'success': False, 'error': 'Missing difficulty_multiplier parameter'}), 400

        difficulty_multiplier = float(data['difficulty_multiplier'])
        manual_override = data.get('manual_override', False)

        # Use MechWebService for business logic
        from services.web.mech_web_service import get_mech_web_service, MechDifficultyRequest

        service = get_mech_web_service()

        if manual_override:
            # Manual override = static mode with custom difficulty
            request_obj = MechDifficultyRequest(
                operation='set',
                multiplier=difficulty_multiplier
            )
        else:
            # No manual override = reset to dynamic mode
            request_obj = MechDifficultyRequest(operation='reset')

        # Set difficulty through service
        result = service.manage_difficulty(request_obj)

        if result.success:
            return jsonify(result.data)
        else:
            # Log detailed error server-side, return generic message to user
            current_app.logger.error(f"Difficulty set request failed: {result.error}", exc_info=True)
            return jsonify({'success': False, 'error': 'Failed to set difficulty'}), 500

    except ValueError:
        return jsonify({'success': False, 'error': 'Invalid difficulty multiplier value'}), 400
    except (ImportError, AttributeError, RuntimeError) as e:
        # Service dependency errors (mech web service unavailable)
        current_app.logger.error(f"Service dependency error in set_mech_difficulty route: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Service error: Unable to set difficulty'}), 500

@main_bp.route('/api/mech/difficulty/reset', methods=['POST'])
@auth.login_required
def reset_mech_difficulty():
    """Reset mech evolution difficulty to automatic mode using MechWebService."""
    try:
        # Use MechWebService for business logic
        from services.web.mech_web_service import get_mech_web_service, MechDifficultyRequest

        service = get_mech_web_service()
        request_obj = MechDifficultyRequest(operation='reset')

        # Reset difficulty through service
        result = service.manage_difficulty(request_obj)

        if result.success:
            return jsonify(result.data)
        else:
            # Log detailed error server-side, return generic message to user
            current_app.logger.error(f"Difficulty reset request failed: {result.error}", exc_info=True)
            return jsonify({'success': False, 'error': 'Failed to reset difficulty'}), 500

    except (ImportError, AttributeError, RuntimeError) as e:
        # Service dependency errors (mech web service unavailable)
        current_app.logger.error(f"Service dependency error in reset_mech_difficulty route: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Service error: Unable to reset difficulty'}), 500

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
            # Log detailed error server-side, return generic message to user
            current_app.logger.error(f"Failed to load donations: {result.error}", exc_info=True)
            return jsonify({
                'success': False,
                'error': 'Failed to load donations'
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
        
    except (ImportError, AttributeError, RuntimeError) as e:
        # Service dependency errors (donation management service unavailable)
        current_app.logger.error(f"Service dependency error loading donations API: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': 'Service error: Unable to load donations'
        })
    except (ValueError, TypeError, KeyError) as e:
        # Data processing errors (stats formatting, data access)
        current_app.logger.error(f"Data error loading donations API: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': 'Data error: Failed to process donation data'
        })

@main_bp.route('/api/donations/delete/<int:index>', methods=['POST'])
@auth.login_required
def delete_donation(index):
    """
    Delete a donation OR restore a deleted donation using Event Sourcing compensation events.

    This is EVENT SOURCING COMPLIANT:
    - For DonationAdded: Adds a DonationDeleted event (marks donation as deleted)
    - For DonationDeleted: Adds another DonationDeleted event (restores original donation!)
    - Rebuilds the snapshot from scratch, applying all active events
    - All level-ups and costs are recalculated correctly
    - Member counts are frozen at the correct historical moments
    """
    try:
        from services.donation.donation_management_service import get_donation_management_service

        service = get_donation_management_service()
        result = service.delete_donation(index)

        if result.success:
            action = result.data.get('action', 'Deleted')
            event_type = result.data.get('type', 'Unknown')
            seq = result.data.get('deleted_seq', 'Unknown')

            current_app.logger.info(f"{action} event at index {index} (seq {seq}, type {event_type})")

            message = f"Event {action.lower()} successfully (seq #{seq})"
            return jsonify({
                'success': True,
                'message': message
            })
        else:
            # Log detailed error server-side, return generic message to user
            current_app.logger.error(f"Failed to delete/restore event: {result.error}", exc_info=True)
            return jsonify({
                'success': False,
                'error': 'Failed to delete/restore event'
            }), 400

    except (ImportError, AttributeError, RuntimeError) as e:
        # Service dependency errors (donation management service unavailable)
        current_app.logger.error(f"Service dependency error in delete/restore donation route: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': "Service error: Unable to process donation deletion/restoration"
        }), 500
    except (ValueError, TypeError, KeyError) as e:
        # Data processing errors (index validation, result parsing)
        current_app.logger.error(f"Data error in delete/restore donation route: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': "Data error: Invalid deletion request"
        }), 400

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
        return redirect(url_for('main_bp.config_page'))
    
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
            
    except (ImportError, AttributeError) as e:
        # Dependency errors (werkzeug unavailable)
        current_app.logger.error(f"Dependency error in setup: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': 'Setup failed: Missing required dependencies'
        })
    except (ValueError, TypeError) as e:
        # Data processing errors (password validation, hash generation)
        current_app.logger.error(f"Data error in setup: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': 'Setup failed: Invalid configuration data'
        })
    except (IOError, OSError) as e:
        # File I/O errors (config save failure)
        current_app.logger.error(f"File I/O error in setup: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': 'Setup failed: Unable to save configuration'
        })

# ========================================
# MECH MUSIC API ROUTES (for Discord integration)
# ========================================

@main_bp.route('/api/mech/music/<int:level>')
def get_mech_music_url(level):
    """Get YouTube URL for mech music at a specific level using MechMusicService."""
    try:
        # Use MechMusicService for business logic
        from services.web.mech_music_service import get_mech_music_service, MechMusicRequest

        service = get_mech_music_service()
        request_obj = MechMusicRequest(level=level)

        # Get YouTube music URL through service
        result = service.get_mech_music_url(request_obj)

        if result.success:
            current_app.logger.info(f"Providing YouTube URL for mech music level {level}: {result.title}")
            return jsonify({
                'success': True,
                'level': level,
                'title': result.title,
                'url': result.url,
                'platform': 'YouTube',
                'monetized': True  # Support creator revenue! 💰
            })
        else:
            current_app.logger.warning(f"YouTube URL not found for mech level {level}: {result.error}")
            return jsonify({
                'success': False,
                'error': result.error or f'YouTube URL not found for Mech Level {level}'
            }), result.status_code

    except (ImportError, AttributeError, RuntimeError) as e:
        # Service dependency errors (mech music service unavailable)
        current_app.logger.error(f"Service dependency error in get_mech_music_url route: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': 'Service error: Unable to get YouTube music URL'
        }), 500
    except (ValueError, TypeError) as e:
        # Data processing errors (level validation, URL formatting)
        current_app.logger.error(f"Data error in get_mech_music_url route: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': 'Data error: Invalid music level'
        }), 400

@main_bp.route('/api/mech/music/info')
def get_mech_music_info():
    """Get information about all available mech music tracks using MechMusicService."""
    try:
        # Use MechMusicService for business logic
        from services.web.mech_music_service import get_mech_music_service, MechMusicInfoRequest

        service = get_mech_music_service()
        request_obj = MechMusicInfoRequest()

        # Get all music info through service
        result = service.get_all_music_info(request_obj)

        if result.success:
            return jsonify({
                'success': True,
                **result.data
            })
        else:
            return jsonify({
                'success': False,
                'error': result.error
            }), result.status_code

    except (ImportError, AttributeError, RuntimeError) as e:
        # Service dependency errors (mech music service unavailable)
        current_app.logger.error(f"Service dependency error in get_mech_music_info route: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': 'Service error: Unable to get mech music information'
        }), 500


@main_bp.route('/api/mech/display/<int:level>/<string:image_type>')
def get_mech_display_image(level: int, image_type: str):
    """
    Serve pre-rendered mech display images for instant Discord loading.

    URL: /api/mech/display/{level}/{type}
    Example: /api/mech/display/5/shadow
             /api/mech/display/8/unlocked
    """
    try:
        # Validate parameters
        if level < 1 or level > 11:
            return jsonify({'error': 'Invalid level. Must be 1-11.'}), 400

        if image_type not in ['shadow', 'unlocked']:
            return jsonify({'error': 'Invalid image type. Must be "shadow" or "unlocked".'}), 400

        # Get pre-rendered image through SERVICE FIRST
        from services.mech.mech_display_cache_service import get_mech_display_cache_service, MechDisplayImageRequest

        display_cache_service = get_mech_display_cache_service()
        image_request = MechDisplayImageRequest(
            evolution_level=level,
            image_type=image_type
        )
        image_result = display_cache_service.get_mech_display_image(image_request)

        if not image_result.success:
            current_app.logger.error(f"Failed to get mech display image: {image_result.error_message}")
            return jsonify({'error': 'Image not available'}), 404

        # Create in-memory file object for serving
        image_buffer = io.BytesIO(image_result.image_bytes)
        image_buffer.seek(0)

        # Determine content type and set caching headers
        response = Response(
            image_buffer.getvalue(),
            mimetype='image/webp',
            headers={
                'Content-Type': 'image/webp',
                'Cache-Control': 'public, max-age=86400',  # Cache for 24 hours
                'ETag': f'mech-{level}-{image_type}',
                'Content-Disposition': f'inline; filename="{image_result.filename}"'
            }
        )

        current_app.logger.info(f"Served mech display image: Level {level} {image_type} ({len(image_result.image_bytes)} bytes)")
        return response

    except (ImportError, AttributeError, RuntimeError) as e:
        # Service dependency errors (display cache service unavailable)
        current_app.logger.error(f"Service dependency error serving mech display image: {e}", exc_info=True)
        return jsonify({'error': 'Service error: Unable to serve display image'}), 500
    except (ValueError, TypeError, IOError, OSError) as e:
        # Data/file errors (validation, image access)
        current_app.logger.error(f"Data/file error serving mech display image: {e}", exc_info=True)
        return jsonify({'error': 'Error: Invalid image request or file access failed'}), 400


@main_bp.route('/api/mech/display/info')
def get_mech_display_info():
    """
    Get information about available mech display images.

    Returns: JSON with available levels and image types
    """
    try:
        from services.mech.mech_display_cache_service import get_mech_display_cache_service

        display_cache_service = get_mech_display_cache_service()

        # Check available cache files
        cache_files = list(display_cache_service.cache_dir.glob('mech_*_*.webp'))
        available_images = {}

        for cache_file in cache_files:
            # Parse filename: mech_{level}_{type}.webp
            parts = cache_file.stem.split('_')
            if len(parts) >= 3:
                try:
                    level = int(parts[1])
                    image_type = parts[2]

                    if level not in available_images:
                        available_images[level] = {}

                    file_size = cache_file.stat().st_size
                    available_images[level][image_type] = {
                        'available': True,
                        'size_bytes': file_size,
                        'url': url_for('main_bp.get_mech_display_image', level=level, image_type=image_type, _external=True)
                    }
                except ValueError:
                    continue

        return jsonify({
            'success': True,
            'available_levels': list(range(1, 12)),
            'available_types': ['shadow', 'unlocked'],
            'cached_images': available_images,
            'total_cached': len(cache_files),
            'cache_directory': str(display_cache_service.cache_dir)
        })

    except (ImportError, AttributeError, RuntimeError) as e:
        # Service dependency errors (display cache service unavailable)
        current_app.logger.error(f"Service dependency error getting mech display info: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': 'Service error: Unable to get display information'
        }), 500
    except (IOError, OSError) as e:
        # File system errors (cache directory access, file stat)
        current_app.logger.error(f"File system error getting mech display info: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': 'File system error: Unable to access cache directory'
        }), 500
    except (ValueError, TypeError) as e:
        # Data processing errors (filename parsing, stat operations)
        current_app.logger.error(f"Data error getting mech display info: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': 'Data error: Failed to process cache information'
        }), 500

@main_bp.route('/api/mech/reset', methods=['POST'])
@auth.login_required
def reset_mech_to_level_1():
    """Reset Mech system to Level 1 for testing/development."""
    try:
        from services.mech.mech_reset_service import get_mech_reset_service

        # Get reset service
        reset_service = get_mech_reset_service()

        # Get current status before reset
        current_status = reset_service.get_current_status()

        # Perform full reset
        result = reset_service.full_reset()

        # Log the action
        try:
            from services.infrastructure.action_logger import log_user_action
            log_user_action(
                action="MECH_RESET",
                target="Mech System",
                user=session.get('username', 'Unknown'),
                source="Web UI",
                details=f"Reset to Level 1 - Previous: Level {current_status.get('current_level', 'Unknown')}"
            )
        except (ImportError, AttributeError, RuntimeError) as log_error:
            # Non-critical: Action logger errors (logging service unavailable)
            current_app.logger.warning(f"Failed to log mech reset action: {log_error}")

        # Return result
        if result.success:
            # Success: Include full details
            response_data = {
                'success': True,
                'message': result.message,
                'previous_status': current_status,
                'timestamp': result.details.get('timestamp') if result.details else None
            }
            if result.details and 'operations' in result.details:
                response_data['operations'] = result.details['operations']

            current_app.logger.info(f"Mech reset to Level 1 completed by user: {session.get('username', 'Unknown')}")
            return jsonify(response_data)
        else:
            # Failure: Log detailed error server-side, return generic message to user
            current_app.logger.error(f"Mech reset failed: {result.message}", exc_info=True)
            return jsonify({
                'success': False,
                'error': 'Failed to reset mech system'
            }), 500

    except (ImportError, AttributeError, RuntimeError) as e:
        # Service dependency errors (mech reset service unavailable)
        error_msg = f"Service dependency error during mech reset: {e}"
        current_app.logger.error(error_msg, exc_info=True)
        return jsonify({
            'success': False,
            'error': 'Service error: Unable to reset mech system'
        }), 500
    except (ValueError, TypeError, KeyError) as e:
        # Data processing errors (status parsing, result formatting)
        error_msg = f"Data error during mech reset: {e}"
        current_app.logger.error(error_msg, exc_info=True)
        return jsonify({
            'success': False,
            'error': 'Data error: Failed to process reset operation'
        }), 500

@main_bp.route('/api/mech/status', methods=['GET'])
@auth.login_required
def get_mech_status():
    """Get current Mech system status."""
    try:
        from services.mech.mech_reset_service import get_mech_reset_service

        # Get reset service for status
        reset_service = get_mech_reset_service()
        status = reset_service.get_current_status()

        return jsonify({
            'success': True,
            'status': status,
            'timestamp': datetime.now().isoformat()
        })

    except (ImportError, AttributeError, RuntimeError) as e:
        # Service dependency errors (mech reset service unavailable)
        error_msg = f"Service dependency error getting mech status: {e}"
        current_app.logger.error(error_msg, exc_info=True)
        return jsonify({
            'success': False,
            'error': 'Service error: Unable to get mech status'
        }), 500
    except (ValueError, TypeError, KeyError) as e:
        # Data processing errors (status formatting, datetime operations)
        error_msg = f"Data error getting mech status: {e}"
        current_app.logger.error(error_msg, exc_info=True)
        return jsonify({
            'success': False,
            'error': 'Data error: Failed to format status'
        }), 500
