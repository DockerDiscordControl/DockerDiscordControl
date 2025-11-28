# Configuration Guide

DockerDiscordControl v2.0 configuration guide for production deployments.

## Configuration Methods

DDC supports two primary configuration methods:

1. **Web UI** (Recommended) - Configure via http://your-server:9374
2. **Environment Variables** - Set via docker-compose.yml or .env file

## Quick Start

### First-Time Setup

1. **Start the container:**
   ```bash
   docker-compose up -d
   ```

2. **Access Web UI:**
   ```
   http://your-server:9374
   ```

3. **Login:**
   - Username: `admin`
   - Password: Your `DDC_ADMIN_PASSWORD` (or `setup` if not set)

4. **If using default password:** Change immediately (Web UI → Settings)

5. **Configure Discord bot token** (Web UI → Configuration)

6. **Add containers** (Web UI → Container Management)

7. **Save configuration**

## Web UI Configuration

### System Settings

Access: Web UI → Configuration

| Setting | Description | Default |
|---------|-------------|---------|
| Language | Bot language (de, fr, en) | en |
| Timezone | Server timezone | Europe/Berlin |
| Guild ID | Discord server ID | (required) |
| Bot Token | Discord bot token | (required) |

### Container Management

Access: Web UI → Container Management

Add Docker containers to control via Discord:

| Field | Description | Required |
|-------|-------------|----------|
| Container Name | Docker container name | Yes |
| Display Name | Name shown in Discord | Yes |
| Allowed Actions | start, stop, restart, status | Yes |
| Active | Show in Discord | Yes |
| Order | Display order (lower first) | No |

**Container Info Settings:**

| Field | Description | Required |
|-------|-------------|----------|
| Enable Info | Enable /info command | No |
| Show IP | Display IP address | No |
| Custom IP | Override auto-detected IP | No |
| Custom Port | Port to display | No |
| Custom Text | Additional info text | No |

### Channel Permissions

Access: Web UI → Channel Configuration

Configure which commands are available in each Discord channel:

**Available Commands:**
- `serverstatus` / `ss` - Display server status
- `control` - Start/stop/restart containers
- `schedule` - Schedule automated tasks
- `info` - Show container information

**Auto-Refresh Settings:**
- Enable automatic status updates
- Update interval (minutes)
- Recreate on inactivity
- Inactivity timeout (minutes)

### Advanced Settings

Access: Web UI → Settings → Advanced

| Setting | Description | Default |
|---------|-------------|---------|
| Session Timeout | Web UI session timeout (seconds) | 3600 |
| Donation Key | Disable donation system | (optional) |
| Scheduler Debug | Enable debug logging | false |
| Docker Socket | Docker socket path | /var/run/docker.sock |
| Command Cooldown | Cooldown between commands (seconds) | 5 |
| API Timeout | Docker API timeout (seconds) | 30 |
| Max Log Lines | Maximum log lines to fetch | 50 |

## Environment Variables

Configure via docker-compose.yml for enhanced security.

### Recommended Variables

```yaml
environment:
  # Security (Required)
  FLASK_SECRET_KEY: "your-64-character-random-secret-key"

  # Discord (Optional - can also configure via Web UI)
  DISCORD_BOT_TOKEN: "your-discord-token-here"

  # Admin Password (Optional)
  DDC_ADMIN_PASSWORD: "your-secure-admin-password"

  # Timezone (Optional)
  TZ: "Europe/Berlin"
```

### Generate Secure Keys

```bash
# Generate Flask secret key
openssl rand -hex 32

# Use output in docker-compose.yml
```

### Example docker-compose.yml

```yaml
version: '3.8'

services:
  ddc:
    image: dockerdiscordcontrol/dockerdiscordcontrol:latest
    container_name: ddc
    restart: unless-stopped
    ports:
      - "9374:9374"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ./config:/app/config
      - ./logs:/app/logs
    environment:
      FLASK_SECRET_KEY: "${FLASK_SECRET_KEY}"
      DISCORD_BOT_TOKEN: "${DISCORD_BOT_TOKEN}"
      DDC_ADMIN_PASSWORD: "${DDC_ADMIN_PASSWORD}"
      TZ: "Europe/Berlin"
      # For NAS systems (Unraid, Synology, etc.):
      # PUID: 99   # Unraid default
      # PGID: 100  # Unraid default
```

## Configuration Storage

DDC stores configuration in the `/app/config` directory:

```
config/
├── info/           # Container information cache
├── progress/       # Donation/evolution system data
├── tasks/          # Scheduled tasks (empty until tasks created)
└── tasks.json      # Task definitions
```

**Note:** Configuration is managed internally by DDC. Manual editing of config files is not recommended.

## Token Security

### Encryption

Discord bot tokens are encrypted using:
- **Algorithm:** Fernet (AES-128 CBC mode)
- **Key Derivation:** PBKDF2-HMAC-SHA256
- **Iterations:** 260,000
- **Password Hashing:** PBKDF2-SHA256, 600,000 iterations

### Best Practices

1. **Use environment variables** for bot token when possible
2. **Set strong Flask secret key** (64 characters minimum)
3. **Change default admin password** immediately
4. **Rotate tokens** if compromised
5. **Use read-only Docker socket** mounting

## Backup Configuration

### Backup Command

```bash
# Backup entire config directory
tar czf ddc_config_backup_$(date +%Y%m%d).tar.gz config/

# Set secure permissions
chmod 600 ddc_config_backup_*.tar.gz
```

### Restore Configuration

```bash
# Stop container
docker-compose down

# Restore config
tar xzf ddc_config_backup_20251118.tar.gz

# Start container
docker-compose up -d
```

## Troubleshooting

### Bot Won't Start

**Problem:** Bot token not found or invalid

**Solution:**
1. Check Web UI → Configuration → Bot Token is set
2. Or verify `DISCORD_BOT_TOKEN` environment variable
3. Check logs: `docker logs ddc`

### Web UI Login Failed

**Problem:** Password incorrect

**Solution:**
1. Check if custom password was set via `DDC_ADMIN_PASSWORD`
2. Default password is `setup` (change immediately)
3. Clear browser cache
4. Restart container: `docker-compose restart`

### Containers Not Showing in Discord

**Problem:** Configured containers don't appear

**Solution:**
1. Verify containers are marked as "Active" in Web UI
2. Check Docker container names match exactly
3. Reload bot: restart DDC container
4. Check bot has proper Discord permissions

### Configuration Not Persisting

**Problem:** Settings reset after restart

**Solution:**
1. Verify config volume is mounted: `/app/config`
2. Check file permissions: `ls -la config/`
3. Ensure container runs as correct user (1000:1000)
4. Check Docker logs for save errors

## Production Checklist

Before going live, verify:

- [ ] Changed default admin password from `setup`
- [ ] Set strong `FLASK_SECRET_KEY` (64+ characters)
- [ ] Discord bot token configured (Web UI or environment)
- [ ] All desired containers added and set to Active
- [ ] Channel permissions configured correctly
- [ ] Docker socket mounted read-only (`:ro`)
- [ ] Config directory persisted with volume mount
- [ ] Container runs as non-root user (1000:1000)
- [ ] Web UI accessible only from trusted network
- [ ] Backups configured for config directory

## See Also

- [SECURITY.md](SECURITY.md) - Security best practices and incident response
- [README.md](../README.md) - Installation and quick start guide
- [CHANGELOG.md](CHANGELOG.md) - Version history and updates
