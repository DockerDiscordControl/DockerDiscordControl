# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2023-2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, 
    jsonify, session, current_app, send_file, Response, make_response
)
from datetime import datetime, timezone, timedelta # Added datetime for config_page
from functools import wraps
import os
import io
import time
import json
import traceback
import pytz

# Import auth from app.auth
from app.auth import auth 
from utils.config_loader import load_config, save_config, DEFAULT_CONFIG # Import DEFAULT_CONFIG
from app.utils.web_helpers import (
    log_user_action, 
    get_docker_containers_live,
    docker_cache
)
# NEW: Import shared_data
from app.utils.shared_data import get_active_containers, load_active_containers_from_config
from app.constants import COMMON_TIMEZONES # Import from new constants file
# Import scheduler functions for the main page
from utils.scheduler import (
    load_tasks, 
    DAYS_OF_WEEK
)
from utils.action_logger import log_user_action

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
def generate_python_monitor_script(form_data):
    """Generate a Python-based heartbeat monitor script"""
    # Extract configuration
    monitor_bot_token = form_data.get('monitor_bot_token', '')
    ddc_bot_user_id = form_data.get('ddc_bot_user_id', '')
    heartbeat_channel_id = form_data.get('heartbeat_channel_id', '')
    alert_channel_ids = form_data.get('alert_channel_ids', '')
    monitor_timeout_seconds = form_data.get('monitor_timeout_seconds', '271')  # Default: ~4.5 minutes
    
    # Format the alert channel IDs as a Python list
    formatted_alert_channels = [ch.strip() for ch in alert_channel_ids.split(',') if ch.strip()]
    alert_channels_str = ", ".join([f"'{ch}'" for ch in formatted_alert_channels])
    
    # Generate the script content
    current_time = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    script = f"""#!/usr/bin/env python3
# -*- coding: utf-8 -*-
'''
DockerDiscordControl (DDC) Heartbeat Monitor Script
===================================================

This script monitors Discord for heartbeat messages sent by the DDC bot
and sends alerts if the heartbeat is missing for too long.

Generated on: {current_time}

Setup Instructions:
1. Install requirements: pip install discord.py
2. Run this script on a separate system from your DDC bot
3. Keep this script running continuously (using systemd, screen, tmux, etc.)
'''

import asyncio
import datetime
import logging
import sys
import time
from typing import List, Optional

try:
    import discord
    from discord.ext import tasks
except ImportError:
    print("Error: This script requires discord.py. Please install it with: pip install discord.py")
    sys.exit(1)

# === Configuration ===
BOT_TOKEN = '{monitor_bot_token}'
DDC_BOT_USER_ID = {ddc_bot_user_id}
HEARTBEAT_CHANNEL_ID = {heartbeat_channel_id}
ALERT_CHANNEL_IDS = [{alert_channels_str}]
HEARTBEAT_TIMEOUT_SECONDS = {monitor_timeout_seconds}

# === Logging Setup ===
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('ddc_heartbeat_monitor.log')
    ]
)
logger = logging.getLogger('ddc_monitor')

class HeartbeatMonitor(discord.Client):
    def __init__(self, *args, **kwargs):
        intents = discord.Intents.default()
        intents.message_content = True  # Needed to read message content
        super().__init__(intents=intents, *args, **kwargs)
        
        # State tracking
        self.last_heartbeat_time = None
        self.alert_sent = False
        self.start_time = datetime.datetime.now()
        
        # Start monitoring loop
        self.heartbeat_check.start()
    
    async def on_ready(self):
        '''Called when the client is ready'''
        logger.info(f"Monitor logged in as {{self.user}} (ID: {{self.user.id}})")
        logger.info(f"Monitoring heartbeats from DDC bot ID: {{DDC_BOT_USER_ID}}")
        logger.info(f"Watching channel: {{HEARTBEAT_CHANNEL_ID}}")
        logger.info(f"Will send alerts to channel(s): {{ALERT_CHANNEL_IDS}}")
        logger.info(f"Heartbeat timeout: {{HEARTBEAT_TIMEOUT_SECONDS}} seconds")
        
        # Send startup notification
        await self._send_to_alert_channels(
            title="🔄 Heartbeat Monitoring Started",
            description=f"DDC Heartbeat monitoring is now active.\\nMonitoring DDC bot: <@{{DDC_BOT_USER_ID}}>\\nAlert timeout: {{HEARTBEAT_TIMEOUT_SECONDS}} seconds",
            color=discord.Color.blue()
        )
    
    async def on_message(self, message):
        '''Called when a message is received'''
        # Check if message is from DDC bot and in the heartbeat channel
        if (message.author.id == DDC_BOT_USER_ID and 
            message.channel.id == HEARTBEAT_CHANNEL_ID and
            "❤️" in message.content):
            
            # Update last heartbeat time
            self.last_heartbeat_time = datetime.datetime.now()
            logger.debug(f"Heartbeat detected at {{self.last_heartbeat_time.isoformat()}}")
            
            # If we previously sent an alert, send recovery notification
            if self.alert_sent:
                self.alert_sent = False
                logger.info("Heartbeat recovered after previous alert")
                await self._send_to_alert_channels(
                    title="✅ DDC Heartbeat Recovered",
                    description=f"Heartbeat from DDC bot <@{{DDC_BOT_USER_ID}}> has been restored.\\n\\nMonitoring continues.",
                    color=discord.Color.green()
                )
    
    async def _send_to_alert_channels(self, title, description, color):
        '''Send a message to all configured alert channels'''
        embed = discord.Embed(
            title=title,
            description=description,
            color=color,
            timestamp=datetime.datetime.now()
        )
        embed.set_footer(text="DDC Heartbeat Monitor | https://ddc.bot")
        
        for channel_id in ALERT_CHANNEL_IDS:
            try:
                channel = self.get_channel(int(channel_id))
                if not channel:
                    channel = await self.fetch_channel(int(channel_id))
                await channel.send(embed=embed)
                logger.info(f"Notification sent to channel {{channel_id}}")
            except Exception as e:
                logger.error(f"Error sending to channel {{channel_id}}: {{e}}")
    
    @tasks.loop(seconds=30)
    async def heartbeat_check(self):
        '''Check if heartbeat has been received within the timeout period'''
        now = datetime.datetime.now()
        
        if not self.last_heartbeat_time:
            # No heartbeat received yet since startup
            startup_seconds = (now - self.start_time).total_seconds()
            if startup_seconds > HEARTBEAT_TIMEOUT_SECONDS and not self.alert_sent:
                logger.warning(f"No initial heartbeat received {{startup_seconds:.1f}} seconds after startup")
                await self._send_alert()
        else:
            # Check time since last heartbeat
            elapsed = (now - self.last_heartbeat_time).total_seconds()
            if elapsed > HEARTBEAT_TIMEOUT_SECONDS and not self.alert_sent:
                await self._send_alert()
    
    async def _send_alert(self):
        '''Send missing heartbeat alert to all configured channels'''
        if self.alert_sent:
            return  # Don't spam alerts
        
        # Calculate elapsed time
        now = datetime.datetime.now()
        if self.last_heartbeat_time:
            elapsed_seconds = (now - self.last_heartbeat_time).total_seconds()
            last_heartbeat_time_str = self.last_heartbeat_time.isoformat()
        else:
            elapsed_seconds = (now - self.start_time).total_seconds()
            last_heartbeat_time_str = "Never"
        
        logger.warning(f"Heartbeat missing for {{elapsed_seconds:.1f}} seconds, sending alert")
        
        await self._send_to_alert_channels(
            title="⚠️ DDC Heartbeat Missing",
            description=(f"❌ No heartbeat detected from DDC bot <@{{DDC_BOT_USER_ID}}> "
                        f"for {{elapsed_seconds:.1f}} seconds.\\n\\n"
                        f"Last heartbeat: {{last_heartbeat_time_str}}\\n\\n"
                        f"**Possible causes:**\\n"
                        f"• DDC container is down\\n"
                        f"• Discord bot has lost connection\\n"
                        f"• Discord API issues\\n"
                        f"• Missing permissions in heartbeat channel"),
            color=discord.Color.red()
        )
        
        self.alert_sent = True
    
    @heartbeat_check.before_loop
    async def before_heartbeat_check(self):
        '''Wait until the bot is ready before starting the loop'''
        await self.wait_until_ready()

async def main():
    '''Main entry point for the script'''
    logger.info("Starting DDC Heartbeat Monitor")
    
    # Validate configuration
    if not BOT_TOKEN or BOT_TOKEN == 'YOUR_BOT_TOKEN':
        logger.error("Invalid bot token. Please set a valid token.")
        return
    
    if not ALERT_CHANNEL_IDS:
        logger.error("No alert channels specified. Please configure at least one alert channel.")
        return
    
    # Create and start the client
    client = HeartbeatMonitor()
    
    try:
        await client.start(BOT_TOKEN)
    except discord.LoginFailure:
        logger.error("Failed to login. Please check your bot token.")
    except Exception as e:
        logger.error(f"Error starting bot: {{e}}", exc_info=True)
    finally:
        logger.info("Bot is shutting down")
        if not client.is_closed():
            await client.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down")
    except Exception as e:
        logger.error(f"Unhandled exception: {{e}}", exc_info=True)
        sys.exit(1)
"""
    return script

