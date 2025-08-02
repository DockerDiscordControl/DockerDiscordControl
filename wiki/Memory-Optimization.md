# Memory Optimization Guide

DockerDiscordControl has been extensively optimized for minimal memory usage while maintaining full functionality. This guide covers memory optimization techniques, monitoring, and troubleshooting.

## Memory Usage Overview

### **Current Performance**
- **Typical Usage**: 150-180MB RAM
- **Peak Usage**: <200MB RAM
- **Memory Limit**: 200MB (configurable)
- **Minimum Required**: 128MB RAM

### **Optimization Results**
```
Before Optimization:  190.3MB+ (growing)
After Optimization:   150-180MB (stable)
Memory Reduction:     20-40MB (15-20% improvement)
```

## Built-in Memory Optimizations

### **Python-Level Optimizations**

DDC includes several Python memory optimizations:

```bash
# Environment variables (automatically set)
PYTHONMALLOC=malloc          # Use system malloc
MALLOC_TRIM_THRESHOLD_=50000  # Aggressive memory trimming
PYTHONHASHSEED=0             # Deterministic hash behavior
PYTHONOPTIMIZE=2             # Maximum bytecode optimization
PYTHONDONTWRITEBYTECODE=1    # Prevent .pyc files
PYTHONUNBUFFERED=1           # Immediate output flushing
```

### **Application-Level Optimizations**

#### **Cache Management**
```python
# Automatic cache limits
DDC_MAX_CACHE_SIZE=50           # Status cache entries
DDC_MAX_PENDING_ACTIONS=10      # Pending Docker actions
DDC_MAX_TRACKED_CHANNELS=15     # Discord channel tracking
```

#### **Garbage Collection**
```python
# Memory monitoring and cleanup
DDC_MEMORY_LIMIT_MB=180         # Soft memory limit
DDC_GC_THRESHOLD_MB=140         # Garbage collection trigger
DDC_MEMORY_CHECK_INTERVAL=45    # Check interval (seconds)
```

#### **Resource Limits**
```python
# Production limits
DDC_MAX_CONTAINERS=50           # Maximum Docker containers
DDC_MAX_CHANNELS=15             # Maximum Discord channels
```

## ⚙️ Container-Level Optimization

### **Docker Memory Settings**

For optimal memory usage, configure your container with these limits:

```bash
docker run -d \
  --name ddc \
  --memory 200M \                # Hard memory limit
  --memory-swap 200M \           # No additional swap
  --memory-swappiness 0 \        # Disable swap usage
  --memory-reservation 120M \    # Soft limit
  # ... rest of configuration
```

### **Docker Compose Configuration**

```yaml
version: '3.8'
services:
  ddc:
    image: dockerdiscordcontrol/dockerdiscordcontrol:latest
    deploy:
      resources:
        limits:
          memory: 200M
        reservations:
          memory: 120M
    # ... rest of configuration
```

### **Unraid Template Settings**

The Unraid template includes optimized memory settings:

```xml
<Config Name="Memory Limit" Target="DDC_MEMORY_LIMIT_MB" Default="180" />
<Config Name="GC Threshold" Target="DDC_GC_THRESHOLD_MB" Default="140" />
<Config Name="Memory Check Interval" Target="DDC_MEMORY_CHECK_INTERVAL" Default="45" />
```

## 📈 Memory Monitoring

### **Real-time Monitoring**

```bash
# Monitor container memory usage
docker stats ddc --no-stream

# Detailed memory breakdown
docker exec ddc cat /proc/meminfo

# DDC-specific memory stats
docker logs ddc | grep -i memory
```

### **Performance Metrics**

DDC includes built-in memory monitoring:

```bash
# Check memory optimizer status
docker logs ddc | grep "Memory cleanup"

# View garbage collection stats
docker logs ddc | grep "GC performed"

# Monitor cache cleanup
docker logs ddc | grep "cache cleanup"
```

### **Grafana/Prometheus Integration**

For advanced monitoring, DDC exposes memory metrics:

```yaml
# Example Prometheus config
- job_name: 'ddc'
  static_configs:
  - targets: ['localhost:9374']
  metrics_path: '/metrics'
```

## Advanced Memory Tuning

### **Environment Variable Tuning**

Fine-tune memory behavior for your environment:

```bash
# Highly low memory (experimental)
DDC_MEMORY_LIMIT_MB=150
DDC_GC_THRESHOLD_MB=120
DDC_MEMORY_CHECK_INTERVAL=30
DDC_MAX_CACHE_SIZE=25
DDC_MAX_PENDING_ACTIONS=5

# High-performance (more memory available)
DDC_MEMORY_LIMIT_MB=256
DDC_GC_THRESHOLD_MB=200
DDC_MEMORY_CHECK_INTERVAL=60
DDC_MAX_CACHE_SIZE=100
DDC_MAX_PENDING_ACTIONS=20
```

### **Cache Optimization**

```bash
# Cache tuning
DDC_CACHE_TTL=30                    # Faster cache expiration
DDC_DOCKER_CACHE_DURATION=60       # Shorter Docker cache
DDC_ENABLE_BACKGROUND_REFRESH=false # Disable background refresh
```

