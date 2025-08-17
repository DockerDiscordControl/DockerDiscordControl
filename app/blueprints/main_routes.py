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
import traceback
import pytz

# Import auth from app.auth
from app.auth import auth 
from utils.config_loader import load_config, save_config, DEFAULT_CONFIG # Import DEFAULT_CONFIG

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
from utils.scheduler import (
    load_tasks, 
    DAYS_OF_WEEK
)
from utils.action_logger import log_user_action
from utils.spam_protection_manager import get_spam_protection_manager

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
    """Generate a REST-only Python heartbeat monitor script (no Gateway).
    Uses plain string assembly to avoid brace-escaping issues.
    """
    monitor_bot_token = (form_data.get('monitor_bot_token', '') or '').strip()
    alert_webhook_url = (form_data.get('alert_webhook_url', '') or '').strip()

    raw_ddc_id = (form_data.get('ddc_bot_user_id', '') or '').strip()
    raw_channel_id = (form_data.get('heartbeat_channel_id', '') or '').strip()
    ddc_id = int(''.join(ch for ch in raw_ddc_id if ch.isdigit()) or '0')
    channel_id = int(''.join(ch for ch in raw_channel_id if ch.isdigit()) or '0')

    try:
        timeout_val = int(str(form_data.get('monitor_timeout_seconds', '271')).strip() or '271')
        if timeout_val < 60:
            timeout_val = 60
    except Exception:
        timeout_val = 271

    alert_ids_raw = form_data.get('alert_channel_ids', '')
    alert_ids = []
    for ch in (alert_ids_raw or '').split(','):
        digits = ''.join(c for c in ch.strip() if c.isdigit())
        if digits:
            alert_ids.append(int(digits))

    current_time = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')

    lines = []
    lines.append("#!/usr/bin/env python3\n")
    lines.append("# -*- coding: utf-8 -*-\n")
    lines.append("'''\n")
    lines.append("DockerDiscordControl (DDC) Heartbeat Monitor Script (REST-only)\n")
    lines.append("===============================================================\n\n")
    lines.append("Monitors the heartbeat messages sent by the DDC bot by polling Discord's REST API.\n")
    lines.append("No Gateway/WebSocket connection is opened, so you can reuse the same bot token.\n\n")
    lines.append("Generated on: " + current_time + "\n\n")
    lines.append("Requirements:\n  pip install requests\n")
    lines.append("'''\n\n")
    lines.append("import logging\nimport sys\nimport time\nfrom datetime import datetime, timezone\nimport requests\n\n")
    lines.append("# === Configuration ===\n")
    lines.append("BOT_TOKEN = " + repr(monitor_bot_token) + "\n")
    lines.append("DDC_BOT_USER_ID = " + str(ddc_id) + "\n")
    lines.append("HEARTBEAT_CHANNEL_ID = " + str(channel_id) + "\n")
    lines.append("ALERT_CHANNEL_IDS = " + repr(alert_ids) + "\n")
    lines.append("ALERT_WEBHOOK_URL = " + repr(alert_webhook_url) + "\n")
    lines.append("HEARTBEAT_TIMEOUT_SECONDS = " + str(timeout_val) + "\n")
    lines.append("API_BASE = 'https://discord.com/api/v10'\n\n")
    # Core script (no formatting braces processed here)
    core = """
# === Logging Setup ===
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger('ddc_monitor_rest')

session = requests.Session()
session.headers.update({'Authorization': f'Bot {BOT_TOKEN}', 'Content-Type': 'application/json'})

def resolve_ddc_bot_user_id() -> int:
    try:
        url = f"{API_BASE}/users/@me"
        resp = session.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return int(data.get('id', 0))
    except Exception as e:
        logger.warning(f'Failed to resolve bot user ID: {e}')
        return 0

def _parse_discord_timestamp(iso_ts: str) -> datetime:
    if not iso_ts:
        return datetime.now(timezone.utc)
    if iso_ts.endswith('Z'):
        iso_ts = iso_ts[:-1] + '+00:00'
    try:
        dt = datetime.fromisoformat(iso_ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)

def fetch_recent_messages(channel_id: int, limit: int = 20):
    url = f"{API_BASE}/channels/{channel_id}/messages?limit={limit}"
    resp = session.get(url, timeout=15)
    resp.raise_for_status()
    return resp.json()

def find_last_heartbeat_timestamp(messages):
    for msg in messages:
        try:
            author = int(msg.get('author', {}).get('id', 0))
            content = msg.get('content') or ''
            if author == DDC_BOT_USER_ID and '❤️' in content:
                return _parse_discord_timestamp(msg.get('timestamp'))
        except Exception:
            continue
    return None

def send_alert_message(content: str):
    if ALERT_WEBHOOK_URL:
        try:
            session.post(ALERT_WEBHOOK_URL, json={'content': content}, timeout=10)
            logger.info('Alert sent via webhook')
            return
        except Exception as e:
            logger.warning(f'Webhook alert failed: {e}')
    for channel_id in ALERT_CHANNEL_IDS:
        try:
            url = f"{API_BASE}/channels/{channel_id}/messages"
            session.post(url, json={'content': content}, timeout=15)
            logger.info(f'Alert sent to channel {channel_id}')
        except Exception as e:
            logger.warning(f'Failed to send alert to channel {channel_id}: {e}')

def main():
    logger.info('Starting DDC Heartbeat Monitor (REST-only)')
    if not BOT_TOKEN:
        logger.error('BOT_TOKEN is required')
        sys.exit(1)
    if HEARTBEAT_CHANNEL_ID <= 0:
        logger.error('HEARTBEAT_CHANNEL_ID must be set')
        sys.exit(1)
    global DDC_BOT_USER_ID
    if DDC_BOT_USER_ID <= 0:
        tmp_id = resolve_ddc_bot_user_id()
        if tmp_id > 0:
            DDC_BOT_USER_ID = tmp_id
            logger.info(f'Resolved DDC bot user ID via REST: {tmp_id}')
        else:
            logger.error('Could not resolve DDC bot user ID via REST; please provide it manually')
            sys.exit(1)
    if not ALERT_WEBHOOK_URL and not ALERT_CHANNEL_IDS:
        logger.warning('No ALERT_WEBHOOK_URL or ALERT_CHANNEL_IDS configured; alerts will not be delivered')

    alert_sent = False
    last_heartbeat = None
    try:
        msgs = fetch_recent_messages(HEARTBEAT_CHANNEL_ID, limit=25)
        last_heartbeat = find_last_heartbeat_timestamp(msgs)
        if last_heartbeat:
            logger.info(f'Initialized last heartbeat from history: {last_heartbeat.isoformat()}')
        else:
            logger.info('No heartbeat found in recent history during initialization')
    except Exception as e:
        logger.warning(f'Initialization failed: {e}')

    while True:
        try:
            msgs = fetch_recent_messages(HEARTBEAT_CHANNEL_ID, limit=20)
            candidate = find_last_heartbeat_timestamp(msgs)
            now = datetime.now(timezone.utc)

            if candidate:
                if not last_heartbeat or candidate > last_heartbeat:
                    last_heartbeat = candidate
                    logger.debug(f'Updated last heartbeat to {last_heartbeat.isoformat()}')
                if alert_sent:
                    send_alert_message('✅ DDC Heartbeat Recovered')
                    alert_sent = False

            if last_heartbeat:
                elapsed = (now - last_heartbeat).total_seconds()
            else:
                elapsed = HEARTBEAT_TIMEOUT_SECONDS + 1

            if elapsed > HEARTBEAT_TIMEOUT_SECONDS and not alert_sent:
                send_alert_message(f'⚠️ DDC Heartbeat Missing: no heartbeat for {int(elapsed)}s (channel {HEARTBEAT_CHANNEL_ID})')
                alert_sent = True

        except requests.HTTPError as http_err:
            logger.warning(f'HTTP error: {http_err}')
        except Exception as e:
            logger.warning(f'Unexpected error: {e}')
        finally:
            time.sleep(30)

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info('Shutting down')
        sys.exit(0)
"""
    lines.append(core)
    return ''.join(lines)

