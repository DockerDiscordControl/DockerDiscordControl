# Startup Optimization Changes for Main Repository

## Overview
This document describes the startup optimization changes made to the Mac repository that should be applied to the main DockerDiscordControl repository. These changes eliminate crash loops and reduce resource usage when the Discord bot token is not configured.

## Problem Statement
**Before:**
- Container crashes immediately when Discord token is missing
- Web-UI restarts aggressively every 2-3 seconds (supervisord auto-restart)
- Excessive resource usage from constant crash loops
- Poor user experience with spam logs

**After:**
- Container runs stably without token
- Bot implements intelligent retry loop with countdown (configurable interval, default 60s)
- Web-UI waits silently for token configuration (synchronized with bot timing)
- No crash loops, minimal resource usage
- Clean, informative logs

## Changes Required

### 1. bot.py - Add Intelligent Retry Loop

**Location:** `bot.py` around line 95-130 (in the `main()` function, after `bot = create_bot(runtime)`)

**Add import at top of file:**
```python
import time
```

**Replace the token retrieval section with:**
```python
def main() -> None:
    """Main entry point for the Discord bot."""

    configure_environment()
    config = load_main_configuration()
    runtime = build_runtime(config)

    _ensure_timezone(runtime.logger)

    bot = create_bot(runtime)
    register_event_handlers(bot, runtime)

    # Retry loop for missing token with countdown
    retry_interval = int(os.getenv("DDC_TOKEN_RETRY_INTERVAL", "60"))
    max_retries = int(os.getenv("DDC_TOKEN_MAX_RETRIES", "0"))  # 0 = infinite
    retry_count = 0

    while True:
        token = get_decrypted_bot_token(runtime)
        if token:
            break

        retry_count += 1
        runtime.logger.error("FATAL: Bot token not found or could not be decrypted.")
        runtime.logger.error(
            "Please configure the bot token in the Web UI or check the configuration files."
        )

        if max_retries > 0 and retry_count >= max_retries:
            runtime.logger.error(f"Maximum retries ({max_retries}) reached. Exiting.")
            sys.exit(1)

        runtime.logger.warning(f"Retry {retry_count}: Waiting {retry_interval} seconds before next attempt...")

        # Countdown timer
        for remaining in range(retry_interval, 0, -1):
            if remaining % 10 == 0 or remaining <= 5:
                runtime.logger.info(f"⏳ Retrying in {remaining} seconds...")
            time.sleep(1)

        runtime.logger.info("Attempting to reload configuration and retry...")
        # Reload config in case it was updated
        config = load_main_configuration()
        runtime = build_runtime(config)

    runtime.logger.info("Starting bot with token ending in: ...%s", token[-4:])
    bot.run(token)
    runtime.logger.info("Bot has stopped gracefully.")
```

### 2. Create scripts/start_webui.sh

**Create new file:** `scripts/start_webui.sh`

```bash
#!/bin/sh
# Smart startup script for Web UI - synchronized with Bot retry logic

RETRY_INTERVAL=${DDC_TOKEN_RETRY_INTERVAL:-60}
RETRY_COUNT=0

echo "[WebUI] Checking if configuration is ready..."

while true; do
    # Check if Discord token is configured (environment variable or config file)
    if [ -n "$DISCORD_BOT_TOKEN" ]; then
        echo "[WebUI] Discord token found in environment - starting Web UI..."
        break
    fi

    # Check if credentials.yaml exists and is not empty (contains token)
    if [ -f "/app/config/credentials.yaml" ] && [ -s "/app/config/credentials.yaml" ]; then
        # Check if it actually contains a token (not just empty/template)
        if grep -q "bot_token" "/app/config/credentials.yaml" 2>/dev/null; then
            echo "[WebUI] Bot token found in credentials.yaml - starting Web UI..."
            break
        fi
    fi

    RETRY_COUNT=$((RETRY_COUNT + 1))
    echo "[WebUI] Retry $RETRY_COUNT: Bot token not configured yet, waiting ${RETRY_INTERVAL} seconds before retry..."
    echo "[WebUI] (synchronized with Bot retry timing)"
    sleep "$RETRY_INTERVAL"
done

# Start Gunicorn with the web UI
echo "[WebUI] Starting Gunicorn web server on port ${DDC_WEB_PORT:-9374}..."
exec /usr/bin/python3 -m gunicorn -c gunicorn_config.py app.web_ui:app
```

### 3. Update supervisord.conf

**Modify the `[program:web-ui]` section:**