### **Discord Optimization**

```bash
# Discord-specific optimizations
DDC_DISCORD_CACHE_DURATION=300     # 5-minute Discord cache
DDC_MAX_MESSAGE_HISTORY=100        # Limit message history
DDC_BATCH_UPDATE_SIZE=5             # Smaller batch updates
```

## 🔍 Memory Leak Detection

### **Automatic Leak Detection**

DDC includes automatic memory leak detection:

```python
# Memory trend monitoring
- Tracks memory usage over time
- Detects growing memory patterns
- Automatic cleanup triggers
- Leak prevention mechanisms
```

### **Manual Leak Investigation**

```bash
# Check for memory leaks
docker exec ddc python3 -c "
import gc, psutil, os
print(f'Memory: {psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024:.1f}MB')
print(f'Objects: {len(gc.get_objects())}')
gc.collect()
print(f'After GC: {psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024:.1f}MB')
"
```

### **Memory Profiling**

For development and debugging:

```bash
# Enable memory profiling
docker run -d \
  -e PYTHONMALLOC=debug \
  -e MALLOC_CHECK_=2 \
  # ... rest of configuration
```

## 🚨 Troubleshooting Memory Issues

### **High Memory Usage**

**❌ Memory usage >200MB**

**Diagnosis:**
```bash
# Check memory breakdown
docker exec ddc cat /proc/self/status | grep -E "(VmRSS|VmHWM)"

# Check for memory leaks
docker exec ddc python3 -c "import gc; print(len(gc.get_objects()))"
```

**Solutions:**
1. **Restart container**: `docker restart ddc`
2. **Reduce limits**: Lower `DDC_MAX_CACHE_SIZE`
3. **Check logs**: Look for memory warnings
4. **Update image**: Ensure latest optimizations

### **Memory Limit Exceeded**

**❌ Container killed by OOM**

**Diagnosis:**
```bash
# Check container exit code
docker inspect ddc --format='{{.State.ExitCode}}'

# Check system logs
dmesg | grep -i "killed process"
```

**Solutions:**
1. **Increase limit**: Raise Docker memory limit
2. **Optimize settings**: Reduce cache sizes
3. **Check configuration**: Verify environment variables

### **Memory Growth Over Time**

**❌ Gradual memory increase**

**Diagnosis:**
```bash
# Monitor memory trend
watch -n 10 'docker stats ddc --no-stream'

# Check cleanup frequency
docker logs ddc | grep "cleanup" | tail -20
```

**Solutions:**
1. **Force cleanup**: Restart with lower GC threshold
2. **Check cache**: Verify cache limits are working
3. **Update DDC**: Ensure latest memory fixes

## 📱 Platform-Specific Optimization

### **Unraid Optimization**

```bash
# Unraid-specific settings
--memory 180M                    # Conservative limit
--memory-reservation 120M        # Ensure availability
--oom-kill-disable=false        # Allow OOM protection
```

### **Raspberry Pi Optimization**

```bash
# ARM/Pi-specific settings
DDC_MEMORY_LIMIT_MB=128
DDC_GC_THRESHOLD_MB=100
DDC_MAX_CACHE_SIZE=25
DDC_MAX_CONTAINERS=25
DDC_MAX_CHANNELS=10
```

### **NAS Optimization**

```bash
# Synology/QNAP settings
--memory 200M
--memory-reservation 150M
DDC_MEMORY_LIMIT_MB=180
DDC_ENABLE_BACKGROUND_REFRESH=false
```

## Best Practices

### **Production Deployment**

1. **Set appropriate limits**: Match container limits to system capacity
2. **Monitor regularly**: Use `docker stats` for ongoing monitoring  
3. **Plan for growth**: Consider future container additions
4. **Test limits**: Verify performance under load

### **Development Environment**

1. **Use debug settings**: Enable verbose memory logging
2. **Profile regularly**: Check for memory leaks during development
3. **Test limits**: Validate optimizations with realistic data
4. **Document changes**: Note any custom memory configurations

### **Monitoring Checklist**

- [ ] **Container limits set**: Docker memory constraints configured
- [ ] **Environment variables**: DDC memory settings applied
- [ ] **Monitoring enabled**: Regular memory usage checks
- [ ] **Alerts configured**: Notifications for memory thresholds
- [ ] **Cleanup verified**: Automatic garbage collection working

## 📚 Related Documentation

- **[Alpine Migration](Alpine-Linux-Migration.md)**: OS-level optimizations
- **[Performance Guide](Performance-and-Architecture.md)**: Overall performance tuning
- **[Configuration](Configuration.md)**: Environment variable reference
- **[Troubleshooting](Troubleshooting.md)**: Common memory issues

## 🆘 Support

**Memory optimization help:**

- **Memory Issues**: [GitHub Issues](https://github.com/DockerDiscordControl/DockerDiscordControl/issues?q=label%3Amemory)
- **Performance Questions**: [GitHub Discussions](https://github.com/DockerDiscordControl/DockerDiscordControl/discussions)
- **Community Support**: [Discord Server](https://ddc.bot/discord)

---

**Optimized for efficiency!** DDC runs lean while maintaining full functionality. 