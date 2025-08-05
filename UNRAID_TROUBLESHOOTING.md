# Unraid Troubleshooting Guide

## Web UI Connection Issues

### Problem: Cannot access Web UI via http://IP:8374

**Symptoms:**
- Browser shows "Unable to connect" 
- `curl -I http://localhost:8374` returns "Connection reset by peer"
- Container appears to be running but Web UI is inaccessible

### Root Cause
The container runs the Web UI on **port 9374** internally, but Unraid Community Apps may map it to port 8374 externally.

### Solutions

#### Solution 1: Check Unraid Port Mapping
1. Go to Unraid Web UI → Docker tab
2. Click on your DDC container
3. Check the port mapping - it should show: `8374:9374`
4. If incorrect, edit the container and fix the port mapping

#### Solution 2: Update Unraid Template
If using Community Apps:
1. Remove the existing DDC container
2. Re-install from Community Apps
3. During setup, ensure port mapping is: `Host Port: 8374` → `Container Port: 9374`

#### Solution 3: Manual Docker Run (Alternative)
```bash
docker run -d \
  --name dockerdiscordcontrol \
  -p 8374:9374 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /mnt/user/appdata/dockerdiscordcontrol/config:/app/config \
  -v /mnt/user/appdata/dockerdiscordcontrol/logs:/app/logs \
  --restart unless-stopped \
  dockerdiscordcontrol/dockerdiscordcontrol:latest
```

#### Solution 4: Check if Web UI Service is Running
```bash
# Check container logs
docker logs dockerdiscordcontrol

# Check if gunicorn is running
docker exec dockerdiscordcontrol ps aux | grep gunicorn

# Check if port 9374 is open inside container
docker exec dockerdiscordcontrol netstat -tlnp | grep 9374
```

### Expected Logs
When working correctly, you should see:
```
INFO spawned: 'webui' with pid X
INFO spawned: 'discordbot' with pid Y
INFO success: webui entered RUNNING state
INFO success: discordbot entered RUNNING state
```

### Common Issues

#### Issue: "spawnerr: can't find command '/venv/bin/gunicorn'"
**Fix:** Container build failed. Rebuild with: `./scripts/rebuild.sh`

#### Issue: Web UI starts but crashes immediately
**Fix:** Check permissions:
```bash
docker exec dockerdiscordcontrol chown -R ddcuser:ddcuser /app/config /app/logs
```

#### Issue: Port already in use
**Fix:** Change host port in Unraid:
```
Host Port: 8375 (or any free port)
Container Port: 9374 (keep this!)
```

### Testing Connection

After fixing, test with:
```bash
# From Unraid console
curl -I http://localhost:8374

# Should return:
HTTP/1.1 401 Unauthorized
WWW-Authenticate: Basic realm="Authentication Required"
Server: gunicorn
```

### Automatic Port Diagnostics

DDC v1.1.3c+ includes automatic port diagnostics that run at startup and provide detailed troubleshooting information:

#### In Container Logs
Look for the **Port Diagnostics** section in your container logs:
```bash
docker logs dockerdiscordcontrol | grep -A 20 "=== DDC Port Diagnostics ==="
```

#### Via Web UI (if accessible)
If you can access the Web UI, visit: `http://[IP]:8374/port_diagnostics`

### Manual Troubleshooting

If automatic diagnostics aren't available:

1. **Check container status:** `docker ps | grep dockerdiscordcontrol`
2. **View full logs:** `docker logs dockerdiscordcontrol -f`
3. **Verify port mapping:** `docker port dockerdiscordcontrol`
4. **Test internal connectivity:** `docker exec dockerdiscordcontrol curl -I http://localhost:9374`

### Creating a GitHub Issue

If none of these solve it, please create a GitHub issue with:
- Unraid version
- Full container logs (`docker logs dockerdiscordcontrol`)
- Port diagnostics output (from logs or `/port_diagnostics` endpoint)
- Port configuration screenshot
- Output of `docker port dockerdiscordcontrol`