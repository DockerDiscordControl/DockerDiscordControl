# Configuration Guide

This guide covers configuring DockerDiscordControl through the web interface and advanced settings.

## Accessing the Web UI

1. **Open Browser**: Navigate to `http://your-server-ip:8374`
2. **Login**: Use username `admin` and your configured password
3. **Security**: **Immediately change the default password** if using defaults

## Initial Configuration

### 1. Discord Bot Settings

**Bot Token**
- Paste your Discord bot token from the [Discord Developer Portal](https://discord.com/developers/applications)
- **Security**: Never share this token publicly
- Required for bot functionality

**Guild ID (Server ID)**
- Your Discord server's unique identifier  
- Get this by right-clicking your server name in Discord (Developer Mode required)
- Bot will only operate in this specific server

**Language Settings**
- **Bot Language**: Choose language for Discord bot responses (English, German, French)
- **Timezone**: Set timezone for timestamps in logs and web UI
- Changes take effect immediately without restart

### 2. Container Selection & Bot Permissions

This is the core configuration where you:
- Select which Docker containers DDC can manage
- Set permissions for each container (Status, Start, Stop, Restart)
- Configure display names for the Discord bot

**Container Table Columns:**

| Column | Description |
|--------|-------------|
| **Order** | Display order in Discord (use +/- buttons to reorder) |
| **Active** | Enable/disable bot management for this container |
| **Container Name** | Docker container name (read-only) |
| **Display Name** | Custom name shown in Discord bot |
| **Status** | Allow bot to fetch CPU/RAM/Uptime information |
| **Start** | Allow bot to start stopped containers |
| **Stop** | Allow bot to stop running containers  
| **Restart** | Allow bot to restart containers |

**Best Practices:**
- Only enable permissions you actually need
- Use descriptive display names (e.g., "Game Server" instead of "minecraft_1")
- Keep sensitive containers (databases, etc.) with minimal permissions

### 3. Channel Permissions

Configure which Discord channels can use which bot commands:

**Command Types:**
- **`/serverstatus`** (or `/ss`): Display container status messages
- **`/command`**: Execute container control actions  
- **`/control`**: Alternative control command
- **`/task`**: Create and manage scheduled tasks

**Channel Settings:**
- **Channel Name**: Descriptive name for your reference
- **Channel ID**: Discord channel ID (right-click channel → Copy ID)
- **Initial**: Post status messages when bot starts
- **Refresh**: Enable automatic status updates
- **Minutes**: Update interval (if refresh enabled)
- **Recreate**: Regenerate messages after inactivity
- **Minutes**: Inactivity timeout (if recreate enabled)

**Permission Strategies:**

**Read-Only Status Channel:**
```
✅ /serverstatus  ❌ /command  ❌ /control  ❌ /task
Use case: Public server status monitoring
```

**Admin Control Channel:**
```
✅ /serverstatus  ✅ /command  ✅ /control  ✅ /task  
Use case: Full administrative control
```

**Limited Control Channel:**
```
✅ /serverstatus  ✅ /command  ❌ /control  ❌ /task
Use case: Basic start/stop without advanced features
```

## Advanced Configuration

### Performance Settings

DDC includes optimized performance settings:

**Cache Settings:**
- **Docker Cache Duration**: How long to cache container info (default: 75s)
- **Toggle Cache Duration**: Extended cache for toggle operations (default: 150s)
- **Background Refresh**: Automatic cache refresh interval (default: 30s)

**Batch Processing:**
- **Batch Size**: Number of operations processed together (default: 3)
- **Message Update Batching**: Efficient Discord message updates

### Environment Variables

Advanced users can configure via environment variables:

```bash
# Performance Tuning
DDC_DOCKER_CACHE_DURATION=75
DDC_BACKGROUND_REFRESH_INTERVAL=30  
DDC_TOGGLE_CACHE_DURATION=150
DDC_BATCH_SIZE=3

# Security
FLASK_SECRET_KEY=your_32_byte_hex_key
DDC_ADMIN_PASSWORD=your_secure_password

# Docker Connection
DOCKER_HOST=unix:///var/run/docker.sock
```

### Task Scheduler Configuration

**Scheduler Debug Mode:**
- Enable detailed logging for scheduled tasks
- Useful for troubleshooting automation issues
- Can be toggled on/off without restart

**Temporary Debug Mode:**
- Enable debug logging for a specified duration
- Automatically disables after timeout
- Perfect for troubleshooting specific issues

## Web UI Authentication

### Changing Password

1. Navigate to "Web UI Authentication" section
2. Enter current password
3. Enter new password twice
4. Click "Save Configuration"
5. Password changes immediately

### Security Best Practices

1. **Strong Passwords**: Use complex, unique passwords
2. **Regular Updates**: Change passwords periodically  
3. **Access Control**: Limit who has web UI access
4. **HTTPS**: Consider reverse proxy with SSL/TLS
5. **Network Security**: Restrict access to trusted networks

## Configuration Files

DDC uses split configuration files for better organization:

| File | Purpose |
|------|---------|
| `bot_config.json` | Discord bot settings (token, guild ID, language) |
| `docker_config.json` | Container selection and permissions |
| `channels_config.json` | Channel permissions and settings |
| `web_config.json` | Web UI authentication and settings |

**File Locations:**
- Docker: `/app/config/` (inside container)
- Host: Your mounted config directory

## Troubleshooting Configuration

### Configuration Not Saving

**Symptoms:**
- Changes revert after refresh
- "Save Configuration" shows errors
- Container permissions show empty arrays

**Solutions:**
1. **Check File Permissions:**
   ```bash
   docker exec ddc /app/scripts/fix_permissions.sh
   ```

2. **Manual Permission Fix:**
   ```bash
   chmod 644 /path/to/config/*.json
   chown nobody:users /path/to/config/*.json  # Unraid
   ```

3. **Check Logs:**
   ```bash
   docker logs ddc | grep -i "permission\|error"
   ```

### Bot Not Responding

**Check Configuration:**
1. **Bot Token**: Verify token is correct and not regenerated
2. **Guild ID**: Ensure server ID matches your Discord server
3. **Permissions**: Bot needs appropriate Discord permissions
4. **Channel Setup**: Configure channel permissions in web UI

### Performance Issues

**Optimization Steps:**
1. **Adjust Cache Duration**: Increase for better performance
2. **Reduce Update Frequency**: Lower refresh rates for large setups
3. **Monitor Resources**: Check CPU/memory usage in logs
4. **Enable Performance Logging**: Use debug mode for insights

## Configuration Examples

### Small Home Setup
- 3-5 containers
- Single control channel
- 5-minute status updates
- Basic permissions only

### Medium Server Environment  
- 10-20 containers
- Separate status and control channels
- 2-minute status updates
- Role-based permission strategy

### Large Enterprise Setup
- 50+ containers
- Multiple specialized channels
- 1-minute status updates
- Granular permission matrix
- Performance monitoring enabled

## Next Steps

- [📅 Task System](Task-System) - Set up automated scheduling
- [Performance](Performance-and-Architecture) - Optimize for your environment
- [Troubleshooting](Troubleshooting) - Solve common issues 