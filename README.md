# DockerDiscordControl v2.0 🐳

[![Version](https://img.shields.io/badge/Version-v2.0.0-brightgreen?style=for-the-badge)](https://github.com/DockerDiscordControl/DockerDiscordControl/releases/tag/v2.0.0) [![Python](https://img.shields.io/badge/Python-3.12-blue?style=for-the-badge)](https://python.org) [![Base Image](https://img.shields.io/badge/Base-Alpine%203.22.2-blueviolet?style=for-the-badge)](#-ultra-optimized-alpine-image) [![Tests](https://img.shields.io/badge/Tests-Passing-success?style=for-the-badge)](#-testing--quality-assurance) [![Coverage](https://img.shields.io/badge/Coverage-80%25-brightgreen?style=for-the-badge)](#-testing--quality-assurance) [![Docker Pulls](https://img.shields.io/docker/pulls/dockerdiscordcontrol/dockerdiscordcontrol?style=for-the-badge)](https://hub.docker.com/r/dockerdiscordcontrol/dockerdiscordcontrol) [![Unraid](https://img.shields.io/badge/Unraid-Community%20Apps-orange?style=for-the-badge)](./docs/UNRAID.md) [![Wiki](https://img.shields.io/badge/Documentation-Wiki-lightgrey?style=for-the-badge)](https://github.com/DockerDiscordControl/DockerDiscordControl/wiki)

A powerful Discord bot and web interface to manage Docker containers remotely. This application bridges the gap between Discord and your Docker environment, allowing container monitoring and control directly through Discord channels.

**Homepage:** [https://ddc.bot](https://ddc.bot) | **[Complete Documentation](../../wiki)**

Control your Docker containers directly from Discord! This application provides a Discord bot and a web interface to manage Docker containers (start, stop, restart, view status) with a focus on stability, security, and performance. The default image is an ultra-optimized Alpine Linux build with the latest security patches and enhanced performance.

## 🆕 Latest Updates

### ✅ **v2.0.0 (2025-11-18) - MAJOR UPDATE - Complete Rewrite**

🎮 **EVERYTHING via Discord - Complete Control:**
- **NEW:** Live Logs Viewer - Monitor container output in real-time directly in Discord
- **NEW:** Task System - Create, view, delete tasks (Once, Daily, Weekly, Monthly, Yearly) entirely in Discord
- **NEW:** Container Info System - Attach custom info and password-protected info to containers
- **NEW:** Public IP Display - Automatic WAN IP detection with custom port support
- Full container management without leaving Discord (start, stop, restart, bulk operations)

🌍 **Multi-Language Support:**
- **NEW:** Full Discord UI translation in German, French, and English
- Complete language coverage for all buttons, messages, and interactions
- Dynamic language switching via Web UI settings
- 100% translation coverage across entire bot interface

🤖 **Mech Evolution System:**
- **NEW:** 11-stage Mech Evolution with animated WebP graphics
- Continuous power decay system (minutengenau) for fair donation tracking
- Premium key system for power users
- Visual feedback with stage-specific animations and particle effects

⚡ **Performance Improvements:**
- **IMPROVED:** 16x faster Docker status cache (500ms → 31ms)
- 7x faster container processing through async optimization
- Smart queue system with fair request processing
- Operation-specific timeout optimization

🎨 **Modern UI/UX Overhaul:**
- **IMPROVED:** Beautiful Discord embeds with consistent styling
- Advanced spam protection with configurable cooldowns
- Enhanced container information system
- Real-time monitoring and status updates

🔒 **Security & Optimization:**
- **IMPROVED:** Alpine Linux 3.22.2 base (94% fewer vulnerabilities)
- Ultra-compact image (<200MB RAM usage)
- Production-ready security hardening
- Enhanced token encryption and validation

🐛 **Critical Fixes:**
- **FIXED:** Port mapping consistency (9374) for Unraid deployment
- Interaction timeout issues with defer() pattern
- Container control reliability improvements
- Web UI configuration persistence

**🚀 Ready for Unraid Community Applications! Complete rewrite with multi-language support, performance optimizations, and production-ready deployment!**

## Platform Selection

**DockerDiscordControl is now available with platform-optimized versions!**

| Platform | Repository | Description | Best For |
|----------|------------|-------------|----------|
| **Windows** | **[DockerDiscordControl-Windows](https://github.com/DockerDiscordControl/DockerDiscordControl-Windows)** | Windows Docker Desktop optimized | Windows 10/11 + Docker Desktop |
| **Linux** | **[DockerDiscordControl-Linux](https://github.com/DockerDiscordControl/DockerDiscordControl-Linux)** | Native Linux optimization | Ubuntu, Debian, CentOS, RHEL |
| **macOS** | **[DockerDiscordControl-Mac](https://github.com/DockerDiscordControl/DockerDiscordControl-Mac)** | Apple Silicon & Intel Mac optimized | macOS + Docker Desktop |
| **Universal** | **[DockerDiscordControl](https://github.com/DockerDiscordControl/DockerDiscordControl)** *(this repo)* | Multi-platform, Unraid focus | Unraid, NAS, servers |

### Quick Platform Selection:

- **Windows Users** → [**Windows Version**](https://github.com/DockerDiscordControl/DockerDiscordControl-Windows) *(PowerShell scripts, WSL2 optimized)*
- **Linux Users** → [**Linux Version**](https://github.com/DockerDiscordControl/DockerDiscordControl-Linux) *(Native systemd, package managers)*  
- **macOS Users** → [**Mac Version**](https://github.com/DockerDiscordControl/DockerDiscordControl-Mac) *(Apple Silicon + Intel, Homebrew)*
- **Unraid/NAS Users** → **Use this repository** *(Universal, Community Apps support)*

---

## v1.1.2-alpine: Ultra-Optimized & Secure

**Release v1.1.2-alpine brings massive performance improvements with an ultra-optimized Alpine Linux image.**
- **78% Size Reduction**: From 924MB to ~200MB - ultra-optimized Alpine Linux 3.22.2
- **Latest Security Patches**: Upgraded to Flask 3.1.1 and Werkzeug 3.1.3 to resolve all critical and high-severity CVEs
- **Enhanced Performance**: Faster startup times and reduced memory footprint
- **Docker Socket Fixes**: Resolved permissions and volume mount issues
- **Complete Functionality**: All features preserved while dramatically reducing resource usage

## Features - EVERYTHING via Discord! 🚀

### 🎮 Discord Container Control
- **Start, Stop, Restart** individual containers or **ALL containers at once**
- **Live Logs Viewer** - Monitor container output in real-time directly in Discord
- **Attach Custom Info** to containers (e.g., current WAN IP address, connection details)
- **Password-Protected Info** for secure data sharing within your Discord community
- **Container Status** monitoring with real-time updates

### 📅 Discord Task Scheduler
- **Create, view, and delete** automated tasks directly in Discord channels
- **Flexible Scheduling**: Once, Daily, Weekly, Monthly, Yearly
- **Full Task Management** - Complete control without leaving Discord
- **Timezone Configuration** for accurate scheduling across regions

### 🔒 Flexible Permissions System
- **Status Channels**: All members see container status and public info
- **Status Channels**: Admin users get admin panel access for full control
- **Control Channels**: Everyone gets full admin access to all features
- **Granular Container Permissions**: Fine-grained control per container (Status, Start, Stop, Restart, Active visibility)
- **Hide Containers** from Discord or configure custom visibility per container
- **Password-Protected Info**: Viewable by anyone who knows the password
- **Spam Protection**: All Discord commands and button clicks protected by configurable cooldowns

### 🌐 Web Interface
- **Secure Configuration Panel** with real-time monitoring
- **Container Management**: Configure permissions, custom info, and visibility
- **Task Management**: Create and manage scheduled tasks
- **Admin User Management**: Define who gets admin panel access in status channels
- **Security Audit**: Built-in security scoring and recommendations

### 🎨 Customization & Localization
- **Multi-Language Support**: Full Discord UI in English, German, and French
- **Customizable Container Order**: Organize containers in your preferred display order
- **Mech Evolution System**: 11-stage evolution with animated graphics and premium keys
- **Custom Branding**: Configure container display names and information

### ⚡ Performance & Optimization
- **16x Faster Docker Cache**: Optimized from 500ms to 31ms response time
- **7x Faster Processing**: Through async optimization and smart queue system
- **Alpine Linux 3.22.2**: 94% fewer vulnerabilities, less than 200MB RAM usage
- **Production Ready**: Supports 50 containers across 15 Discord channels
- **Intelligent Caching**: Background refresh for real-time data

**New in v1.1.2-alpine:** The default build is now an ultra-optimized ~200MB Alpine Linux image with 78% size reduction while maintaining full functionality and improving security.

**Latest Updates:** Upgraded to Flask 3.1.1 and Werkzeug 3.1.3, resolved all security vulnerabilities, and achieved massive optimization with Alpine Linux 3.22.2 base image.

## 🧪 Testing & Quality Assurance

DockerDiscordControl maintains **80% test coverage** with comprehensive automated testing:

### Test Suites
- **Unit Tests**: Service-level testing for core business logic
- **Integration Tests**: End-to-end workflow validation
- **Performance Tests**: Benchmarking and profiling with Locust
- **Security Tests**: Static Analysis Security Testing (SAST) with bandit & semgrep

### Continuous Integration
All code changes are automatically validated through GitHub Actions:
- ✅ **Automated Testing** - pytest with 80% coverage requirement
- ✅ **Code Quality** - pylint, flake8, mypy type checking
- ✅ **Security Scanning** - bandit, semgrep, safety dependency checks
- ✅ **Performance Benchmarks** - Automated performance regression testing

### Running Tests Locally

```bash
# Install test dependencies
pip install -r requirements-test.txt

# Run all tests
pytest

# Run with coverage report
pytest --cov=services --cov=app --cov=utils --cov-report=html

# Open coverage report
open htmlcov/index.html
```

### Development Branch

For active development with additional debug tools and utilities, check out the `v2.0` branch:

```bash
git checkout v2.0
```

The `v2.0` development branch includes:
- Additional debug scripts (`debug_*.py`)
- Fix utilities (`fix_*.sh`)
- Ad-hoc testing tools
- Development documentation

The `main` branch contains production-ready code with comprehensive test infrastructure.

## 🚀 Quick Start

### **Platform-Specific Installation (Recommended)**

**Choose your platform for optimized experience:**

#### **Windows Users**
Visit: **[DockerDiscordControl-Windows](https://github.com/DockerDiscordControl/DockerDiscordControl-Windows)**
```powershell
# Clone Windows-optimized version
git clone https://github.com/DockerDiscordControl/DockerDiscordControl-Windows.git
cd DockerDiscordControl-Windows
# Follow Windows-specific setup guide
```

#### **Linux Users** 
Visit: **[DockerDiscordControl-Linux](https://github.com/DockerDiscordControl/DockerDiscordControl-Linux)**
```bash
# Clone Linux-optimized version
git clone https://github.com/DockerDiscordControl/DockerDiscordControl-Linux.git
cd DockerDiscordControl-Linux
# Follow Linux-specific setup guide
```

#### **macOS Users**
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

1. **Create Discord Bot**: [Bot Setup Guide](../../wiki/Discord‐Bot‐Setup)
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
- [📖 Detailed Unraid Setup](docs/UNRAID.md)

#### First-Time Setup

**🚀 Easy Web Setup (Recommended)**

1. **Access Web UI**: `http://<your-server-ip>:9374`
2. **Setup Options**:
   - **Method 1**: Visit `/setup` for guided web setup
   - **Method 2**: Use temporary credentials: `admin` / `setup` 
   - **Method 3**: Set `DDC_ADMIN_PASSWORD=your_password` before starting

3. **Complete Setup**: Configure bot token, Guild ID, container permissions
4. **Restart**: `docker compose restart` after initial configuration

**Security Note**: Default password is 'setup' for initial access. MUST be changed immediately after first login for security!

**Upgrade from v1.1.3D**: Automatic migration! Your existing `config.json` will be automatically split into modular files and backed up. No manual action required.

## Environment Variables

### Security & Authentication

**🔐 Password Setup Options:**

```bash
# Option 1: Set admin password before first start (Recommended)
DDC_ADMIN_PASSWORD=your_secure_password_here

# Option 2: Use temporary credentials for web setup
# Visit http://your-server:9374 and login with: admin / setup
# Then complete setup through the web interface

# Flask security (auto-generated if not provided)
FLASK_SECRET_KEY=your-64-character-random-secret-key
```

**Important**: The default password is 'setup' for security setup. You MUST change this immediately after first login. For production deployments, set DDC_ADMIN_PASSWORD before first start.

### Performance Optimization Variables (New in 2025)

DDC now includes advanced performance optimization settings that can be configured via environment variables:

#### Memory Optimization
```bash
# Docker Cache Settings - Optimized for 1-minute Web UI updates
DDC_MAX_CACHED_CONTAINERS=100          # Maximum containers in cache (default: 100)
DDC_DOCKER_CACHE_DURATION=45           # Cache duration in seconds (default: 45, supports 1-min updates)
DDC_DOCKER_MAX_CACHE_AGE=90            # Maximum cache age before forced refresh (default: 90)
DDC_CACHE_CLEANUP_INTERVAL=300         # Memory cleanup interval in seconds (default: 300)

# Background Refresh Settings - CRITICAL for 1-minute Web UI updates
DDC_ENABLE_BACKGROUND_REFRESH=true     # Enable background Docker cache refresh (default: true)
DDC_BACKGROUND_REFRESH_INTERVAL=30     # Background refresh interval (default: 30, required for 1-min updates)
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

### Ultra-Optimized Alpine Image

The default build for this repository is now the stable, optimized Alpine image. To build it locally, simply use the standard rebuild script:

```bash
# This script now uses the optimized Dockerfile by default
./scripts/rebuild.sh
```

**Optimization Features:**
- **~50% smaller image size** compared to older Debian-based builds.
- **Stable and reliable** single-stage Docker build process.
- **Minimal runtime dependencies** - only essential packages included.
- **Production-only requirements** - testing dependencies excluded.
- **Latest security patches** for all dependencies.

**Important Cache Timing**: The Docker cache is updated every 30 seconds with a 45-second cache duration to ensure fresh data for users who set 1-minute update intervals in the Web UI. This timing is critical for maintaining data freshness at the minimum supported interval.

**Note**: All Web UI configuration options remain fully functional regardless of these performance optimizations. The interval frequency settings and all other configuration capabilities are preserved and unaffected.

## 🐳 Docker Images

**Ultra-optimized Alpine Linux image:**
- **Size:** 176MB with multi-stage build optimization
- **Base:** Alpine Linux 3.22.2 (latest secure version)  
- **Architecture:** Service-oriented modular design (v2.0)
- **Security:** Latest dependencies with all CVEs fixed
- **Performance:** Optimized for minimal resource usage and fast startup

```bash
docker pull dockerdiscordcontrol/dockerdiscordcontrol:latest
```

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
| [Unraid Setup](docs/UNRAID.md) | Community Applications guide |
| [Troubleshooting](../../wiki/Troubleshooting) | Common issues & solutions |
| [Development](../../wiki/Development) | Contributing & development setup |
| [Security](../../wiki/Security) | Best practices & considerations |

## ⚠️ Security Notice

**Docker Socket Access Required**: This application requires access to `/var/run/docker.sock` to control containers. Only run in trusted environments and ensure proper host security.

**First-Time Setup Required**: DDC v2.0+ uses temporary default password 'setup' for initial access. Use one of these secure setup methods:
- **Web Setup**: Visit `/setup` and create your password  
- **Temporary Access**: Login with `admin` / `setup`, then set real password
- **Environment Variable**: Set `DDC_ADMIN_PASSWORD` before starting container

**Password Security**: All passwords are hashed with PBKDF2-SHA256 (600,000 iterations) for maximum security.

## Quick Help

**First-Time Setup Issues:**
- **Can't Login**: Visit `/setup` or use `admin` / `setup` credentials
- **"Authentication Required"**: Use default credentials `admin` / `setup` or configure DDC_ADMIN_PASSWORD
- **Password Reset**: Run `docker exec -it ddc python3 scripts/reset_password.py`

**Common Issues:**
- **Permission Errors**: Run `docker exec ddc /app/scripts/fix_permissions.sh`
- **Configuration Not Saving**: Check file permissions in logs
- **Bot Not Responding**: Verify token and Guild ID in Web UI

**Need Help?** Check our [Troubleshooting Guide](../../wiki/Troubleshooting) or create an issue.

## Contributing

We welcome contributions! See our [Development Guide](../../wiki/Development) for setup instructions and coding standards.

**Contributing to Platform-Specific Versions:**
- **Windows**: [Contribute to Windows version](https://github.com/DockerDiscordControl/DockerDiscordControl-Windows)
- **Linux**: [Contribute to Linux version](https://github.com/DockerDiscordControl/DockerDiscordControl-Linux)
- **macOS**: [Contribute to Mac version](https://github.com/DockerDiscordControl/DockerDiscordControl-Mac)

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

**Like DDC? Star the repository!** | **Found a bug?** [Report it](../../issues) | **Feature idea?** [Suggest it](../../discussions)

**Don't forget to star the platform-specific repos too!** 
- **[Windows](https://github.com/DockerDiscordControl/DockerDiscordControl-Windows)**
- **[Linux](https://github.com/DockerDiscordControl/DockerDiscordControl-Linux)**  
- **[macOS](https://github.com/DockerDiscordControl/DockerDiscordControl-Mac)**

## Support DDC Development

Help keep DockerDiscordControl growing and improving across all platforms:

- **[Buy Me A Coffee](https://buymeacoffee.com/dockerdiscordcontrol)** - Quick one-time support
- **[PayPal Donation](https://www.paypal.com/donate/?hosted_button_id=XKVC6SFXU2GW4)** - Direct contribution  

Your support helps maintain DDC across **Windows, Linux, macOS, and Universal** versions, develop new features, and keep it zero-vulnerability secure! 

## Credits & Contributors

**DockerDiscordControl** is developed and maintained by:
- **Lead Developer**: MAX
- **Contributors**: Community contributions welcome via [Pull Requests](../../pulls)
- **Special Thanks**: All users who report bugs, suggest features, and support the project

Want to contribute? Check out our [Contributing Guidelines](docs/CONTRIBUTING.md)!

**Built for every platform - optimized for your environment!**