**Before:**
```ini
[program:web-ui]
command=/usr/bin/python3 -m gunicorn -c gunicorn_config.py app.web_ui:app
directory=/app
autostart=true
autorestart=true
stdout_logfile=/app/logs/webui.log
stderr_logfile=/app/logs/webui.log
stdout_logfile_maxbytes=10MB
stderr_logfile_maxbytes=10MB
stdout_logfile_backups=3
stderr_logfile_backups=3
environment=DDC_WEB_PORT="9374"
user=ddc
```

**After:**
```ini
[program:web-ui]
command=/app/scripts/start_webui.sh
directory=/app
autostart=true
autorestart=true
stdout_logfile=/app/logs/webui.log
stderr_logfile=/app/logs/webui.log
stdout_logfile_maxbytes=10MB
stderr_logfile_maxbytes=10MB
stdout_logfile_backups=3
stderr_logfile_backups=3
environment=DDC_WEB_PORT="9374"
user=ddc
```

### 4. Update Dockerfile

**Find the section that copies scripts (around line 156-161):**

**Before:**
```dockerfile
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY --chown=ddc:ddc scripts/entrypoint.sh /app/entrypoint.sh

# Setup permissions
RUN chmod +x /app/entrypoint.sh && \
    mkdir -p /app/config /app/logs /app/scripts && \
```

**After:**
```dockerfile
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY --chown=ddc:ddc scripts/entrypoint.sh /app/entrypoint.sh
COPY --chown=ddc:ddc scripts/start_webui.sh /app/scripts/start_webui.sh

# Setup permissions
RUN chmod +x /app/entrypoint.sh /app/scripts/start_webui.sh && \
    mkdir -p /app/config /app/logs /app/scripts && \
```

## New Environment Variables

Add these to your documentation:

```bash
# Bot Token Retry Configuration (New in v2.0)
DDC_TOKEN_RETRY_INTERVAL=60    # Seconds between retry attempts (default: 60)
DDC_TOKEN_MAX_RETRIES=0        # Maximum retry attempts, 0 = infinite (default: 0)
```

## Benefits

1. **No Crash Loops:** Container runs stably even without token configured
2. **Reduced Resource Usage:** No aggressive restart cycles
3. **Better User Experience:** Clear countdown messages inform users what's happening
4. **Synchronized Timing:** Both Bot and Web-UI retry at the same interval
5. **Configurable:** Users can adjust retry timing via environment variables
6. **Production Ready:** Handles edge cases like token being added while running

## Testing

Test with these scenarios:

```bash
# Test 1: No token configured (should retry every 60s)
docker run --rm -e FLASK_SECRET_KEY="test" yourimage:latest

# Test 2: Custom retry interval (should retry every 20s)
docker run --rm -e DDC_TOKEN_RETRY_INTERVAL=20 -e FLASK_SECRET_KEY="test" yourimage:latest

# Test 3: Max retries limit (should exit after 3 attempts)
docker run --rm -e DDC_TOKEN_RETRY_INTERVAL=10 -e DDC_TOKEN_MAX_RETRIES=3 -e FLASK_SECRET_KEY="test" yourimage:latest
```

## Expected Log Output

```
Starting DockerDiscordControl as user: ddc (UID: 1000, GID: 1000)
...
2025-11-19 19:31:50,689 INFO success: discord-bot entered RUNNING state
2025-11-19 19:31:50,689 INFO success: web-ui entered RUNNING state
...
2025-11-19 19:31:51 CET - ddc.bot - ERROR - FATAL: Bot token not found or could not be decrypted.
2025-11-19 19:31:51 CET - ddc.bot - ERROR - Please configure the bot token in the Web UI or check the configuration files.
2025-11-19 19:31:51 CET - ddc.bot - WARNING - Retry 1: Waiting 60 seconds before next attempt...
2025-11-19 19:31:51 CET - ddc.bot - INFO - ⏳ Retrying in 60 seconds...
2025-11-19 19:32:01 CET - ddc.bot - INFO - ⏳ Retrying in 50 seconds...
...
```

Note: Web-UI should have NO crash/restart messages after initial startup.

## Rollback Instructions

If these changes cause issues, rollback by:

1. Revert `bot.py` changes (remove retry loop, restore original token check)
2. Delete `scripts/start_webui.sh`
3. Restore original `supervisord.conf` (direct gunicorn command)
4. Restore original Dockerfile (remove start_webui.sh references)

## Author

These changes were developed for the DockerDiscordControl Mac repository and tested thoroughly with:
- Alpine Linux 3.22.2
- Python 3.12.12
- Supervisord 4.2.5
- Gunicorn 23.0.0

## License

MIT License - Same as main DockerDiscordControl project
