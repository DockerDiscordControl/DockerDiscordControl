# DockerDiscordControl (DDC)

**Homepage:** [https://ddc.bot](https://ddc.bot) | **[Complete Documentation](../../wiki)**

Control your Docker containers directly from Discord! This application provides a Discord bot and a web interface to manage Docker containers (start, stop, restart, view status) with revolutionary performance optimizations. Built on Alpine Linux for enhanced security and minimal resource usage.

[![Version](https://img.shields.io/badge/version-1.0.5-blue.svg)](https://github.com/DockerDiscordControl/DockerDiscordControl)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](https://github.com/DockerDiscordControl/DockerDiscordControl/blob/main/LICENSE)
[![Alpine Linux](https://img.shields.io/badge/Alpine_Linux-327MB-0D597F.svg?logo=alpine-linux)](https://hub.docker.com/r/dockerdiscordcontrol/dockerdiscordcontrol)
[![Docker Pulls](https://img.shields.io/docker/pulls/dockerdiscordcontrol/dockerdiscordcontrol.svg)](https://hub.docker.com/r/dockerdiscordcontrol/dockerdiscordcontrol)
[![Memory Optimized](https://img.shields.io/badge/RAM-<200MB-green.svg)](../../wiki/Memory‐Optimization)
[![Unraid](https://img.shields.io/badge/Unraid-Community_Apps-orange.svg)](UNRAID.md)
[![Wiki](https://img.shields.io/badge/documentation-wiki-blue.svg)](../../wiki)

## 🎯 **Choose Your Platform**

**DockerDiscordControl is now available with platform-optimized versions!**

| Platform | Repository | Description | Best For |
|----------|------------|-------------|----------|
| **🪟 Windows** | **[DockerDiscordControl-Windows](https://github.com/DockerDiscordControl/DockerDiscordControl-Windows)** | Windows Docker Desktop optimized | Windows 10/11 + Docker Desktop |
| **🐧 Linux** | **[DockerDiscordControl-Linux](https://github.com/DockerDiscordControl/DockerDiscordControl-Linux)** | Native Linux optimization | Ubuntu, Debian, CentOS, RHEL |
| **🍎 macOS** | **[DockerDiscordControl-Mac](https://github.com/DockerDiscordControl/DockerDiscordControl-Mac)** | Apple Silicon & Intel Mac optimized | macOS + Docker Desktop |
| **🔧 Universal** | **[DockerDiscordControl](https://github.com/DockerDiscordControl/DockerDiscordControl)** *(this repo)* | Multi-platform, Unraid focus | Unraid, NAS, servers |

### **🚀 Quick Platform Selection:**

- **🪟 Using Windows?** → [**Windows Version**](https://github.com/DockerDiscordControl/DockerDiscordControl-Windows) *(PowerShell scripts, WSL2 optimized)*
- **🐧 Running Linux?** → [**Linux Version**](https://github.com/DockerDiscordControl/DockerDiscordControl-Linux) *(Native systemd, package managers)*  
- **🍎 On macOS?** → [**Mac Version**](https://github.com/DockerDiscordControl/DockerDiscordControl-Mac) *(Apple Silicon + Intel, Homebrew)*
- **🔧 Unraid/NAS?** → **Use this repository** *(Universal, Community Apps support)*

---

## 🚀 Revolutionary Performance Breakthrough

**Major Performance Optimizations Delivered:**
- **Cache Updates**: 16x faster (33 seconds → 4 seconds)
- **Message Updates**: 7x faster (2.6 seconds → 350ms average)
- **Docker Stats**: Eliminated critical 5-17 second timeouts
- **Background Processing**: Patient data collection with UI responsiveness
- **Real-time Updates**: No more "N/A" values, accurate CPU/RAM data

## Features

- **Discord Bot**: Slash commands, status monitoring, container controls
- **Web Interface**: Secure configuration, permissions, logs, and monitoring  
- **Ultra-Fast Performance**: Revolutionary bulk processing and intelligent caching
- **Task System**: Schedule automated container actions (daily, weekly, monthly, one-time)
- **Security**: Channel-based permissions, rate limiting, comprehensive framework
- **Multi-Language**: English, German, French support
- **Alpine Linux**: 327MB image, 94% fewer vulnerabilities than Debian-based containers
- **Memory Optimized**: <200MB RAM usage with intelligent garbage collection
- **Production Ready**: Supports 50 containers across 15 Discord channels

**New in v3.0:** Revolutionary performance optimizations, complete security vulnerability remediation, 36% code reduction, 100% English documentation.

**Latest Updates:** Alpine Linux migration, aggressive memory optimization, Unraid Community Applications support, **platform-specific optimized versions**.

## 🚀 Quick Start

### **Platform-Specific Installation (Recommended)**

**Choose your platform for optimized experience:**

#### **🪟 Windows Users**
Visit: **[DockerDiscordControl-Windows](https://github.com/DockerDiscordControl/DockerDiscordControl-Windows)**
```powershell
# Clone Windows-optimized version
git clone https://github.com/DockerDiscordControl/DockerDiscordControl-Windows.git
cd DockerDiscordControl-Windows
# Follow Windows-specific setup guide
```

#### **🐧 Linux Users** 
Visit: **[DockerDiscordControl-Linux](https://github.com/DockerDiscordControl/DockerDiscordControl-Linux)**
```bash
# Clone Linux-optimized version
git clone https://github.com/DockerDiscordControl/DockerDiscordControl-Linux.git
cd DockerDiscordControl-Linux
# Follow Linux-specific setup guide
```

#### **🍎 macOS Users**
Visit: **[DockerDiscordControl-Mac](https://github.com/DockerDiscordControl/DockerDiscordControl-Mac)**
```bash
# Clone Mac-optimized version  
git clone https://github.com/DockerDiscordControl/DockerDiscordControl-Mac.git
cd DockerDiscordControl-Mac
# Follow macOS-specific setup guide
```

---

### **Universal Installation (Unraid & Servers)**

**For Unraid, NAS systems, and server deployments:**

#### Prerequisites

1. **Create Discord Bot**: [📖 Bot Setup Guide](../../wiki/Discord‐Bot‐Setup)
2. **Docker**: [Install Docker](https://docs.docker.com/engine/install/) + [Docker Compose](https://docs.docker.com/compose/install/)

#### Installation Methods

**Method 1: Docker Compose (Recommended)**

```bash
# Clone repository
git clone https://github.com/DockerDiscordControl/DockerDiscordControl.git
cd DockerDiscordControl

# Create directories
mkdir config logs

# Create .env file with secure secret key
echo "FLASK_SECRET_KEY=$(openssl rand -hex 32)" > .env

# Start container
docker compose up --build -d
```

**Method 2: Docker Hub (Direct)**

```bash
# Pull and run latest Alpine-optimized image
docker run -d --name ddc \
  -p 9374:9374 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v ./config:/app/config \
  -v ./logs:/app/logs \
  -e FLASK_SECRET_KEY="$(openssl rand -hex 32)" \
  --restart unless-stopped \
  dockerdiscordcontrol/dockerdiscordcontrol:latest
```

**Method 3: Unraid (Recommended for Unraid users)**
- Install via **Community Applications**
- Search for "DockerDiscordControl"
- **One-click install** with pre-configured paths
- [📖 Detailed Unraid Setup](UNRAID.md)

#### Configuration

1. **Access Web UI**: `http://<your-server-ip>:8374`
2. **Login**: Username `admin`, Password `admin` (change immediately!)
3. **Configure**: Bot token, Guild ID, container permissions
4. **Restart**: `docker compose restart` after initial setup

## Environment Variables

### Performance Optimization Variables (New in 2025)

DDC now includes advanced performance optimization settings that can be configured via environment variables:

#### Memory Optimization
```bash
# Docker Cache Settings
DDC_MAX_CACHED_CONTAINERS=100          # Maximum containers in cache (default: 100)
DDC_CACHE_CLEANUP_INTERVAL=300         # Cache cleanup interval in seconds (default: 300)
DDC_DOCKER_CACHE_DURATION=75           # Cache duration in seconds (default: 75)
DDC_DOCKER_MAX_CACHE_AGE=150          # Maximum cache age before forced refresh (default: 150)

# Background Refresh Settings
DDC_ENABLE_BACKGROUND_REFRESH=true     # Enable background Docker cache refresh (default: true)
DDC_BACKGROUND_REFRESH_INTERVAL=30     # Background refresh interval (default: 30)
```

#### CPU Optimization
```bash
# Scheduler Service Settings
DDC_SCHEDULER_CHECK_INTERVAL=120       # Scheduler check interval in seconds (default: 120)
DDC_MAX_CONCURRENT_TASKS=3             # Maximum concurrent tasks (default: 3)
DDC_TASK_BATCH_SIZE=5                  # Task batch processing size (default: 5)
```

#### Web Server Optimization
```bash
# Gunicorn Settings
GUNICORN_WORKERS=2                     # Number of worker processes (default: adaptive 1-3)
GUNICORN_MAX_REQUESTS=300              # Requests per worker before recycling (default: 300)
GUNICORN_MAX_REQUESTS_JITTER=30        # Random jitter for worker recycling (default: 30)
GUNICORN_TIMEOUT=45                    # Request timeout in seconds (default: 45)
GUNICORN_LOG_LEVEL=info                # Logging level (default: info)
```

#### Cache Control
```bash
# Configuration Cache
DDC_CONFIG_CACHE_AGE_MINUTES=15        # Config cache age in minutes (default: 15)

# Docker Query Settings
DDC_DOCKER_QUERY_COOLDOWN=1.0          # Minimum time between Docker API requests (default: 1.0)
```

### Performance Monitoring

Access real-time performance statistics via the Web UI at `/performance_stats` (requires authentication). This endpoint provides:

- **Memory Usage**: RAM consumption of all components
- **Cache Statistics**: Hit/miss ratios and cleanup times
- **System Resources**: CPU, memory, and thread monitoring
- **Scheduler Stats**: Task execution and batching metrics

### Recommended Settings by Deployment Size

#### Small Deployment (1-2 CPU cores, <2GB RAM)
```bash
GUNICORN_WORKERS=1
DDC_MAX_CACHED_CONTAINERS=50
DDC_SCHEDULER_CHECK_INTERVAL=180
DDC_MAX_CONCURRENT_TASKS=2
```

#### Medium Deployment (2-4 CPU cores, 2-4GB RAM)
```bash
GUNICORN_WORKERS=2
DDC_MAX_CACHED_CONTAINERS=100
DDC_SCHEDULER_CHECK_INTERVAL=120
DDC_MAX_CONCURRENT_TASKS=3
```

#### Large Deployment (4+ CPU cores, 4GB+ RAM)
```bash
GUNICORN_WORKERS=3
DDC_MAX_CACHED_CONTAINERS=200
DDC_SCHEDULER_CHECK_INTERVAL=90
DDC_MAX_CONCURRENT_TASKS=5
```

**Note**: All Web UI configuration options remain fully functional regardless of these performance optimizations. The interval frequency settings and all other configuration capabilities are preserved and unaffected.

## System Requirements

### **Minimum Requirements**
- **CPU**: 1 core (1.5 cores recommended)
- **RAM**: 150MB (200MB limit, <200MB typical usage)
- **Storage**: 100MB for application + config/logs space
- **Docker**: Docker Engine 20.10+ and Docker Compose 2.0+

### **Production Limits**
- **Maximum Containers**: 50 Docker containers
- **Maximum Channels**: 15 Discord channels  
- **Concurrent Operations**: 10 pending Docker actions
- **Cache Size**: 50 status entries with intelligent cleanup

### **Platform Support**

#### **🔧 This Universal Repository**
- **Unraid**: Native Community Applications support ⭐
- **Linux Servers**: x86_64, ARM64 (Raspberry Pi)
- **Docker**: Swarm, Compose, Standalone
- **NAS**: Synology, QNAP, TrueNAS

#### **🎯 Platform-Optimized Repositories**
- **🪟 [Windows](https://github.com/DockerDiscordControl/DockerDiscordControl-Windows)**: Docker Desktop, WSL2, PowerShell integration
- **🐧 [Linux](https://github.com/DockerDiscordControl/DockerDiscordControl-Linux)**: Native systemd, package managers, distributions
- **🍎 [macOS](https://github.com/DockerDiscordControl/DockerDiscordControl-Mac)**: Apple Silicon, Intel, Homebrew, Docker Desktop

## Documentation

| Topic | Description |
|-------|-------------|
| [Installation Guide](../../wiki/Installation‐Guide) | Detailed setup for all platforms |
| [Configuration](../../wiki/Configuration) | Web UI, permissions, channels |
| [Task System](../../wiki/Task‐System) | Automated scheduling system |
| [Performance](../../wiki/Performance‐and‐Architecture) | V3.0 optimizations & monitoring |
| [Alpine Migration](../../wiki/Alpine‐Linux‐Migration) | Benefits, security, optimization |
| [Memory Optimization](../../wiki/Memory‐Optimization) | Resource management, limits |
| [Unraid Setup](UNRAID.md) | Community Applications guide |
| [Troubleshooting](../../wiki/Troubleshooting) | Common issues & solutions |
| [Development](../../wiki/Development) | Contributing & development setup |
| [Security](../../wiki/Security) | Best practices & considerations |

## ⚠️ Security Notice

**Docker Socket Access Required**: This application requires access to `/var/run/docker.sock` to control containers. Only run in trusted environments and ensure proper host security.

**Default Credentials**: Change the default admin password immediately after first login!

## 🆘 Quick Help

**Common Issues:**
- **Permission Errors**: Run `docker exec ddc /app/scripts/fix_permissions.sh`
- **Configuration Not Saving**: Check file permissions in logs
- **Bot Not Responding**: Verify token and Guild ID in Web UI

**Need Help?** Check our [📖 Troubleshooting Guide](../../wiki/Troubleshooting) or create an issue.

## 🤝 Contributing

We welcome contributions! See our [Development Guide](../../wiki/Development) for setup instructions and coding standards.

**Contributing to Platform-Specific Versions:**
- **🪟 Windows**: [Contribute to Windows version](https://github.com/DockerDiscordControl/DockerDiscordControl-Windows)
- **🐧 Linux**: [Contribute to Linux version](https://github.com/DockerDiscordControl/DockerDiscordControl-Linux)
- **🍎 macOS**: [Contribute to Mac version](https://github.com/DockerDiscordControl/DockerDiscordControl-Mac)

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

**Like DDC? Star the repository!** | **Found a bug?** [Report it](../../issues) | **Feature idea?** [Suggest it](../../discussions)

**🌟 Don't forget to star the platform-specific repos too!** 
- **[⭐ Windows](https://github.com/DockerDiscordControl/DockerDiscordControl-Windows)**
- **[⭐ Linux](https://github.com/DockerDiscordControl/DockerDiscordControl-Linux)**  
- **[⭐ macOS](https://github.com/DockerDiscordControl/DockerDiscordControl-Mac)**

## Support DDC Development

Help keep DockerDiscordControl growing and improving across all platforms:

- **[Buy Me A Coffee](https://buymeacoffee.com/dockerdiscordcontrol)** - Quick one-time support
- **[PayPal Donation](https://www.paypal.com/donate/?hosted_button_id=XKVC6SFXU2GW4)** - Direct contribution  

Your support helps maintain DDC across **Windows, Linux, macOS, and Universal** versions, develop new features, and keep it zero-vulnerability secure! 

**🚀 Built for every platform - optimized for your environment!** 