# Keep these as simple placeholders
def generate_bash_monitor_script(form_data):
    """Generate a simplified Bash-based heartbeat monitor script placeholder"""
    current_time = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    return f"""#!/bin/bash
# DockerDiscordControl (DDC) Heartbeat Monitor Script (Bash version)
# Generated on: {current_time}
#
# This is a simplified placeholder script.
# For full functionality, please use the Python monitor script instead.

echo "DockerDiscordControl Heartbeat Monitor (Bash)"
echo "This is a placeholder. For full monitoring functionality, please use the Python script."
echo ""
echo "The Python script provides the following benefits:"
echo "- Reliable Discord API connection"
echo "- Proper heartbeat detection"
echo "- Automatic alerts when heartbeats are missed"
echo "- Recovery notifications"

# Configuration:
DISCORD_WEBHOOK_URL="{form_data.get('alert_webhook_url', '')}"
DDC_BOT_USER_ID="{form_data.get('ddc_bot_user_id', '')}"
HEARTBEAT_CHANNEL_ID="{form_data.get('heartbeat_channel_id', '')}"
"""

def generate_batch_monitor_script(form_data):
    """Generate a simplified Windows Batch heartbeat monitor script placeholder"""
    current_time = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    return f"""@echo off
rem DockerDiscordControl (DDC) Heartbeat Monitor Script (Windows Batch version)
rem Generated on: {current_time}
rem
rem This is a simplified placeholder script.
rem For full functionality, please use the Python monitor script instead.

echo DockerDiscordControl Heartbeat Monitor (Windows Batch)
echo This is a placeholder. For full monitoring functionality, please use the Python script.
echo.
echo The Python script provides the following benefits:
echo - Reliable Discord API connection
echo - Proper heartbeat detection
echo - Automatic alerts when heartbeats are missed
echo - Recovery notifications

rem Configuration:
set "DISCORD_WEBHOOK_URL={form_data.get('alert_webhook_url', '')}"
set "DDC_BOT_USER_ID={form_data.get('ddc_bot_user_id', '')}"
set "HEARTBEAT_CHANNEL_ID={form_data.get('heartbeat_channel_id', '')}"

pause
"""