# Keep these as simple placeholders
def generate_bash_monitor_script(form_data):
    """Generate a Bash-based heartbeat monitor script (requires curl + jq + GNU date)."""
    current_time = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')

    # Use existing bot token from configuration (no separate input)
    try:
        from utils.config_cache import get_cached_config
        cfg = get_cached_config() or {}
        token = (cfg.get('bot_token_decrypted_for_usage') or cfg.get('bot_token') or '')
    except Exception:
        token = ''
    raw_ddc_id = (form_data.get('ddc_bot_user_id', '') or '').strip()
    raw_channel_id = (form_data.get('heartbeat_channel_id', '') or '').strip()
    webhook = (form_data.get('alert_webhook_url', '') or '').strip()
    timeout_raw = (form_data.get('monitor_timeout_seconds', '271') or '271').strip()

    ddc_id = ''.join(ch for ch in raw_ddc_id if ch.isdigit()) or '0'
    channel_id = ''.join(ch for ch in raw_channel_id if ch.isdigit()) or '0'
    try:
        timeout_val = max(60, int(timeout_raw))
    except Exception:
        timeout_val = 271

    return f"""#!/bin/bash
set -euo pipefail

# DockerDiscordControl (DDC) Heartbeat Monitor Script (Bash version)
# Generated on: {current_time}
#
# Requirements:
# - curl, jq, GNU date (Linux). On macOS, install coreutils (gdate) and adjust DATE_CMD.
#
# Configuration
MONITOR_BOT_TOKEN='{token}'
DDC_BOT_USER_ID={ddc_id}
HEARTBEAT_CHANNEL_ID={channel_id}
ALERT_WEBHOOK_URL='{webhook}'
HEARTBEAT_TIMEOUT_SECONDS={timeout_val}
API_VERSION=v10

# Commands (adjust DATE_CMD to 'gdate' on macOS if needed)
DATE_CMD=date

log() {{ echo "[DDC-MONITOR] $1"; }}

if [[ -z "$MONITOR_BOT_TOKEN" || -z "$ALERT_WEBHOOK_URL" ]]; then
  log "ERROR: MONITOR_BOT_TOKEN and ALERT_WEBHOOK_URL are required."
  exit 1
fi

fetch_messages() {{
  curl -sS -H "Authorization: Bot $MONITOR_BOT_TOKEN" \
       -H "Content-Type: application/json" \
       "https://discord.com/api/$API_VERSION/channels/$HEARTBEAT_CHANNEL_ID/messages?limit=20"
}}

send_alert() {{
  local elapsed="$1"; local last_ts="$2"
  local payload
  payload=$(jq -n --arg content "⚠️ DDC Heartbeat Missing: No heartbeat from <@$DDC_BOT_USER_ID> for ${{elapsed}}s. Last: ${{last_ts}}" '{{content: $content}}')
  curl -sS -H "Content-Type: application/json" -X POST -d "$payload" "$ALERT_WEBHOOK_URL" >/dev/null || true
  log "Alert sent via webhook"
}}

resp=$(fetch_messages)
if echo "$resp" | jq -e . >/dev/null 2>&1; then
  :
else
  log "ERROR: Failed to parse Discord API response."
  exit 1
fi

# Find latest heartbeat message from the DDC bot containing the heart symbol
last_ts=$(echo "$resp" | jq -r "[ .[] | select(.author.id==\"$DDC_BOT_USER_ID\" and (.content|tostring|contains(\"❤️\"))) ][0].timestamp")

now_epoch=$($DATE_CMD -u +%s)
if [[ "$last_ts" == "null" || -z "$last_ts" ]]; then
  # No heartbeat found in recent history; treat as missing
  send_alert "$HEARTBEAT_TIMEOUT_SECONDS" "Never"
  exit 0
fi

# Convert ISO timestamp to epoch seconds (GNU date)
last_epoch=$($DATE_CMD -u -d "$last_ts" +%s 2>/dev/null || echo 0)
if [[ "$last_epoch" == "0" ]]; then
  log "WARNING: Could not parse timestamp '$last_ts'"
  send_alert "$HEARTBEAT_TIMEOUT_SECONDS" "$last_ts"
  exit 0
fi

elapsed=$(( now_epoch - last_epoch ))
log "Last heartbeat at $last_ts (elapsed ${{elapsed}}s)"

if (( elapsed > HEARTBEAT_TIMEOUT_SECONDS )); then
  send_alert "$elapsed" "$last_ts"
else
  log "Heartbeat OK"
fi
"""

