# 🚀 First Time Setup - DockerDiscordControl

This guide helps you set up DockerDiscordControl for the first time and handle password resets.

## 🔐 Initial Login Setup

### Method 1: Web Setup (Recommended)

1. **Access the setup page** in your browser:
   ```
   http://your-server-ip:5001/setup
   ```
   
2. **Or use temporary credentials** to access the setup:
   - Username: `admin` 
   - Password: `setup`
   - Then navigate to setup or change password

### Method 2: Environment Variable

1. **Set your admin password** before starting the container:
   ```bash
   docker run -e DDC_ADMIN_PASSWORD=your_secure_password -d dockerdiscordcontrol
   ```
   
2. **Or update existing container**:
   ```bash
   docker stop dockerdiscordcontrol
   docker run --rm -e DDC_ADMIN_PASSWORD=your_secure_password dockerdiscordcontrol
   docker start dockerdiscordcontrol
   ```

### Method 3: Using Reset Script

1. **Run the reset script inside the container**:
   ```bash
   docker exec -it dockerdiscordcontrol python3 scripts/reset_password.py
   ```

2. **Follow the prompts** to set your new password

## 🔄 Password Reset

If you've forgotten your password or need to change it:

### Option A: Environment Variable Reset
```bash
docker exec -e DDC_ADMIN_PASSWORD=new_password dockerdiscordcontrol python3 scripts/reset_password.py
```

### Option B: Interactive Reset
```bash
docker exec -it dockerdiscordcontrol python3 scripts/reset_password.py
```

### Option C: Config File Reset (Advanced)
```bash
# Stop container
docker stop dockerdiscordcontrol

# Delete web config to force recreation
docker exec dockerdiscordcontrol rm -f /app/config/web_config.json

# Set new password and restart
docker run --rm -e DDC_ADMIN_PASSWORD=new_password dockerdiscordcontrol
docker start dockerdiscordcontrol
```

## 🔍 Troubleshooting

### "Authentication Required" Error
This means no password is configured. Use the web setup (/setup) or environment variable method above.

### "No password hash configured" in Logs
This is the security system working correctly. Use `/setup` or set `DDC_ADMIN_PASSWORD` and restart.

### Can't Access Setup Page?
Try the temporary credentials: username `admin`, password `setup`

### Permission Errors
Make sure your Docker container has write access to the config directory:
```bash
docker exec dockerdiscordcontrol ls -la /app/config/
```

### Still Locked Out?
1. Check container logs:
   ```bash
   docker logs dockerdiscordcontrol
   ```

2. Access health endpoint:
   ```bash
   curl http://localhost:5001/health
   ```
   Look for `"first_time_setup_needed": true`

3. Nuclear option - reset everything:
   ```bash
   docker stop dockerdiscordcontrol
   docker exec dockerdiscordcontrol rm -rf /app/config/
   docker run --rm -e DDC_ADMIN_PASSWORD=new_password dockerdiscordcontrol
   docker start dockerdiscordcontrol
   ```

## 🛡️ Security Notes

- **Strong Passwords**: Use at least 12 characters with mixed case, numbers, and symbols
- **Password Hashing**: Uses PBKDF2-SHA256 with 600,000 iterations
- **No Default Credentials**: System fails securely if no password is configured
- **Session Security**: Sessions are invalidated when password changes

## 📋 Quick Reference

| Action | Command |
|--------|---------|
| First setup | `DDC_ADMIN_PASSWORD=password docker run -d dockerdiscordcontrol` |
| Reset password | `docker exec -it dockerdiscordcontrol python3 scripts/reset_password.py` |
| Check status | `curl http://localhost:5001/health` |
| View logs | `docker logs dockerdiscordcontrol` |
| Help | `docker exec dockerdiscordcontrol python3 scripts/reset_password.py --help` |

---

**Need more help?** Check the container logs or create an issue on GitHub.