@main_bp.route('/', methods=['GET'])
# Use direct auth decorator
@auth.login_required 
def config_page():
    logger = current_app.logger
    config = load_config()
    now = datetime.now().strftime("%Y%m%d%H%M%S") # datetime is now imported
    live_containers_list, cache_error = get_docker_containers_live(logger)
    
    configured_servers = {}
    for server in config.get('servers', []):
        server_name = server.get('docker_name')
        if server_name:
            configured_servers[server_name] = server
            
    # NEW: Load active containers from the shared data class
    # Update active containers from configuration
    load_active_containers_from_config()
    active_container_names = get_active_containers()
    
    # Debug output
    logger.debug(f"Selected servers in config: {config.get('selected_servers', [])}")
    logger.debug(f"Active container names for task form: {active_container_names}")

    # Format cache timestamp for display
    last_cache_update = docker_cache.get('timestamp')
    formatted_timestamp = "Never"
    if last_cache_update:
        formatted_timestamp = datetime.fromtimestamp(last_cache_update).strftime('%Y-%m-%d %H:%M:%S')
    
    # Try to get the timestamp from the global_timestamp field, which is used in the newer code
    if formatted_timestamp == "Never" and docker_cache.get('global_timestamp'):
        try:
            formatted_timestamp = datetime.fromtimestamp(docker_cache['global_timestamp']).strftime('%Y-%m-%d %H:%M:%S')
            logger.debug(f"Using global_timestamp for container list update time: {formatted_timestamp}")
        except Exception as e:
            logger.error(f"Error formatting global_timestamp: {e}")
    
    # Load schedules for display on the main page
    timezone_str = config.get('timezone', 'Europe/Berlin')
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
                tz = pytz.timezone(timezone_str)
                next_run_dt = next_run_dt.replace(tzinfo=pytz.UTC).astimezone(tz)
            next_run = next_run_dt.strftime("%Y-%m-%d %H:%M %Z")
        
        last_run = None
        if task.last_run_ts:
            last_run_dt = datetime.utcfromtimestamp(task.last_run_ts)
            if timezone_str:
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
    
    return render_template('config.html', 
                           config=config,
                           common_timezones=COMMON_TIMEZONES, # Use imported COMMON_TIMEZONES
                           current_timezone=config.get('selected_timezone', 'UTC'),
                           all_containers=live_containers_list,  # Renamed from 'containers' to 'all_containers'
                           configured_servers=configured_servers,  # Added
                           active_container_names=active_container_names, # NEW Added
                           cache_error=cache_error,
                           docker_cache=docker_cache,  # Pass the entire docker_cache for direct access in template
                           last_cache_update=last_cache_update,
                           formatted_timestamp=formatted_timestamp,
                           auto_refresh_interval=config.get('auto_refresh_interval', 30),
                           version_tag=now, 
                           show_clear_logs_button=config.get('show_clear_logs_button', True),
                           show_download_logs_button=config.get('show_download_logs_button', True),
                           DEFAULT_CONFIG=DEFAULT_CONFIG, # Add DEFAULT_CONFIG
                           tasks=formatted_tasks # Add schedule data
                          )

