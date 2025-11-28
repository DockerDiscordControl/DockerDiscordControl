# Configuration Guide

DDC uses a hierarchical configuration system: **Config Files > Environment Variables > Defaults**.
This means values in `config/*.json` files take precedence, followed by Environment Variables, and finally hardcoded defaults.

## Environment Variables

### Permission Settings (NAS/Unraid)
Settings for file permission handling on NAS systems.

| Variable | Default | Description |
| :--- | :--- | :--- |
| `PUID` | `1000` | User ID for file permissions. Unraid: `99`, Synology: `1026`. |
| `PGID` | `1000` | Group ID for file permissions. Unraid: `100`, Synology: `100`. |
| `DDC_ADMIN_PASSWORD` | - | **Required.** Password for web UI admin user. |

### Application Settings (DDC)
Advanced settings for tuning application behavior.

| Variable | Default | Description |
| :--- | :--- | :--- |
| `DDC_WEB_PORT` | `9374` | Port for the Web Dashboard. |
| `DDC_DOCKER_CACHE_DURATION` | `30` | Seconds to cache Docker container lists. |
| `DDC_DOCKER_QUERY_COOLDOWN` | `2` | Minimum seconds between Docker API calls. |
| `DDC_ENABLE_BACKGROUND_REFRESH` | `true` | Enable background polling of container status. |
| `DDC_BACKGROUND_REFRESH_INTERVAL` | `30` | Seconds between background refreshes. |
| `DDC_MAX_CONTAINERS_DISPLAY` | `100` | Maximum number of containers to show in the UI. |
| `DDC_LIVE_LOGS_ENABLED` | `true` | Enable the live log streaming feature. |
| `DDC_LIVE_LOGS_TAIL_LINES` | `50` | Number of initial lines to fetch for live logs. |

## Configuration Files

Configuration is persisted in JSON files located in the `/app/config` directory (mapped to a volume in Docker).

### `bot_config.json`
Core Discord bot settings.
*   **bot_token**: Your Discord Bot Token.
*   **guild_id**: The ID of your Discord Server (Guild).
*   **language**: Bot language (`en`, `de`, etc.).
*   **timezone**: Timezone for logs and scheduling (e.g., `Europe/Berlin`).

### `channels_config.json`
Manages channel mappings and spam protection.
*   **channels**: Maps internal channel types to Discord Channel IDs.
*   **spam_protection**: Stores cooldowns and rate limits (see [Web UI Settings](WebUI_Settings.md)).

### `docker_config.json`
Docker connection settings.
*   **docker_socket_path**: Path to the socket (default: `/var/run/docker.sock`).
*   **docker_api_timeout**: Timeout for Docker API calls (default: 30s).

### `web_config.json`
Web Dashboard settings.
*   **web_ui_user**: Admin username (default: `admin`).
*   **web_ui_password_hash**: Hashed password for the dashboard.
*   **admin_enabled**: Enable/Disable the web interface.
