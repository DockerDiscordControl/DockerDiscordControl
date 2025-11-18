# Memory Optimization

DockerDiscordControl v2.0 is designed to be memory-efficient, running on less than 200MB RAM under normal operation.

## Performance Metrics

**Typical Memory Usage:**
- Normal operation: 150-180MB RAM
- Peak usage: <200MB RAM
- Minimum recommended: 256MB allocated

## Built-in Optimizations

### 1. Alpine Linux Base

We use Alpine Linux 3.22.2 which provides:
- ✅ Small base image (~5MB)
- ✅ Minimal system packages
- ✅ Reduced memory footprint
- ✅ 94% fewer vulnerabilities vs other distributions

### 2. Multi-Stage Docker Build

Our Dockerfile uses multi-stage builds to minimize the final image:

```dockerfile
# Stage 1: Builder (includes build tools)
FROM alpine:3.22.2 AS builder
# ... build dependencies ...

# Stage 2: Runtime (minimal runtime only)
FROM alpine:3.22.2
# ... only runtime packages ...
```

**Benefits:**
- Build tools not included in final image
- Stripped Python stdlib (test, ensurepip, idlelib removed)
- Binary stripping for smaller size
- Cleaned .pyc files and __pycache__ directories

### 3. Python Runtime Optimizations

Environment variables set in the container:

```dockerfile
ENV PYTHONPATH="/opt/runtime/site-packages"
ENV PYTHONDONTWRITEBYTECODE=1  # Don't create .pyc files
ENV PYTHONUNBUFFERED=1         # Immediate output, no buffering
ENV PYTHONOPTIMIZE=1           # Optimize bytecode
```

**What these do:**
- `PYTHONDONTWRITEBYTECODE=1` - Prevents writing compiled .pyc files, saves disk I/O
- `PYTHONUNBUFFERED=1` - Disables output buffering, reduces memory usage
- `PYTHONOPTIMIZE=1` - Enables basic Python optimizations

### 4. Docker Container Limits

Memory limits are configured in `docker-compose.yml`:

```yaml
deploy:
  resources:
    limits:
      memory: 512M    # Maximum memory allowed
    reservations:
      memory: 128M    # Minimum memory reserved
```

**Configuration:**
- **Hard limit:** 512MB (container will be killed if exceeded)
- **Soft reservation:** 128MB (guaranteed minimum)
- **OOM protection:** Docker will restart container if OOM occurs

### 5. Efficient Service Architecture

**Docker Python SDK:**
- Direct socket communication (no CLI overhead)
- Minimal memory footprint
- Efficient container management

**Async Operations:**
- Event-driven Discord.py (no polling)
- Efficient message processing
- Minimal blocking operations

**Smart Caching:**
- Docker status cached to reduce API calls
- Efficient cache invalidation
- Memory-efficient data structures

## Resource Requirements

### Minimum System Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| RAM | 256MB | 512MB |
| CPU | 1 core | 2 cores |
| Disk | 500MB | 1GB |

### Platform-Specific Notes

**Unraid:**
- Works well with default 512MB limit
- Recommended: 512MB-1GB allocation
- Enable auto-restart on OOM

**Raspberry Pi:**
- Tested on Pi 3B+ and newer
- 512MB allocation recommended
- Monitor swap usage

**Low-Memory Systems:**
- Minimum 256MB can work for small setups
- Reduce concurrent container operations
- Limit number of tracked channels

## Monitoring Memory Usage

### Check Current Usage

```bash
# Docker stats
docker stats ddc

# Inside container
docker exec ddc free -m

# Detailed process info
docker exec ddc ps aux
```

### Expected Values

```
Normal Operation:
- RSS: 120-150MB
- VSZ: 180-200MB
- Shared: 20-30MB

Peak (during container actions):
- RSS: 150-180MB
- VSZ: 200-250MB
```

## Troubleshooting High Memory Usage

### If memory usage exceeds 300MB:

1. **Check for resource leaks:**
   ```bash
   docker logs ddc --tail 100 | grep -i "error\|warning"
   ```

2. **Restart the container:**
   ```bash
   docker-compose restart
   ```

3. **Check Docker daemon:**
   ```bash
   docker system df
   docker system prune  # Clean up unused data
   ```

4. **Reduce workload:**
   - Limit number of tracked Discord channels
   - Reduce number of managed containers
   - Disable unnecessary features

### OOM (Out of Memory) Errors

If the container is killed due to OOM:

1. **Increase memory limit:**
   ```yaml
   # In docker-compose.yml
   deploy:
     resources:
       limits:
         memory: 768M  # Increase from 512M
   ```

2. **Check for memory leaks:**
   - Review recent code changes
   - Check for stuck tasks or connections
   - Monitor over time

3. **Reduce concurrent operations:**
   - Limit parallel container actions
   - Reduce cache sizes if customized

## Performance Tips

### DO:
- ✅ Use recommended memory limits (512MB)
- ✅ Monitor memory usage periodically
- ✅ Keep Docker daemon healthy (prune regularly)
- ✅ Update to latest DDC version (includes optimizations)
- ✅ Use SSD storage for better I/O performance

### DON'T:
- ❌ Set memory limit below 256MB
- ❌ Disable swap completely (unless required)
- ❌ Run on systems with <512MB total RAM
- ❌ Manage 50+ containers simultaneously
- ❌ Track 20+ Discord channels on low-memory systems

## Technical Details

### Image Size
- **Base image:** Alpine 3.22.2 (~7MB)
- **Final image:** ~180MB
- **With all dependencies:** ~200MB total

### Memory Breakdown (Approximate)
- Python runtime: ~40MB
- Discord.py bot: ~60MB
- Flask web UI: ~30MB
- Docker Python SDK: ~20MB
- OS/System: ~30MB
- **Total:** ~180MB

### Optimization Techniques Used
1. **Stripped binaries** - All .so files stripped with `strip --strip-unneeded`
2. **Minimal Python stdlib** - Removed test, tkinter, idlelib, lib2to3
3. **No pip/setuptools** - Build-only dependencies removed from venv
4. **Compiled bytecode optimization** - PYTHONOPTIMIZE=1
5. **Alpine Linux** - Minimal base distribution
6. **Single-purpose processes** - supervisord manages bot + web UI efficiently

## Future Optimizations

Potential improvements for future versions:
- Additional Python garbage collection tuning
- Configurable cache size limits
- Memory usage metrics API endpoint
- Prometheus/Grafana integration for monitoring

## Comparison with Other Solutions

| Solution | Typical RAM | Image Size | Notes |
|----------|-------------|------------|-------|
| **DDC v2.0** | **150-180MB** | **~200MB** | Optimized Alpine |
| Portainer | 200-300MB | ~400MB | Feature-rich UI |
| Generic Python/Discord bot | 100-150MB | ~300MB | Minimal features |
| Watchtower | 30-50MB | ~20MB | Single-purpose only |

**DDC provides excellent memory efficiency for its feature set**, combining Discord bot, web UI, task scheduling, and Docker management in under 200MB RAM.

---

**Last Updated:** 2025-01-18
**Version:** v2.0.0
**Documentation:** https://github.com/DockerDiscordControl/DockerDiscordControl