@main_bp.route('/save_config_api', methods=['POST'])
# Use direct auth decorator
@auth.login_required
def save_config_api():
    logger = current_app.logger
    logger.info("save_config_api (blueprint) called...")
    result = {'success': False, 'message': 'An unexpected error occurred.'}
    
    try:
        from utils.config_loader import (
            process_config_form, BOT_CONFIG_FILE, DOCKER_CONFIG_FILE, 
            CHANNELS_CONFIG_FILE, WEB_CONFIG_FILE
        )
        
        # Explicitly import server_order utilities
        try:
            from utils.server_order import save_server_order
            server_order_utils_available = True
        except ImportError:
            server_order_utils_available = False
            logger.warning("Server order utilities not available, server order changes will require restart")
        
        # Is configuration splitting enabled?
        config_split_enabled = request.form.get('config_split_enabled') == '1'
        
        # Process form
        form_data = request.form.to_dict(flat=False)
        
        # Convert all lists with only one element to normal values
        # This logic can be adjusted if you want to keep certain fields as lists
        cleaned_form_data = {}
        for key, value in form_data.items():
            if isinstance(value, list) and len(value) == 1:
                cleaned_form_data[key] = value[0]
            else:
                cleaned_form_data[key] = value
        
        # Perform configuration processing
        processed_data, success, message = process_config_form(cleaned_form_data, load_config())
        
        # Process server order separately for immediate effect
        if success and server_order_utils_available:
            server_order = processed_data.get('server_order')
            if server_order:
                # If it's a string with separators, split it
                if isinstance(server_order, str):
                    server_order = [name.strip() for name in server_order.split('__,__') if name.strip()]
                
                # Save to dedicated file
                save_server_order(server_order)
                logger.info(f"Server order saved separately: {server_order}")
        
        # List of saved configuration files
        saved_files = []
        
        if success:
            # Save configuration
            save_config(processed_data)
            
            # Update scheduler logging settings if they have changed
            try:
                # Explicitly ensure the debug mode is refreshed
                from utils.logging_utils import refresh_debug_status
                debug_status = refresh_debug_status()
                logger.info(f"Debug mode after config save: {'ENABLED' if debug_status else 'DISABLED'}")
                
                # Verify that debug setting was properly saved
                config_check = load_config()
                saved_debug_status = config_check.get('scheduler_debug_mode', False)
                if saved_debug_status != debug_status:
                    logger.warning(f"Debug status mismatch! Requested: {debug_status}, Saved: {saved_debug_status}")
                    # Force an additional save with correct debug status
                    config_check['scheduler_debug_mode'] = debug_status
                    save_config(config_check)
                    logger.info(f"Forced additional save with debug status: {debug_status}")
                
                # Import here to avoid circular imports
                from utils.scheduler import initialize_logging
                initialize_logging()
                logger.info("Scheduler logging settings updated after configuration save")
            except Exception as e:
                logger.warning(f"Failed to update scheduler logging: {str(e)}")
            
            # Prepare file paths for display (filenames only)
            saved_files = [
                os.path.basename(BOT_CONFIG_FILE),
                os.path.basename(DOCKER_CONFIG_FILE),
                os.path.basename(CHANNELS_CONFIG_FILE),
                os.path.basename(WEB_CONFIG_FILE)
            ]
            
            logger.info(f"Configuration saved successfully via API: {message}")
            log_user_action("SAVE", "Configuration", source="Web UI Blueprint")
            result = {
                'success': True, 
                'message': message or 'Configuration saved successfully.',
                'config_files': saved_files if config_split_enabled else []
            }
            flash(result['message'], 'success')
        else:
            logger.warning(f"Failed to save configuration via API: {message}")
            result = {'success': False, 'message': message or 'Failed to save configuration.'}
            flash(result['message'], 'error')

    except Exception as e:
        logger.error(f"Unexpected error saving configuration via API (blueprint): {str(e)}", exc_info=True)
        result['message'] = f"Error: {str(e)}"
        flash(f"Error saving configuration: {str(e)}", 'danger')
    
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
    Generate and download the standalone DDC Heartbeat Monitor application.
    """
    logger = current_app.logger
    
    try:
        # Get form data from request
        form_data = request.form.to_dict()
        
        # Extract monitoring configuration
        monitor_bot_token = form_data.get('monitor_bot_token', '')
        ddc_bot_user_id = form_data.get('ddc_bot_user_id', '')
        heartbeat_channel_id = form_data.get('heartbeat_channel_id', '')
        alert_channel_ids = form_data.get('alert_channel_ids', '')
        monitor_timeout_seconds = form_data.get('monitor_timeout_seconds', '300')
        
        # Validate required fields
        if not heartbeat_channel_id or not ddc_bot_user_id:
            logger.warning("Missing required fields for monitor download")
            flash("Heartbeat Channel ID and DDC Bot User ID are required.", "warning")
            return redirect(url_for('.config_page'))
        
        if not monitor_bot_token:
            logger.warning("Missing bot token for monitor")
            flash("Monitor Bot Token is required.", "warning")
            return redirect(url_for('.config_page'))
        
        if not alert_channel_ids:
            logger.warning("Missing alert channels for monitor")
            flash("At least one Alert Channel ID is required.", "warning")
            return redirect(url_for('.config_page'))
        
        # Parse alert channel IDs
        try:
            alert_channel_list = [int(ch.strip()) for ch in alert_channel_ids.split(',') if ch.strip()]
        except ValueError:
            flash("Invalid Alert Channel IDs. Please use comma-separated numbers.", "warning")
            return redirect(url_for('.config_page'))
        
        # Create configuration for the standalone monitor
        monitor_config = {
            "monitor": {
                "bot_token": monitor_bot_token,
                "ddc_bot_user_id": int(ddc_bot_user_id),
                "heartbeat_channel_id": int(heartbeat_channel_id),
                "alert_channel_ids": alert_channel_list,
                "heartbeat_timeout_seconds": int(monitor_timeout_seconds),
                "check_interval_seconds": 30
            },
            "logging": {
                "level": "INFO",
                "file_enabled": True,
                "file_name": "ddc_heartbeat_monitor.log",
                "console_enabled": True
            },
            "alerts": {
                "startup_notification": True,
                "recovery_notification": True,
                "include_timestamp": True,
                "mention_roles": []
            }
        }
        
        # Create a ZIP file with all monitor files
        import zipfile
        import tempfile
        from pathlib import Path
        
        # Create temporary directory
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # Read the monitor application file
            monitor_app_path = Path(__file__).parent.parent.parent / "heartbeat_monitor" / "ddc_heartbeat_monitor.py"
            readme_path = Path(__file__).parent.parent.parent / "heartbeat_monitor" / "README.md"
            requirements_path = Path(__file__).parent.parent.parent / "heartbeat_monitor" / "requirements.txt"
            run_bat_path = Path(__file__).parent.parent.parent / "heartbeat_monitor" / "run_monitor.bat"
            run_sh_path = Path(__file__).parent.parent.parent / "heartbeat_monitor" / "run_monitor.sh"
            
            # Create ZIP file
            zip_path = temp_path / "ddc_heartbeat_monitor.zip"
            
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                # Add main application
                if monitor_app_path.exists():
                    zipf.write(monitor_app_path, "ddc_heartbeat_monitor.py")
                
                # Add README
                if readme_path.exists():
                    zipf.write(readme_path, "README.md")
                
                # Add requirements
                if requirements_path.exists():
                    zipf.write(requirements_path, "requirements.txt")
                
                # Add launcher scripts
                if run_bat_path.exists():
                    zipf.write(run_bat_path, "run_monitor.bat")
                
                if run_sh_path.exists():
                    zipf.write(run_sh_path, "run_monitor.sh")
                
                # Add configured config.json
                config_json = json.dumps(monitor_config, indent=2)
                zipf.writestr("config.json", config_json)
                
                # Add example config
                example_config = monitor_config.copy()
                example_config["monitor"]["bot_token"] = "YOUR_MONITOR_BOT_TOKEN_HERE"
                example_config["monitor"]["ddc_bot_user_id"] = 123456789012345678
                example_config["monitor"]["heartbeat_channel_id"] = 123456789012345678
                example_config["monitor"]["alert_channel_ids"] = [123456789012345678]
                example_config_json = json.dumps(example_config, indent=2)
                zipf.writestr("config.json.example", example_config_json)
                
                # Add installation instructions
                install_instructions = """# DDC Heartbeat Monitor - Quick Setup

