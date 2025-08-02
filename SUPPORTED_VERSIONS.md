# Supported Versions

## DockerDiscordControl Version Support

### Currently Supported Versions

| Version | Support Status | Notes |
|---------|---------------|-------|
| v1.1.3c | ✅ **Current** | Latest stable release with Python 3.13 support |
| v1.1.3b | ✅ Supported | Previous stable release |
| v1.1.3a | ✅ Supported | Security patches only |
| v1.1.3  | ⚠️ Deprecated | Upgrade recommended |
| < v1.1  | ❌ Unsupported | No longer maintained |

### Version History

- **v1.1.3c** (Current) - Python 3.13 compatibility, Docker build fixes
- **v1.1.3b** - Security and stability improvements
- **v1.1.3a** - Performance optimizations
- **v1.1.3** - Major security update
- **v1.1.2** - Alpine Linux optimizations
- **v1.1.1** - Initial Alpine release
- **v1.1.0** - Feature complete release
- **v1.0.x** - Legacy versions (unsupported)

### Important Notes

- There are **NO** versions 2.x or 3.x of DockerDiscordControl
- The project follows semantic versioning starting from v1.0.0
- Always use the latest v1.1.3x release for best security and stability

### Upgrade Instructions

To upgrade to the latest version:

```bash
git pull origin main
./scripts/rebuild.sh
```

Or use the specific release tag:

```bash
git checkout v1.1.3c
./scripts/rebuild.sh
```

### Support Policy

- **Current Release**: Full support with bug fixes and features
- **Previous 2 Releases**: Security patches only
- **Older Releases**: No support, upgrade required

For questions about version support, please open an issue on GitHub.