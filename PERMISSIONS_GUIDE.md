# DockerDiscordControl - Permissions Guide

## Problem
File permission errors when Docker containers try to write to mounted volumes, especially on Unraid and other NAS systems.

## Root Cause
Docker containers run with specific user IDs that may not match the host system's file ownership.

## Solutions

### 1. Automatic Permission Fixing (Recommended)
The container now automatically fixes permissions on startup using a built-in script.

**What it does:**
- Runs as root during startup
- Creates necessary directories (`/app/config/info`, `/app/config/tasks`)
- Sets correct ownership and permissions
- Ensures all config files are writable

### 2. PUID/PGID Environment Variables
Set the user and group IDs to match your system:

```yaml
# In docker-compose.yml or .env file
PUID=99    # Unraid default: nobody
PGID=100   # Unraid default: users
```

**Common PUID/PGID values:**
- **Unraid**: `PUID=99`, `PGID=100` (nobody:users)
- **Synology**: `PUID=1024`, `PGID=100` (or check with `id your_username`)
- **Standard Linux**: `PUID=1000`, `PGID=1000`

### 3. Manual Permission Fix
If automatic fixing doesn't work, run manually:

```bash
# On the host system
sudo chown -R 99:100 /mnt/user/appdata/dockerdiscordcontrol/config
sudo chmod -R 755 /mnt/user/appdata/dockerdiscordcontrol/config
```

### 4. Docker Compose User Override
The docker-compose.yml now includes:

```yaml
user: "${PUID:-99}:${PGID:-100}"
```

This ensures the container runs with the correct user ID.

## Verification

After applying the fixes:

1. **Check container logs:**
   ```bash
   docker logs ddc
   ```
   Look for: "✅ Permission fixing completed"

2. **Test file creation:**
   - Try saving container info in Web UI
   - Create a task via Web UI
   - Check if files appear in `config/info/` and `config/tasks/`

3. **Check file ownership:**
   ```bash
   ls -la /mnt/user/appdata/dockerdiscordcontrol/config/
   ```

## Troubleshooting

### Still getting permission errors?

1. **Check mount points:**
   ```bash
   docker exec ddc ls -la /app/config
   ```

2. **Verify PUID/PGID:**
   ```bash
   docker exec ddc id
   ```

3. **Check SELinux/AppArmor:**
   ```bash
   # Disable SELinux temporarily (if applicable)
   sudo setenforce 0
   ```

4. **Manual container restart:**
   ```bash
   docker restart ddc
   ```

### For Unraid Users

1. **Set in Docker template:**
   - PUID: `99`
   - PGID: `100`

2. **Check Unraid file permissions:**
   ```bash
   ls -la /mnt/user/appdata/dockerdiscordcontrol/
   ```

3. **Fix via Unraid terminal:**
   ```bash
   chown -R nobody:users /mnt/user/appdata/dockerdiscordcontrol/config
   ```

## Files That Need Write Access

- `/app/config/bot_config.json`
- `/app/config/docker_config.json`
- `/app/config/channels_config.json`
- `/app/config/web_config.json`
- `/app/config/server_order.json`
- `/app/config/info/*.json` (container info files)
- `/app/config/tasks/*.json` (task files)
- `/app/logs/` (log directory)

## Prevention

The new system prevents most permission issues by:

1. **Automatic permission fixing on startup**
2. **Flexible PUID/PGID support**
3. **Proper directory creation**
4. **Graceful error handling**

These changes make the system much more robust across different deployment scenarios. 