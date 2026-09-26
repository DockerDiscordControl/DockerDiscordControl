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

### Container Groups (v3.0+)

Access: Web UI → Container Groups (under Container Management)

A group is a name you choose and the containers that belong to it. It is yours, not Docker's -
containers created without `docker-compose` have no stack, which on Unraid is usually all of
them.

| Field | Description | Required |
|-------|-------------|----------|
| Group name | Free text, up to 80 characters, unique | Yes |
| Containers | Any number of your configured containers | No (a group may start empty) |

A group can be used wherever a single container can:

- **Scheduled tasks** — pick the group in the task form's container list, under "Container
  groups". The members are acted on one after another. If the group is gone, empty, or has lost a
  member, the task is reported as FAILED rather than as a success over the rest.
- **Auto-actions** — tick the group in the rule editor. It counts twice over: as the containers
  the rule watches, and as the containers it acts on. A rule whose group was deleted watches
  **nothing** (it does not fall back to "every container").
- **Discord** — the Admin Overview's group button offers your groups and any Compose stacks DDC
  finds. It only appears when there is at least one of them.

A container that is renamed or removed stays in the group until you edit it; every place that
uses the group says so rather than quietly acting on fewer containers.

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
| Command Cooldown | Cooldown between commands (seconds) | 5 |
| API Timeout | Docker API timeout (seconds) | 30 |
| Max Log Lines | Maximum log lines to fetch | 50 |

Since v3.0 there is no "Docker socket path" setting any more: every Docker client
follows `DOCKER_HOST`, which the image points at DDC's allowlist proxy. A value
left over in the configuration is ignored and reported once in the log.

### Container Watchdog (v3.0+)

Access: Web UI -> Auto-Actions -> new rule -> trigger type **Container state**

A rule can react when a container

- **stops** on its own (a stop DDC itself carried out is not an alarm),
- turns **unhealthy** (its health check fails),
- **restarts** several times within a few minutes (threshold and window are yours),
- stays above a **CPU or memory threshold** for a number of minutes, or
- has a **newer image** in the registry (checked every six hours; this one can only
  notify, because DDC cannot pull).

The action is notify, or start/stop/restart the container the event is about.
Notices go to the control channel unless the rule names another one. The memory
threshold is a percentage of the container's memory limit - a container started
without `--memory` has none, so that is the host's whole RAM.

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

### Tuning Variables (v2.2.2+)

All optional — sensible defaults are applied when unset.

```yaml
environment:
  # Web session idle timeout (seconds, floor 60). Default 1800 (30 min).
  DDC_SESSION_IDLE_TIMEOUT: "1800"

  # Waitress thread pool size (range 2..16). Default: max(4, min(8, cpu_count)).
  DDC_WAITRESS_THREADS: "8"

  # Web UI port inside the container. Default 9374. Only needed with host networking
  # when 9374 is already in use (bridge: change the host port mapping instead).
  # DDC_WEB_PORT: "9374"

  # Animation disk cache cap (MB). Default 200. Set to 0 to disable LRU eviction.
  DDC_ANIM_DISK_LIMIT_MB: "200"

  # v3.0: the address or range of your reverse proxy. Without it DDC ignores
  # X-Forwarded-* from everybody, so the action log shows the proxy's address.
  # DDC_TRUSTED_PROXIES: "172.18.0.0/16"

  # v3.0: off (default), proxy (TLS ends at your reverse proxy - needs
  # DDC_TRUSTED_PROXIES, or DDC refuses to start), or self-signed (DDC serves
  # HTTPS with a certificate it creates in config/tls/ and renews itself).
  # DDC_TLS_MODE: "off"

  # Extra names/IPs for the self-signed certificate, comma-separated.
  # DDC_TLS_HOSTNAMES: "ddc.lan,192.168.1.50"

  # Override config/data directories (rarely needed; for custom layouts and tests).
  # DDC_CONFIG_DIR: "/app/config"
  # DDC_PROGRESS_DATA_DIR: "/app/config/progress"
  # DDC_METRICS_DIR: "/app/data/metrics"

  # Re-enable gevent monkey-patching (only needed for legacy gunicorn dev workers;
  # the standard waitress runtime works without it). Default: off.
  # DDC_ENABLE_GEVENT: "1"

  # Emergency: run container as root, bypassing privilege drop. Use only when
  # NAS/permission issues prevent first-time chown. Remove after one boot.
  # DDC_FORCE_ROOT: "true"
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
├── tasks.json      # Task definitions
└── groups.json     # Container groups (v3.0+, empty until you make one)
```

**Note:** Configuration is managed internally by DDC. Manual editing of config files is not recommended.

## Token Security

### Encryption

Discord bot tokens are encrypted using:
- **Algorithm:** Fernet (AES-128 CBC mode)
- **Key Derivation:** PBKDF2-HMAC-SHA256
- **Iterations:** 600,000
- **Password Hashing:** PBKDF2-SHA256, 600,000 iterations

### Best Practices

1. **Use environment variables** for bot token when possible
2. **Set strong Flask secret key** (64 characters minimum)
3. **Change default admin password** immediately
4. **Rotate tokens** if compromised
5. **Start the container without `--user`** (use `PUID`/`PGID`): only then does the
   Docker allowlist proxy run. A `:ro` socket mount protects the socket file, not
   the API behind it - it is not a security control

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
- [ ] Container started without `--user` (the Docker allowlist proxy runs; see `/health`)
- [ ] Config directory persisted with volume mount
- [ ] Container runs as non-root user (1000:1000)
- [ ] Web UI accessible only from trusted network
- [ ] Backups configured for config directory

## See Also

- [SECURITY.md](SECURITY.md) - Security best practices and incident response
- [README.md](../README.md) - Installation and quick start guide
- [CHANGELOG.md](CHANGELOG.md) - Version history and updates