## What's included:
- ddc_heartbeat_monitor.py - Main application
- config.json - Pre-configured with your settings
- config.json.example - Template for future use
- requirements.txt - Python dependencies
- run_monitor.bat - Windows launcher
- run_monitor.sh - macOS/Linux launcher
- README.md - Complete documentation

## Quick Start:

### Windows:
1. Double-click run_monitor.bat
2. Follow the prompts

### macOS/Linux:
1. Open Terminal
2. Navigate to this folder
3. Run: ./run_monitor.sh

### Manual:
1. Install Python 3.7+
2. Run: pip install discord.py
3. Run: python ddc_heartbeat_monitor.py

## Configuration:
Your settings are already configured in config.json.
Edit this file if you need to make changes.

## Support:
See README.md for detailed documentation and troubleshooting.
"""
                zipf.writestr("INSTALL.txt", install_instructions)
            
            # Read the ZIP file and send it
            with open(zip_path, 'rb') as f:
                zip_data = f.read()
        
        # Log action
        log_user_action(
            action="DOWNLOAD", 
            target="DDC Heartbeat Monitor (Standalone Application)", 
            source="Web UI"
        )
        logger.info("Generated and downloaded standalone heartbeat monitor application")
        
        # Create response
        response = make_response(zip_data)
        response.headers['Content-Type'] = 'application/zip'
        response.headers['Content-Disposition'] = 'attachment; filename=ddc_heartbeat_monitor.zip'
        
        return response
        
    except Exception as e:
        logger.error(f"Error generating monitor application: {e}", exc_info=True)
        flash(f"Error generating monitor application: {str(e)}", "danger")
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
                'message': f"Error refreshing containers: {error}"
            })
        
        # Log the success
        log_user_action("REFRESH", "Docker Container List", source="Web UI")
        
        # Get the timestamp for the response
        timestamp = docker_cache.get('global_timestamp', time.time())
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
            'message': f"Unexpected error: {str(e)}"
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
            'message': f"Error: {str(e)}"
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
            'message': f"Error: {str(e)}"
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
            'message': f"Error: {str(e)}",
            'is_enabled': False
        })
