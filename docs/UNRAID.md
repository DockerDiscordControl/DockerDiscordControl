# 🚀 DockerDiscordControl (DDC) - Unraid Installation Guide

![DDC Logo](https://raw.githubusercontent.com/DockerDiscordControl/DockerDiscordControl/main/app/static/favicon.png)

## 📋 Quick Start

DDC is available in **Unraid Community Applications**! Simply search for "DockerDiscordControl" or "DDC" and install with one click.

### 🔍 Alternative: Manual Installation

If not yet available in Community Applications, you can install manually:

1. Go to **Docker** tab in Unraid
2. Click **Add Container**
3. Set **Repository**: `dockerdiscordcontrol/dockerdiscordcontrol:latest`
4. Configure the paths and settings below

## ⚙️ Required Configuration

### 📁 **Essential Paths**
- **Config**: `/mnt/user/appdata/dockerdiscordcontrol/config`
- **Logs**: `/mnt/user/appdata/dockerdiscordcontrol/logs`
- **Docker Socket**: `/var/run/docker.sock` (READ/WRITE access required)

### 🌐 **Network**
- **WebUI Port**: `9374` (or any available port)
- **Network Type**: Bridge

### 🔐 **Essential Variables**
- **FLASK_SECRET_KEY**: Generate a secure random key!

```bash
# Generate a secure key on Unraid terminal:
openssl rand -base64 32
```

## 🎯 Container Setup

### **Basic Settings**
```
Repository: dockerdiscordcontrol/dockerdiscordcontrol:latest
Network: bridge
WebUI: http://[IP]:9374
```

### **Volume Mappings**
```
/mnt/user/appdata/dockerdiscordcontrol/config  ->  /app/config
/mnt/user/appdata/dockerdiscordcontrol/logs    ->  /app/logs
/var/run/docker.sock                           ->  /var/run/docker.sock
```

### **Environment Variables**
```
PUID=99                                  # Unraid default (nobody)
PGID=100                                 # Unraid default (users)
DDC_ADMIN_PASSWORD=your-secure-password  # REQUIRED - set during installation
FLASK_SECRET_KEY=your-secure-random-key  # Recommended for persistent sessions
```

### **Permission Variables (PUID/PGID)**

DDC v2.1.2+ automatically handles Unraid permissions via PUID/PGID:

| Variable | Unraid Default | Description |
|----------|----------------|-------------|
| `PUID` | `99` | User ID (Unraid's `nobody` user) |
| `PGID` | `100` | Group ID (Unraid's `users` group) |

**How to find your values:**
```bash
# In Unraid terminal:
ls -ln /mnt/user/appdata
# Look at the UID (3rd column) and GID (4th column)
```

The container automatically:
1. Creates a user with the specified PUID/PGID
2. Fixes volume permissions on startup
3. Drops privileges to the unprivileged user

## 🚀 First-Time Setup

1. **Install the container** using Community Applications or manually
2. **Set admin password** via `DDC_ADMIN_PASSWORD` environment variable (REQUIRED)
3. **Access Web UI** at `http://[UNRAID-IP]:9374`
4. **Login**: Username `admin`, password = your `DDC_ADMIN_PASSWORD`
5. **Configure Discord bot** in the Settings tab
6. **Set up Discord channels** in Channel Configuration

## 🎮 Discord Bot Setup

1. Create Discord Application at https://discord.com/developers/applications
2. Create a Bot and copy the Token
3. Add Bot to your Discord server with these permissions:
   - Send Messages
   - Embed Links
   - Use Slash Commands
   - Read Message History
4. Enter Bot Token in DDC Web UI

## 📊 Resource Requirements

### **Minimum System Requirements**
- **CPU**: 1 core (1.5 cores recommended)
- **RAM**: 150MB (200MB limit set by default)
- **Storage**: 100MB for app + config/logs space

### **Unraid Optimizations**
- DDC is built on **Alpine Linux** for security and efficiency
- **327MB Docker image** (20% smaller than Debian-based)
- **94% fewer vulnerabilities** compared to standard images
- Optimized for **low memory usage** on Unraid systems

## 🔧 Advanced Configuration

### **Memory Optimization**
```bash
# Fine-tune memory settings in Container Variables:
DDC_MEMORY_LIMIT_MB=180          # Memory limit for DDC
DDC_GC_THRESHOLD_MB=140          # Garbage collection threshold
DDC_MEMORY_CHECK_INTERVAL=45     # Memory check interval (seconds)
```

### **Performance Tuning**
```bash
# Cache and performance settings:
DDC_CACHE_TTL=60                 # Docker status cache duration
DDC_DOCKER_CACHE_DURATION=120    # Docker API cache duration
DDC_MAX_CACHE_SIZE=50            # Maximum cache entries
```

### **Scale Limits**
```bash
# Production limits:
DDC_MAX_CONTAINERS=50            # Max containers to manage
DDC_MAX_CHANNELS=15              # Max Discord channels
DDC_MAX_PENDING_ACTIONS=10       # Max pending Docker actions
```

## 🔍 Troubleshooting

### **Common Issues**

**❌ "Bot not responding"**
- Check Discord token in Settings
- Verify bot has required permissions
- Check logs: `docker logs DockerDiscordControl`

**❌ "Cannot access Docker"**
- Ensure `/var/run/docker.sock` is mapped correctly
- Verify READ/WRITE access to Docker socket

**❌ "WebUI not accessible"**
- Check port mapping and Unraid firewall
- Verify container is running: `docker ps`

### **Log Locations**
```
Container logs: docker logs DockerDiscordControl
DDC logs: /mnt/user/appdata/dockerdiscordcontrol/logs/
Web logs: /mnt/user/appdata/dockerdiscordcontrol/logs/web.log
Bot logs: /mnt/user/appdata/dockerdiscordcontrol/logs/bot.log
```

## 🔄 Updates

DDC auto-updates are handled through Unraid's container update system:

1. **Community Applications**: Update notifications appear automatically
2. **Manual**: Pull latest image and recreate container
3. **Rolling Updates**: New versions pushed regularly to Docker Hub

### **Update Commands**
```bash
# Update to latest version:
docker pull dockerdiscordcontrol/dockerdiscordcontrol:latest
# Then recreate container in Unraid Docker tab
```

## 🆘 Support

- **Documentation**: https://ddc.bot
- **GitHub Issues**: https://github.com/DockerDiscordControl/DockerDiscordControl/issues
- **Discord Support**: Available in our support channels
- **Unraid Forums**: Search for "DockerDiscordControl"

## 🎯 Features Overview

### **Discord Integration**
- ✅ Real-time container status monitoring
- ✅ Slash commands for container control
- ✅ Interactive buttons and embeds
- ✅ Scheduled task management
- ✅ Heartbeat monitoring
- ✅ Channel-based permissions

### **Web Interface**
- ✅ Modern, responsive UI
- ✅ Container management and logs
- ✅ Configuration management
- ✅ Real-time status monitoring
- ✅ User management
- ✅ Security settings

### **Unraid Optimizations**
- ✅ Alpine Linux base (security-focused)
- ✅ Low memory footprint (<200MB)
- ✅ Docker socket integration
- ✅ Unraid path conventions
- ✅ Community Applications ready
- ✅ Auto-restart capabilities

## 💖 Support DDC Development

Love using DDC on Unraid? Help keep it growing and secure:

- ☕ **[Buy Me A Coffee](https://buymeacoffee.com/dockerdiscordcontrol)** - Quick one-time support
- 💙 **[PayPal Donation](https://www.paypal.com/donate/?hosted_button_id=XKVC6SFXU2GW4)** - Direct contribution
- 🌟 **[GitHub Sponsors](https://github.com/sponsors/DockerDiscordControl)** - Ongoing support (coming soon)

Your support helps maintain DDC, develop new features, and keep it zero-vulnerability secure! 🛡️

---

**Happy container management!** 🐳✨ 