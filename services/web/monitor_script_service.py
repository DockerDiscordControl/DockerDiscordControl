#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Monitor Script Service                         #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""
Monitor Script Service - Handles generation of heartbeat monitoring scripts in multiple formats
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class ScriptType(Enum):
    """Supported monitor script types."""
    PYTHON = "python"
    BASH = "bash"
    BATCH = "batch"


@dataclass
class MonitorScriptRequest:
    """Represents a monitor script generation request."""
    script_type: ScriptType
    monitor_bot_token: str = ""
    alert_webhook_url: str = ""
    ddc_bot_user_id: str = ""
    heartbeat_channel_id: str = ""
    monitor_timeout_seconds: str = "271"
    alert_channel_ids: str = ""


@dataclass
class MonitorScriptResult:
    """Represents the result of monitor script generation."""
    success: bool
    script_content: Optional[str] = None
    error: Optional[str] = None


class MonitorScriptService:
    """Service for generating heartbeat monitor scripts in various formats."""

    def __init__(self):
        self.logger = logger

    def generate_script(self, request: MonitorScriptRequest) -> MonitorScriptResult:
        """
        Generate a monitor script based on the request parameters.

        Args:
            request: MonitorScriptRequest with script type and configuration

        Returns:
            MonitorScriptResult with script content or error information
        """
        try:
            if request.script_type == ScriptType.PYTHON:
                script_content = self._generate_python_script(request)
            elif request.script_type == ScriptType.BASH:
                script_content = self._generate_bash_script(request)
            elif request.script_type == ScriptType.BATCH:
                script_content = self._generate_batch_script(request)
            else:
                return MonitorScriptResult(
                    success=False,
                    error=f"Unsupported script type: {request.script_type}"
                )

            return MonitorScriptResult(
                success=True,
                script_content=script_content
            )

        except (AttributeError, ValueError, TypeError) as e:
            # Script generation errors (invalid enum, type conversion, attribute access)
            self.logger.error(f"Script generation error for {request.script_type.value}: {e}", exc_info=True)
            return MonitorScriptResult(
                success=False,
                error=f"Error generating monitor script: {str(e)}"
            )

    def _generate_python_script(self, request: MonitorScriptRequest) -> str:
        """Generate a REST-only Python heartbeat monitor script."""
        # Parse and validate parameters
        ddc_id = int(''.join(ch for ch in request.ddc_bot_user_id if ch.isdigit()) or '0')
        channel_id = int(''.join(ch for ch in request.heartbeat_channel_id if ch.isdigit()) or '0')

        try:
            timeout_val = int(str(request.monitor_timeout_seconds).strip() or '271')
            if timeout_val < 60:
                timeout_val = 60
        except (ValueError, TypeError, AttributeError):
            # Integer parsing/conversion errors (invalid string, None, missing attribute)
            timeout_val = 271

        # Parse alert channel IDs
        alert_ids = []
        for ch in (request.alert_channel_ids or '').split(','):
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
        lines.append("BOT_TOKEN = " + repr(request.monitor_bot_token) + "\n")
        lines.append("DDC_BOT_USER_ID = " + str(ddc_id) + "\n")
        lines.append("HEARTBEAT_CHANNEL_ID = " + str(channel_id) + "\n")
        lines.append("ALERT_CHANNEL_IDS = " + repr(alert_ids) + "\n")
        lines.append("ALERT_WEBHOOK_URL = " + repr(request.alert_webhook_url) + "\n")
        lines.append("HEARTBEAT_TIMEOUT_SECONDS = " + str(timeout_val) + "\n")
        lines.append("API_BASE = 'https://discord.com/api/v10'\n\n")

        # Core Python script logic
        core_script = self._get_python_core_script()
        lines.append(core_script)

        return ''.join(lines)

    def _generate_bash_script(self, request: MonitorScriptRequest) -> str:
        """Generate a Bash-based heartbeat monitor script."""
        current_time = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')

        # Get bot token from configuration
        try:
            from utils.config import load_config
            cfg = load_config() or {}
            token = (cfg.get('bot_token_decrypted_for_usage') or cfg.get('bot_token') or '')
        except (ImportError, AttributeError, KeyError, FileNotFoundError, TypeError):
            # Config loading errors (module not found, missing attributes, missing keys, file errors, type errors)
            token = ''

        # Parse parameters
        ddc_id = ''.join(ch for ch in request.ddc_bot_user_id if ch.isdigit()) or '0'
        channel_id = ''.join(ch for ch in request.heartbeat_channel_id if ch.isdigit()) or '0'

        try:
            timeout_val = max(60, int(request.monitor_timeout_seconds))
        except (ValueError, TypeError, AttributeError):
            # Integer parsing/conversion errors (invalid string, None, missing attribute)
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
ALERT_WEBHOOK_URL='{request.alert_webhook_url}'
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
  curl -sS -H "Authorization: Bot $MONITOR_BOT_TOKEN" \\
       -H "Content-Type: application/json" \\
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
last_ts=$(echo "$resp" | jq -r "[ .[] | select(.author.id==\\"$DDC_BOT_USER_ID\\" and (.content|tostring|contains(\\"❤️\\"))) ][0].timestamp")

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

    def _generate_batch_script(self, request: MonitorScriptRequest) -> str:
        """Generate a Windows Batch heartbeat monitor script."""
        current_time = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')

        # Get bot token from configuration
        try:
            from utils.config import load_config
            cfg = load_config() or {}
            token = (cfg.get('bot_token_decrypted_for_usage') or cfg.get('bot_token') or '')
        except (ImportError, AttributeError, KeyError, FileNotFoundError, TypeError):
            # Config loading errors (module not found, missing attributes, missing keys, file errors, type errors)
            token = ''

        # Parse parameters
        ddc_id = ''.join(ch for ch in request.ddc_bot_user_id if ch.isdigit()) or '0'
        channel_id = ''.join(ch for ch in request.heartbeat_channel_id if ch.isdigit()) or '0'

        try:
            timeout_val = max(60, int(request.monitor_timeout_seconds))
        except (ValueError, TypeError, AttributeError):
            # Integer parsing/conversion errors (invalid string, None, missing attribute)
            timeout_val = 271

        return f"""@echo off
REM DockerDiscordControl (DDC) Heartbeat Monitor Script (Windows Batch)
REM Generated on: {current_time}

set "MONITOR_BOT_TOKEN={token}"
set "DDC_BOT_USER_ID={ddc_id}"
set "HEARTBEAT_CHANNEL_ID={channel_id}"
set "ALERT_WEBHOOK_URL={request.alert_webhook_url}"
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
  "$headers = @{{ \\"Authorization\\" = \\"Bot $env:MONITOR_BOT_TOKEN\\" }}; ^
   $url = \\"https://discord.com/api/v10/channels/$env:HEARTBEAT_CHANNEL_ID/messages?limit=20\\"; ^
   try {{ ^
     $resp = Invoke-RestMethod -Method GET -Headers $headers -Uri $url -ErrorAction Stop; ^
   }} catch {{ ^
     Write-Host \\"[DDC-MONITOR] ERROR: Failed to fetch messages: $($_.Exception.Message)\\"; exit 1 ^
   }}; ^
   $ddcId = [int64]$env:DDC_BOT_USER_ID; ^
   $hb = $resp | Where-Object {{ $_.author.id -eq $ddcId -and $_.content -like '*❤️*' }} | Select-Object -First 1; ^
   $now = Get-Date; ^
   if (-not $hb) {{ ^
     $payload = {{ content = \\"⚠️ DDC Heartbeat Missing: No heartbeat from <@$env:DDC_BOT_USER_ID>.\\" }} | ConvertTo-Json; ^
     try {{ Invoke-RestMethod -Method POST -ContentType 'application/json' -Uri $env:ALERT_WEBHOOK_URL -Body $payload }} catch {{ }}; ^
     Write-Host \\"[DDC-MONITOR] Alert sent (no heartbeat in history).\\"; ^
     exit 0 ^
   }}; ^
   $ts = Get-Date $hb.timestamp; ^
   $elapsed = [int]($now.ToUniversalTime() - $ts.ToUniversalTime()).TotalSeconds; ^
   Write-Host \\"[DDC-MONITOR] Last heartbeat at $($ts.ToString('o')) (elapsed $elapsed s)\\"; ^
   if ($elapsed -gt [int]$env:HEARTBEAT_TIMEOUT_SECONDS) {{ ^
     $payload = @{{ content = \\"⚠️ DDC Heartbeat Missing: \\" + $elapsed + \\"s since last heartbeat from <@$env:DDC_BOT_USER_ID>.\\" }} | ConvertTo-Json; ^
     try {{ Invoke-RestMethod -Method POST -ContentType 'application/json' -Uri $env:ALERT_WEBHOOK_URL -Body $payload }} catch {{ }}; ^
     Write-Host \\"[DDC-MONITOR] Alert sent via webhook.\\" ^
   }} else {{ ^
     Write-Host \\"[DDC-MONITOR] Heartbeat OK.\\" ^
   }}"
"""

    def _get_python_core_script(self) -> str:
        """Get the core Python script logic."""
        return """
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


# Singleton instance
_monitor_script_service = None


def get_monitor_script_service() -> MonitorScriptService:
    """Get the singleton MonitorScriptService instance."""
    global _monitor_script_service
    if _monitor_script_service is None:
        _monitor_script_service = MonitorScriptService()
    return _monitor_script_service