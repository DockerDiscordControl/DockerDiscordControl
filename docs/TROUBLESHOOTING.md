# DDC Troubleshooting Guide

## Common Issues and Solutions

### 1. Configuration Changes Not Saving

**Symptom:** 
- Changes made in the Web UI are not saved
- Container permissions always show as empty `[]`
- No error messages in the Web UI

**Cause:** 
File permission issues preventing the application from writing to configuration files.

**Solution:**

1. Check the Docker logs for permission errors:
   ```bash
   docker logs ddc | grep -i "permission"
   ```

2. Fix file permissions on the host:
   ```bash
   # Navigate to your DDC directory
   cd /mnt/user/appdata/dockerdiscordcontrol/config
   
   # Make files readable and writable
   chmod 644 *.json
   
   # Set proper ownership (adjust for your system)
   chown nobody:users *.json
   ```

3. Alternative: Fix from within the container:
   ```bash
   docker exec ddc chmod 644 /app/config/*.json
   ```

4. Restart the container:
   ```bash
   docker restart ddc
   ```

### 2. Permission Errors on Different Systems

**Unraid Users:**
- Default user is typically `nobody:users`
- Use: `chown nobody:users /mnt/user/appdata/dockerdiscordcontrol/config/*.json`

**Synology Users:**
- May need to use different user/group
- Check with: `ls -la /volume1/docker/dockerdiscordcontrol/config/`
- Adjust ownership accordingly

**Standard Linux:**
- Docker containers often run as `1000:1000` or `root`
- Use: `chown 1000:1000 /path/to/dockerdiscordcontrol/config/*.json`

### 3. Web UI Authentication Issues

**Symptom:** Cannot log into Web UI

**Solution:**
1. Default credentials: `admin` / `admin`
2. Reset password by editing `config/web_config.json`
3. Set a new password hash or restore defaults

### 4. Bot Not Responding to Commands

**Symptom:** Bot is online but doesn't respond

**Check:**
1. Bot permissions in Discord server
2. Container permissions in `docker_config.json`
3. Channel permissions in `channels_config.json`

### 5. Container Actions Not Working

**Symptom:** Start/Stop/Restart buttons don't work

**Solution:**
1. Ensure Docker socket is mounted correctly:
   ```yaml
   volumes:
     - /var/run/docker.sock:/var/run/docker.sock
   ```

2. Check container has `allowed_actions` set:
   ```json
   {
     "name": "MyContainer",
     "docker_name": "actual-container-name",
     "allowed_actions": ["status", "start", "stop", "restart"]
   }
   ```

## Debug Mode

Enable debug logging to see more details:

1. In Web UI: Settings → Enable Debug Mode
2. Or edit `config/web_config.json`:
   ```json
   {
     "scheduler_debug_mode": true
   }
   ```

## Getting Help

1. Check logs: `docker logs ddc -f`
2. Look for ERROR or WARNING messages
3. Join our Discord support server
4. Create an issue on GitHub with:
   - Docker logs
   - Your configuration (without tokens!)
   - Steps to reproduce the problem 