def generate_batch_monitor_script(form_data):
    """Generate a Windows Batch heartbeat monitor script (uses PowerShell for JSON)."""
    current_time = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')

    try:
        from utils.config_cache import get_cached_config
        cfg = get_cached_config() or {}
        token = (cfg.get('bot_token_decrypted_for_usage') or cfg.get('bot_token') or '')
    except Exception:
        token = ''
    raw_ddc_id = (form_data.get('ddc_bot_user_id', '') or '').strip()
    raw_channel_id = (form_data.get('heartbeat_channel_id', '') or '').strip()
    webhook = (form_data.get('alert_webhook_url', '') or '').strip()
    timeout_raw = (form_data.get('monitor_timeout_seconds', '271') or '271').strip()

    ddc_id = ''.join(ch for ch in raw_ddc_id if ch.isdigit()) or '0'
    channel_id = ''.join(ch for ch in raw_channel_id if ch.isdigit()) or '0'
    try:
        timeout_val = max(60, int(timeout_raw))
    except Exception:
        timeout_val = 271

    return f"""@echo off
REM DockerDiscordControl (DDC) Heartbeat Monitor Script (Windows Batch)
REM Generated on: {current_time}

set "MONITOR_BOT_TOKEN={token}"
set "DDC_BOT_USER_ID={ddc_id}"
set "HEARTBEAT_CHANNEL_ID={channel_id}"
set "ALERT_WEBHOOK_URL={webhook}"
set "HEARTBEAT_TIMEOUT_SECONDS={timeout_val}"

if "%MONITOR_BOT_TOKEN%"=="" (
  echo [DDC-MONITOR] ERROR: MONITOR_BOT_TOKEN is required.
  exit /b 1
)
if "%ALERT_WEBHOOK_URL%"=="" (
  echo [DDC-MONITOR] ERROR: ALERT_WEBHOOK_URL is required.
  exit /b 1
)

powershell -NoProfile -Command ^
  "$headers = @{{ \"Authorization\" = \"Bot $env:MONITOR_BOT_TOKEN\" }}; ^
   $url = \"https://discord.com/api/v10/channels/$env:HEARTBEAT_CHANNEL_ID/messages?limit=20\"; ^
   try {{ ^
     $resp = Invoke-RestMethod -Method GET -Headers $headers -Uri $url -ErrorAction Stop; ^
   }} catch {{ ^
     Write-Host \"[DDC-MONITOR] ERROR: Failed to fetch messages: $($_.Exception.Message)\"; exit 1 ^
   }}; ^
   $ddcId = [int64]$env:DDC_BOT_USER_ID; ^
   $hb = $resp | Where-Object {{ $_.author.id -eq $ddcId -and $_.content -like '*❤️*' }} | Select-Object -First 1; ^
   $now = Get-Date; ^
   if (-not $hb) {{ ^
     $payload = {{ content = \"⚠️ DDC Heartbeat Missing: No heartbeat from <@$env:DDC_BOT_USER_ID>.\" }} | ConvertTo-Json; ^
     try {{ Invoke-RestMethod -Method POST -ContentType 'application/json' -Uri $env:ALERT_WEBHOOK_URL -Body $payload }} catch {{ }}; ^
     Write-Host \"[DDC-MONITOR] Alert sent (no heartbeat in history).\"; ^
     exit 0 ^
   }}; ^
   $ts = Get-Date $hb.timestamp; ^
   $elapsed = [int]($now.ToUniversalTime() - $ts.ToUniversalTime()).TotalSeconds; ^
   Write-Host \"[DDC-MONITOR] Last heartbeat at $($ts.ToString('o')) (elapsed $elapsed s)\"; ^
   if ($elapsed -gt [int]$env:HEARTBEAT_TIMEOUT_SECONDS) {{ ^
     $payload = @{{ content = \"⚠️ DDC Heartbeat Missing: \" + $elapsed + \"s since last heartbeat from <@$env:DDC_BOT_USER_ID>.\" }} | ConvertTo-Json; ^
     try {{ Invoke-RestMethod -Method POST -ContentType 'application/json' -Uri $env:ALERT_WEBHOOK_URL -Body $payload }} catch {{ }}; ^
     Write-Host \"[DDC-MONITOR] Alert sent via webhook.\" ^
   }} else {{ ^
     Write-Host \"[DDC-MONITOR] Heartbeat OK.\" ^
   }}"
"""

