# GitHub Actions Workflows

## 🐳 Docker Publishing Strategy

### **Universal Repository (This Repo)**
- **Publishes to:** `dockerdiscordcontrol/dockerdiscordcontrol`
- **Image Type:** Ultra-optimized Alpine Linux image
- **Use Case:** Universal deployment, Unraid, general Docker usage
- **Dockerfile:** `Dockerfile.alpine-optimized`

### **Platform-Specific Repositories**
Each platform-specific repository handles its own optimized Docker image:

- **🪟 Windows Repository:** `dockerdiscordcontrol/dockerdiscordcontrol-windows`
  - Debian-based multi-stage build optimized for Windows environments
  - Docker Desktop on Windows, WSL2 compatibility
  
- **🍎 Mac Repository:** `dockerdiscordcontrol/dockerdiscordcontrol-mac`
  - Alpine-based build optimized for macOS environments
  - Apple Silicon and Intel Mac compatibility
  
- **🐧 Linux Repository:** `dockerdiscordcontrol/dockerdiscordcontrol-linux`
  - Alpine-based build optimized for Linux server environments
  - ARM64 and x86_64 architecture support

## 🔧 Workflow Files

### `docker-publish.yml`
- **Triggers:** Push to main, tags, manual dispatch
- **Builds:** Universal Alpine image using `Dockerfile.alpine-optimized`
- **Tags:** `latest`, `unraid`, semantic versions
- **Target:** Docker Hub `dockerdiscordcontrol/dockerdiscordcontrol`

## 🚀 Benefits of This Structure

1. **No Conflicts:** Each repository publishes only its optimized image
2. **Platform Optimization:** Each image is tailored for its target environment  
3. **Clear Separation:** Users know exactly which image to use
4. **Reduced Complexity:** No cross-repository publishing conflicts
5. **Better Maintenance:** Each team can focus on their platform

## 📦 Image Selection Guide

| Platform | Docker Hub Repository | Best For |
|----------|----------------------|----------|
| **Universal/Unraid** | `dockerdiscordcontrol/dockerdiscordcontrol` | Most users, Unraid Community Apps |
| **Windows** | `dockerdiscordcontrol/dockerdiscordcontrol-windows` | Docker Desktop on Windows, WSL2 |
| **macOS** | `dockerdiscordcontrol/dockerdiscordcontrol-mac` | Docker Desktop on Mac, Homebrew |
| **Linux Servers** | `dockerdiscordcontrol/dockerdiscordcontrol-linux` | Dedicated Linux servers, ARM64 |

## ⚡ Quick Start Examples

### Universal (Recommended)
```bash
docker pull dockerdiscordcontrol/dockerdiscordcontrol:latest
```

### Platform-Specific
```bash
# Windows
docker pull dockerdiscordcontrol/dockerdiscordcontrol-windows:latest

# macOS  
docker pull dockerdiscordcontrol/dockerdiscordcontrol-mac:latest

# Linux
docker pull dockerdiscordcontrol/dockerdiscordcontrol-linux:latest
``` 