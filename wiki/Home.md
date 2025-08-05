# DockerDiscordControl Wiki

Control your Docker containers directly from Discord.

DockerDiscordControl (DDC) is an application that bridges Discord and Docker, allowing you to manage containers through Discord commands and a web interface. Built on Alpine Linux for security and minimal resource usage.

## Quick Start

| Step | Guide | Description |
|------|--------|-------------|
| 1 | [Discord Bot Setup](Discord-Bot-Setup) | Create Discord bot and get credentials |
| 2 | [Installation Guide](Installation-Guide) | Install DDC on your platform |
| 3 | [Configuration](Configuration) | Set up web interface and permissions |

For first-time users, start with the [Installation Guide](Installation-Guide).

## Documentation

### Setup & Configuration
- [Installation Guide](Installation-Guide) - Setup for Docker Compose, Unraid, Synology
- [Discord Bot Setup](Discord-Bot-Setup) - Create and configure your Discord bot
- [Configuration](Configuration) - Web UI setup, permissions, security settings

### Features & Usage
- [Task System](Task-System) - Schedule automated container actions
- [Performance & Architecture](Performance-and-Architecture) - System architecture and optimizations
- [Alpine Linux Migration](Alpine-Linux-Migration) - Migration guide and benefits
- [Memory Optimization](Memory-Optimization) - Resource management
- [Security](Security) - Best practices and security considerations

### Support & Development
- [Troubleshooting](Troubleshooting) - Common issues and solutions
- [Development](Development) - Contributing guidelines

## Key Features

### Discord Integration
- Modern slash commands for container operations
- Real-time container status monitoring
- Channel-based permission control
- Fast response times with optimized caching

### Web Interface
- Responsive configuration interface
- Secure authentication and session management
- Live log viewing and monitoring
- Granular permission management

### Performance
- Intelligent caching system
- **Batch Processing**: Efficient bulk operations
- **Background Refresh**: Proactive status updates
- **Resource Optimization**: 36% code reduction with improved performance

### Alpine Linux Base
- 327MB image size
- Reduced attack surface with minimal packages
- Enhanced security
- Supports large deployments

### Memory Optimized
- Low memory footprint (<200MB RAM)
- Automatic garbage collection
- Configurable resource limits
- Memory leak prevention

## Perfect For

- Homelab management through Discord
- Remote container administration for teams
- Development environment control
- Infrastructure monitoring in Discord servers

## Support

| Issue Type | Resource |
|------------|----------|
| Bug Reports | [GitHub Issues](../../issues) |
| Feature Requests | [GitHub Discussions](../../discussions) |
| Configuration Problems | [Troubleshooting Guide](Troubleshooting) |
| Installation Issues | [Installation Guide](Installation-Guide) |
| Security Questions | [Security Guide](Security) |

## What's New in v1.1.3c

- Python 3.13 compatibility
- Docker build improvements and caching fixes
- Bug fixes for channel regeneration and scheduled tasks
- Documentation cleanup and version clarification
- Enhanced security and configuration handling
- Performance improvements for Discord operations

## Recent Updates

- Alpine Linux base for enhanced security
- Memory optimization with <200MB RAM usage
- Optimized for large deployments
- Native Unraid Community Apps support
- Improved security with reduced vulnerabilities
- Smaller container images (327MB)

## Community

- Star the project on [GitHub](../../)
- Report bugs via [Issues](../../issues)
- Suggest features in [Discussions](../../discussions)
- Contribute - see [Development Guide](Development)

---

Ready to get started? See the [Installation Guide](Installation-Guide).

Homepage: [https://ddc.bot](https://ddc.bot) | License: [MIT](../../blob/main/LICENSE) | Version: 1.1.3c