@main_bp.route('/', methods=['GET'])
# Use direct auth decorator
@auth.login_required 
def config_page():
    logger = current_app.logger
    
    # CRITICAL FIX: Use cached config instead of loading directly
    # This ensures we see the same config that was just saved
    from utils.config_cache import get_cached_config
    config = get_cached_config()
    
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
            tz = pytz.timezone(timezone_str)
            dt = datetime.fromtimestamp(docker_cache['global_timestamp'], tz=tz)
            formatted_timestamp = dt.strftime('%Y-%m-%d %H:%M:%S %Z')
            logger.debug(f"Using global_timestamp for container list update time: {formatted_timestamp}")
        except Exception as e:
            logger.error(f"Error formatting global_timestamp: {e}")
    
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
    container_names = [container.get("name", "Unknown") for container in live_containers_list] if live_containers_list else []
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
        'DDC_BACKGROUND_REFRESH_INTERVAL': get_setting_value('DDC_BACKGROUND_REFRESH_INTERVAL', '300'),
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
    
    return render_template('config.html', 
                           config=config_with_env,
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
                           DEFAULT_CONFIG=DEFAULT_CONFIG, # Add DEFAULT_CONFIG
                           tasks=formatted_tasks # Add schedule data
                          )

@main_bp.route('/save_config_api', methods=['POST'])
# Use direct auth decorator
@auth.login_required
def save_config_api():
    logger = current_app.logger
    print("[CONFIG-DEBUG] save_config_api endpoint called")
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
        
        # Load current config to check for critical changes
        current_config = load_config()
        
        # Perform configuration processing
        processed_data, success, message = process_config_form(cleaned_form_data, current_config)
        if not success:
            logger.warning(f"Configuration processing failed: {message}")
            message = "An error occurred while processing the configuration."
        
        # Check file permissions before attempting to save
        if success:
            from utils.config_manager import get_config_manager
            config_manager = get_config_manager()
            permission_results = config_manager.check_all_permissions()
            
            permission_errors = []
            for file_path, (has_permission, error_msg) in permission_results.items():
                if not has_permission:
                    permission_errors.append(error_msg)
            
            if permission_errors:
                logger.error(f"Cannot save configuration due to permission errors: {permission_errors}")
                result = {
                    'success': False,
                    'message': 'Cannot save configuration: File permission errors. Check server logs for details.',
                    'permission_errors': permission_errors
                }
                flash('Error: Configuration files are not writable. Please check file permissions.', 'danger')
                return jsonify(result) if request.headers.get('X-Requested-With') == 'XMLHttpRequest' else redirect(url_for('.config_page'))
        
        # Check if critical settings that require cache invalidation have changed
        critical_settings_changed = False
        if success:
            # Check for language change
            old_language = current_config.get('language', 'en')
            new_language = processed_data.get('language', 'en')
            if old_language != new_language:
                logger.info(f"Language changed from '{old_language}' to '{new_language}' - cache invalidation required")
                critical_settings_changed = True
            
            # Check for timezone change
            old_timezone = current_config.get('timezone', 'Europe/Berlin')
            new_timezone = processed_data.get('timezone', 'Europe/Berlin')
            if old_timezone != new_timezone:
                logger.info(f"Timezone changed from '{old_timezone}' to '{new_timezone}' - cache invalidation required")
                critical_settings_changed = True
        
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
            # Save main configuration
            save_config(processed_data)
            
            # Save container info to separate JSON files
            container_names = []
            if 'servers' in processed_data:
                container_names = [server.get('docker_name') for server in processed_data['servers'] if server.get('docker_name')]
            
            # Save container info to separate JSON files
            if container_names:
                info_results = save_container_info_from_web(cleaned_form_data, container_names)
                logger.info(f"Container info save results: {info_results}")
            
            # Invalidate caches if critical settings changed
            if critical_settings_changed:
                try:
                    # Invalidate ConfigManager cache
                    from utils.config_manager import get_config_manager
                    config_manager = get_config_manager()
                    config_manager.invalidate_cache()
                    logger.info("ConfigManager cache invalidated due to critical settings change")
                    
                    # Invalidate config cache
                    from utils.config_cache import get_config_cache
                    config_cache = get_config_cache()
                    config_cache.clear()
                    logger.info("Config cache cleared due to critical settings change")
                    
                    # Force reload of configuration in config cache
                    from utils.config_cache import init_config_cache
                    fresh_config = load_config()
                    init_config_cache(fresh_config)
                    logger.info("Config cache reinitialized with fresh configuration")
                    
                    # Clear translation manager cache if language changed
                    if old_language != new_language:
                        try:
                            from cogs.translation_manager import translation_manager
                            # Clear the translation cache to force reload with new language
                            if hasattr(translation_manager, '_'):
                                translation_manager._.cache_clear()
                            # Reset cached language to force fresh lookup
                            if hasattr(translation_manager, '_cached_language'):
                                delattr(translation_manager, '_cached_language')
                            logger.info(f"Translation manager cache cleared for language change: {old_language} -> {new_language}")
                        except Exception as e:
                            logger.warning(f"Could not clear translation manager cache: {e}")
                    
                except Exception as e:
                    logger.error(f"Error invalidating caches: {e}")
            
            # Update logging level settings if they have changed
            try:
                # Check if debug level toggle was changed
                config_check = load_config()
                debug_level_enabled = config_check.get('debug_level_enabled', False)
                current_level = 'DEBUG' if debug_level_enabled else 'INFO'
                
                logger.info(f"Log level after config save: {current_level}")
                
                # Update logging level for all loggers
                import logging
                root_logger = logging.getLogger()
                if debug_level_enabled:
                    root_logger.setLevel(logging.DEBUG)
                    # Also update specific loggers
                    for logger_name in ['ddc', 'gunicorn', 'discord', 'app']:
                        specific_logger = logging.getLogger(logger_name)
                        specific_logger.setLevel(logging.DEBUG)
                    logger.info("All loggers set to DEBUG level")
                else:
                    root_logger.setLevel(logging.INFO)
                    # Also update specific loggers
                    for logger_name in ['ddc', 'gunicorn', 'discord', 'app']:
                        specific_logger = logging.getLogger(logger_name)
                        specific_logger.setLevel(logging.INFO)
                    logger.info("All loggers set to INFO level")
                
                # Update scheduler logging if available
                try:
                    from utils.scheduler import initialize_logging
                    initialize_logging()
                    logger.info("Scheduler logging settings updated after configuration save")
                except ImportError:
                    logger.debug("Scheduler module not available for logging update")
                
            except Exception as e:
                logger.warning(f"Failed to update logging settings: {str(e)}")
            
            # Prepare file paths for display (filenames only)
            saved_files = [
                os.path.basename(BOT_CONFIG_FILE),
                os.path.basename(DOCKER_CONFIG_FILE),
                os.path.basename(CHANNELS_CONFIG_FILE),
                os.path.basename(WEB_CONFIG_FILE)
            ]
            
            logger.info(f"Configuration saved successfully via API: {message}")
            log_user_action("SAVE", "Configuration", source="Web UI Blueprint")
            
            # Add note about cache invalidation if critical settings changed
            if critical_settings_changed:
                message += " Critical settings changed - caches have been invalidated. Changes should take effect immediately."
            
            result = {
                'success': True, 
                'message': message or 'Configuration saved successfully.',
                'config_files': saved_files if config_split_enabled else [],
                'critical_settings_changed': critical_settings_changed
            }
            flash(result['message'], 'success')
        else:
            logger.warning(f"Failed to save configuration via API: {message}")
            result = {'success': False, 'message': message or 'Failed to save configuration.'}
            flash(result['message'], 'error')

    except Exception as e:
        logger.error(f"Unexpected error saving configuration via API (blueprint): {str(e)}", exc_info=True)
        result['message'] = "An error occurred while saving the configuration. Please check the logs for details."
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
    # Use cached config for consistency
    from utils.config_cache import get_cached_config
    config = get_cached_config()
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
        
        # Extract monitoring configuration
        monitor_bot_token = form_data.get('monitor_bot_token', '')
        ddc_bot_user_id = form_data.get('ddc_bot_user_id', '')
        heartbeat_channel_id = form_data.get('heartbeat_channel_id', '')
        alert_channel_ids = form_data.get('alert_channel_ids', '')
        alert_webhook_url = form_data.get('alert_webhook_url', '')
        monitor_timeout_seconds = form_data.get('monitor_timeout_seconds', '271')  # Default: ~4.5 minutes
        script_type = form_data.get('script_type', 'python')
        
        # Validate basic fields (common to all scripts)
        if not heartbeat_channel_id:
            logger.warning("Missing required field: heartbeat_channel_id")
            flash("Heartbeat Channel ID is required.", "warning")
            return redirect(url_for('.config_page'))
        
        # Validate script-specific fields
        if script_type == 'python' and not monitor_bot_token:
            logger.warning("Missing bot token for Python REST monitor script")
            flash("Bot Token is required for the Python REST monitor script.", "warning")
            return redirect(url_for('.config_page'))
        elif script_type in ['bash', 'batch']:
            if not alert_webhook_url:
                logger.warning("Missing webhook URL for shell scripts")
                flash("Webhook URL is required for Shell scripts.", "warning")
                return redirect(url_for('.config_page'))
            if not monitor_bot_token:
                logger.warning("Missing bot token for shell scripts (required to resolve bot ID via REST)")
                flash("Bot Token is required for Shell scripts to resolve the bot user ID.", "warning")
                return redirect(url_for('.config_page'))
        
        # Generate the appropriate script content
        if script_type == 'python':
            script_content = generate_python_monitor_script(form_data)
            file_extension = 'py'
            mime_type = 'text/x-python'
        elif script_type == 'bash':
            script_content = generate_bash_monitor_script(form_data)
            file_extension = 'sh'
            mime_type = 'text/x-shellscript'
        elif script_type == 'batch':
            script_content = generate_batch_monitor_script(form_data)
            file_extension = 'bat'
            mime_type = 'application/x-msdos-program'
        else:
            flash(f"Unknown script type: {script_type}", "danger")
            return redirect(url_for('.config_page'))
        
        # Create a buffer with the script content
        buffer = io.BytesIO(script_content.encode('utf-8'))
        buffer.seek(0)
        
        # Log action
        script_names = {
            'python': 'Python',
            'bash': 'Bash',
            'batch': 'Windows Batch'
        }
        log_user_action(
            action="DOWNLOAD", 
            target=f"Heartbeat monitor script ({script_names.get(script_type, script_type)})", 
            source="Web UI"
        )
        logger.info(f"Generated and downloaded heartbeat monitor script ({script_type})")
        
        return send_file(
            buffer, 
            as_attachment=True, 
            download_name=f'ddc_heartbeat_monitor.{file_extension}', 
            mimetype=mime_type
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
        from utils.config_cache import get_cached_config
        config = get_cached_config()
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
    logger = current_app.logger
    
    try:
        performance_data = {}
        
        # Get config cache statistics
        try:
            from utils.config_cache import get_cache_memory_stats
            performance_data['config_cache'] = get_cache_memory_stats()
        except Exception as e:
            logger.warning(f"Could not get config cache stats: {e}")
            performance_data['config_cache'] = {'error': str(e)}
        
        # Get Docker cache statistics
        try:
            from app.utils.web_helpers import docker_cache, cache_lock
            with cache_lock:
                cache_stats = {
                    'containers_count': len(docker_cache.get('containers', [])),
                    'access_count': docker_cache.get('access_count', 0),
                    'global_timestamp': docker_cache.get('global_timestamp'),
                    'last_cleanup': docker_cache.get('last_cleanup'),
                    'bg_refresh_running': docker_cache.get('bg_refresh_running', False),
                    'priority_containers_count': len(docker_cache.get('priority_containers', set())),
                    'container_timestamps_count': len(docker_cache.get('container_timestamps', {})),
                    'container_hashes_count': len(docker_cache.get('container_hashes', {})),
                    'error': docker_cache.get('error')
                }
                
                # Format timestamps
                if cache_stats['global_timestamp']:
                    cache_stats['global_timestamp_formatted'] = datetime.fromtimestamp(
                        cache_stats['global_timestamp']
                    ).strftime('%Y-%m-%d %H:%M:%S')
                
                if cache_stats['last_cleanup']:
                    cache_stats['last_cleanup_formatted'] = datetime.fromtimestamp(
                        cache_stats['last_cleanup']
                    ).strftime('%Y-%m-%d %H:%M:%S')
                
            performance_data['docker_cache'] = cache_stats
        except Exception as e:
            logger.warning(f"Could not get Docker cache stats: {e}")
            performance_data['docker_cache'] = {'error': str(e)}
        
        # Get scheduler service statistics
        try:
            from utils.scheduler_service import get_scheduler_stats
            performance_data['scheduler'] = get_scheduler_stats()
        except Exception as e:
            logger.warning(f"Could not get scheduler stats: {e}")
            performance_data['scheduler'] = {'error': str(e)}
        
        # Get system memory information
        try:
            import psutil
            memory = psutil.virtual_memory()
            performance_data['system_memory'] = {
                'total_mb': round(memory.total / (1024 * 1024), 2),
                'available_mb': round(memory.available / (1024 * 1024), 2),
                'percent_used': memory.percent,
                'free_mb': round(memory.free / (1024 * 1024), 2)
            }
        except Exception as e:
            logger.warning(f"Could not get system memory stats: {e}")
            performance_data['system_memory'] = {'error': str(e)}
        
        # Get current process memory usage
        try:
            import psutil
            import os
            process = psutil.Process(os.getpid())
            memory_info = process.memory_info()
            performance_data['process_memory'] = {
                'rss_mb': round(memory_info.rss / (1024 * 1024), 2),
                'vms_mb': round(memory_info.vms / (1024 * 1024), 2),
                'percent': round(process.memory_percent(), 2),
                'num_threads': process.num_threads()
            }
        except Exception as e:
            logger.warning(f"Could not get process memory stats: {e}")
            performance_data['process_memory'] = {'error': str(e)}
        
        # Add timestamp
        performance_data['timestamp'] = time.time()
        performance_data['timestamp_formatted'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        return jsonify({
            'success': True,
            'performance_data': performance_data
        })
        
    except Exception as e:
        logger.error(f"Error getting performance statistics: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': "Error getting performance statistics. Please check the logs for details."
        })

@main_bp.route('/api/spam-protection', methods=['GET'])
@auth.login_required
def get_spam_protection():
    """Get current spam protection settings."""
    try:
        spam_manager = get_spam_protection_manager()
        settings = spam_manager.load_settings()
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
        
        spam_manager = get_spam_protection_manager()
        success = spam_manager.save_settings(settings)
        
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
