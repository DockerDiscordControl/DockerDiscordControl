# Response to Unraid Web UI Connection Issue

Thank you for reporting this issue. I understand you're unable to access the Web UI at port 8374 on your Unraid system.

## Root Cause
The DDC container runs the Web UI internally on port **9374**, but it should be mapped to port **8374** externally for user access. It seems the port mapping wasn't applied correctly during installation.

## Solution

### Option 1: Check and Fix Port Mapping in Unraid
1. Go to your Unraid Web UI → Docker tab
2. Click on the DockerDiscordControl container
3. Click "Edit" 
4. Look for the "WebUI Port" setting
5. Ensure it shows:
   - **Host Port:** 8374
   - **Container Port:** 9374
6. Click "Apply" to save changes

### Option 2: Remove and Re-install
If the port mapping is incorrect or missing:
1. Stop and remove the current DDC container
2. Re-install from Community Apps
3. During installation, verify the port mapping shows `8374:9374`

### Option 3: Manual Docker Run Command
If the above doesn't work, you can manually run the container with:
```
docker run -d \
  --name DockerDiscordControl \
  -p 8374:9374 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /mnt/user/appdata/dockerdiscordcontrol/config:/app/config \
  -v /mnt/user/appdata/dockerdiscordcontrol/logs:/app/logs \
  --restart unless-stopped \
  dockerdiscordcontrol/dockerdiscordcontrol:latest
```

## Verification
After applying the fix, test the connection:
```
# From Unraid console
curl -I http://localhost:8374

# Should return:
HTTP/1.1 401 Unauthorized
WWW-Authenticate: Basic realm="Authentication Required"
Server: gunicorn
```

This 401 response is expected because DDC uses HTTP Basic Authentication. When you access the Web UI in a browser, you'll see a login popup asking for username/password (default: admin/admin).

## Additional Notes
- The container must map external port 8374 to internal port 9374
- The Web UI service (gunicorn) listens on port 9374 inside the container
- If port 8374 is already in use on your system, you can use any other free port (e.g., 8375) as the host port

## Automatic Diagnostics (v1.1.3c+)

If you're using DDC v1.1.3c or later, the container includes automatic port diagnostics:

1. **Check container logs** for the Port Diagnostics section:
   ```
   docker logs DockerDiscordControl | grep -A 20 "=== DDC Port Diagnostics ==="
   ```

2. **Via Web UI** (if accessible): Visit `http://[IP]:8374/port_diagnostics`

The diagnostics will automatically detect Unraid and provide specific solutions for your platform.

Please let me know if this resolves your issue or if you need further assistance!