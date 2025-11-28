# Troubleshooting Guide

Common issues and solutions for DockerDiscordControl v2.0.

## Quick Diagnostics

### Check Container Status

```bash
# Check if container is running
docker ps | grep ddc

# View logs
docker logs ddc

# View real-time logs
docker logs ddc -f

# Check last 50 lines
docker logs ddc --tail 50
```

### Check Configuration

```bash
# List config files
ls -la /path/to/config/

# Check file permissions
docker exec ddc ls -la /app/config/
```

## Common Issues

### 1. Bot Won't Start

**Symptom:** Container starts but bot doesn't connect to Discord

**Solutions:**

1. **Check bot token:**
   ```bash
   # View logs for token errors
   docker logs ddc | grep -i "token\|fatal"
   ```
   - Verify token in Web UI (http://your-server:9374)
   - Or check `DISCORD_BOT_TOKEN` environment variable
   - Token format: `MTIzNDU2Nzg5MDEyMzQ1Njc4OTA.ABC123.xyz789`

2. **Check bot permissions:**
   - Verify bot has proper Discord server permissions
   - Required: Send Messages, Embed Links, Use Application Commands
   - Verify bot is invited to server with correct scopes

### 2. Web UI Login Failed

**Symptom:** Cannot access Web UI at http://your-server:9374

**Default Credentials:**
- Username: `admin`
- Password: `setup`

**Solutions:**

1. **Change password immediately after first login**
   - Web UI → Settings → Change Password

2. **Reset password via environment variable:**
   ```yaml
   # In docker-compose.yml
   environment:
     DDC_ADMIN_PASSWORD: "your-new-password"
   ```
   Then restart: `docker-compose restart`

3. **Check Web UI is accessible:**
   ```bash
   # Test from host
   curl http://localhost:9374

   # Should return HTTP 200 or redirect
   ```

### 3. Configuration Changes Not Saving

**Symptom:** Changes in Web UI don't persist after restart

**Causes:**
- File permission issues
- Missing volume mount
- Incorrect user permissions

**Solutions:**

1. **Verify volume mount:**
   ```yaml
   # In docker-compose.yml
   volumes:
     - ./config:/app/config
   ```

2. **Check file permissions:**
   ```bash
   # On Unraid
   chown -R nobody:users /mnt/user/appdata/dockerdiscordcontrol/config
   chmod -R 755 /mnt/user/appdata/dockerdiscordcontrol/config

   # On standard Linux
   chown -R 1000:1000 /path/to/config
   chmod -R 755 /path/to/config
   ```

3. **Fix from within container:**
   ```bash
   docker exec -u root ddc chown -R ddc:ddc /app/config
   docker exec ddc chmod -R 755 /app/config
   docker restart ddc
   ```

### 4. Containers Not Showing in Discord

**Symptom:** Configured containers don't appear in Discord commands

**Solutions:**

1. **Check container is marked Active:**
   - Web UI → Container Management
   - Verify "Active" checkbox is enabled

2. **Verify Docker container name matches exactly:**
   ```bash
   # List running containers
   docker ps --format "table {{.Names}}\t{{.Status}}"

   # Container name in DDC must match exactly
   ```

3. **Check Discord channel permissions:**
   - Web UI → Channel Configuration
   - Verify commands are enabled for the channel
   - Required: `serverstatus` or `control` enabled

4. **Reload bot:**
   ```bash
   docker restart ddc
   ```

### 5. Container Actions (Start/Stop/Restart) Not Working

**Symptom:** Buttons in Discord don't work or return errors

**Solutions:**

1. **Verify Docker socket is mounted:**
   ```yaml
   # In docker-compose.yml
   volumes:
     - /var/run/docker.sock:/var/run/docker.sock:ro
   ```

2. **Check socket permissions:**
   ```bash
   # View socket permissions
   ls -la /var/run/docker.sock

   # Should be accessible by docker group (GID 281 or similar)
   ```

3. **Verify allowed actions are configured:**
   - Web UI → Container Management → Edit Container
   - Check "Allowed Actions" includes: start, stop, restart

4. **Check Docker socket accessibility:**
   ```bash
   docker exec ddc docker ps
   # Should list containers - if error, socket not accessible
   ```

### 6. Permission Errors on Different Systems

**Recommended Solution (v2.1.2+):** Use PUID/PGID environment variables:

| System | PUID | PGID |
|--------|------|------|
| Unraid | 99 | 100 |
| Synology | 1026 | 100 |
| TrueNAS | 568 | 568 |
| Standard Linux | 1000 | 1000 |

```yaml
environment:
  - PUID=99    # Change to match your system
  - PGID=100
```

The container automatically fixes volume permissions on startup.

**Manual Fix (older versions):**

**Unraid:**
```bash
chown -R 1000:1000 /mnt/user/appdata/dockerdiscordcontrol
```

**Synology:**
```bash
chown -R 1000:1000 /volume1/docker/ddc/config/
```

**Standard Linux:**
```bash
chown -R 1000:1000 /path/to/config
```

### 7. Scheduled Tasks Not Running

**Symptom:** Tasks configured but don't execute

**Solutions:**

1. **Verify task is active:**
   - Web UI → Task Management
   - Check task has "Active" status

2. **Check task schedule:**
   - Verify cron expression is valid
   - Test at CronTab.guru

3. **Check scheduler logs:**
   ```bash
   docker logs ddc | grep -i "scheduler\|task"
   ```

### 8. Discord Interaction Timeouts

**Symptom:** "This interaction failed" messages in Discord

**Solutions:**

1. **Check bot response time:**
   ```bash
   # View response time logs
   docker logs ddc | grep -i "timeout\|defer"
   ```

2. **Increase Docker API timeout:**
   - Web UI → Settings → Advanced
   - Increase "Docker API Timeout" from 30 to 60 seconds

3. **Verify Docker daemon is responsive:**
   ```bash
   time docker ps
   # Should complete in < 2 seconds
   ```

## Advanced Troubleshooting

### Enable Debug Logging

1. **Via Web UI:**
   - Settings → Advanced → Enable "Scheduler Debug Mode"
   - Save and restart

2. **Check debug logs:**
   ```bash
   docker logs ddc -f | grep -i "debug\|error"
   ```

### Container Resource Issues

**Check resource usage:**
```bash
docker stats ddc

# Expected:
# CPU: < 10% normally, < 50% during heavy operations
# Memory: < 200MB normally, < 512MB maximum
```

**If container is restarting:**
```bash
# Check restart count
docker ps -a | grep ddc

# View exit code
docker inspect ddc | grep -i "exitcode\|error"
```

### Network Issues

**Verify network connectivity:**
```bash
# Test Discord API from container
docker exec ddc wget -q -O- https://discord.com/api/v10/gateway

# Should return JSON with gateway URL
```

### Clean Reinstall

If all else fails:

```bash
# Backup configuration
tar czf ddc_backup.tar.gz config/

# Stop and remove container
docker-compose down
docker rmi dockerdiscordcontrol/dockerdiscordcontrol:latest

# Remove old data (careful!)
rm -rf config/

# Restore backup
tar xzf ddc_backup.tar.gz

# Fresh installation
docker-compose up -d

# View startup logs
docker logs ddc -f
```

## Getting Help

### Before Asking for Help

Collect this information:

1. **Version:** `docker exec ddc python -c "print('v2.0.0')"`
2. **Logs:** `docker logs ddc --tail 100 > ddc_logs.txt`
3. **Environment:** Unraid / Synology / Linux / etc.
4. **Error messages:** Exact error text from Discord or Web UI

### Support Channels

1. Check documentation:
   - [CONFIGURATION.md](CONFIGURATION.md)
   - [SECURITY.md](SECURITY.md)
   - [README.md](../README.md)

2. GitHub Issues:
   - Search existing issues first
   - Include collected information
   - Redact sensitive data (tokens, passwords)

3. Logs to include:
   ```bash
   # Bot logs
   docker logs ddc --tail 100

   # Web UI logs
   docker logs ddc | grep -i "webui\|flask"

   # Error logs only
   docker logs ddc 2>&1 | grep -i "error\|exception\|failed"
   ```

## Known Limitations

- Docker socket access requires proper host permissions
- Default credentials must be changed for security
- Some operations may time out with slow Docker daemon
- Container names must match exactly (case-sensitive)
