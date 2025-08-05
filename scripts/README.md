# DockerDiscordControl Scripts

This directory contains build and deployment scripts for DDC.

## Working Scripts

### rebuild.sh
The main build script that:
- Stops and removes existing DDC container
- Builds the Docker image from the standard Dockerfile
- Starts the new container with proper configuration
- **This is the script you should use for normal rebuilds**

### rebuild-debian.sh  
Alternative build script that uses Dockerfile.debian instead of the Alpine-based image.
Only use if you specifically need Debian-based image.

### start.sh
Quick start script that runs the container without rebuilding the image.
Useful for restarting after configuration changes.

### fix_permissions.sh
Fixes file permissions for config and log directories.
Run this if you encounter permission errors.

## Removed Scripts

The following scripts were removed as they were non-functional or misleading:
- `security-update.sh` - Only created text files without applying updates
- `rebuild-alpine.sh` - Referenced non-existent Dockerfile.alpine
- `rebuild-fast.sh` - No actual fast build implementation
- `rebuild-debug.sh` - No debug functionality implemented  
- `build-production.sh` - Incomplete multi-arch build
- `build-unraid.sh` - Duplicate of rebuild.sh

## Usage

For normal operations, simply use:
```bash
./scripts/rebuild.sh
```

This will rebuild and restart your DDC container with the latest code changes.