# Supported Versions

## DockerDiscordControl Version Support

### Currently Supported Version

| Version | Support Status | Release Date | Notes |
|---------|---------------|--------------|-------|
| v2.4.1 | Current | 2026-09-22 | Last v2 release |
| < v2.4.1 | Unsupported | - | Upgrade to the current release |

v3.0.0 replaces v2.4.1 when it is released. Going back from v3.0 to v2.4.1 is
not supported (see the v3.0 release notes).

### Version 2.0.0 Features

- Multi-language support (German, French, English)
- 11-stage Mech Evolution system
- Performance improvements (16x faster caching)
- Modern Web UI
- Alpine Linux 3.22.1 security hardening
- Flask 3.1.1 and Werkzeug 3.1.3

### Installation

**Docker Hub:**
```bash
docker pull dockerdiscordcontrol/dockerdiscordcontrol:latest
docker-compose up -d
```

**From Source:**
```bash
git clone https://github.com/DockerDiscordControl/DockerDiscordControl.git
cd DockerDiscordControl
docker-compose up -d
```

### Upgrade Instructions

Upgrading from development versions:

```bash
# Pull latest changes
git checkout main
git pull origin main

# Rebuild container
docker-compose down
docker-compose pull
docker-compose up -d
```

**Note:** Development continues in the `v2.0` branch. The `main` branch contains production-ready code only.

### Support Policy

- **The current release**: bug fixes, security updates, and features
- **Older releases**: no support - upgrade to the current release

### Getting Support

For issues or questions:

1. Check [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
2. Review [CONFIGURATION.md](CONFIGURATION.md)
3. Check [SECURITY.md](SECURITY.md)
4. Open an issue on GitHub with:
   - Version number
   - Docker logs (`docker logs ddc`)
   - Steps to reproduce
   - Configuration (remove sensitive data)

### Security Updates

Security fixes are released as needed. To stay updated:

```bash
# Check for updates
docker pull dockerdiscordcontrol/dockerdiscordcontrol:latest

# Apply updates
docker-compose down
docker-compose up -d
```

Subscribe to GitHub releases for notifications.
