# Installation Guide

This guide covers installing DockerDiscordControl on various platforms.

## Prerequisites

### Discord Bot Setup
Before installing DDC, you need a Discord bot. Follow the [Discord Bot Setup Guide](Discord-Bot-Setup) to:
- Create Discord application and bot
- Get bot token and guild ID
- Configure permissions and intents

### System Requirements
- **Docker**: Version 20.10 or later
- **Docker Compose**: Version 2.0 or later (recommended)
- **Memory**: Minimum 512MB RAM available
- **CPU**: 1+ cores (2+ recommended for optimal performance)
- **Storage**: ~500MB for container + config/logs storage

## Method 1: Docker Compose (Recommended)

### Standard Installation

1. **Clone Repository**
   ```bash
   git clone https://github.com/DockerDiscordControl/DockerDiscordControl.git
   cd DockerDiscordControl
   ```

2. **Create Required Directories**
   ```bash
   mkdir config logs
   ```

3. **Create Environment File**
   Create `.env` file with secure configuration:
   ```bash
   # Generate secure secret key
   echo "FLASK_SECRET_KEY=$(openssl rand -hex 32)" > .env
   
   # Optional: Add custom admin password
   echo "DDC_ADMIN_PASSWORD=your_secure_password" >> .env
   ```

4. **Review Docker Compose Configuration**
   The default `docker-compose.yml` includes:
   ```yaml
   version: '3.8'
   services:
     ddc:
       build: .
       container_name: ddc
       ports:
         - "8374:8374"
       volumes:
         - /var/run/docker.sock:/var/run/docker.sock
         - ./config:/app/config
         - ./logs:/app/logs
       environment:
         - FLASK_SECRET_KEY=${FLASK_SECRET_KEY}
         - DDC_ADMIN_PASSWORD=${DDC_ADMIN_PASSWORD:-admin}
       deploy:
         resources:
           limits:
             cpus: '2.0'
             memory: 512M
           reservations:
             memory: 128M
       restart: unless-stopped
   ```

5. **Build and Start Container**
   ```bash
   docker compose up --build -d
   ```

6. **Verify Installation**
   ```bash
   # Check container status
   docker compose ps
   
   # View logs
   docker compose logs -f
   ```

### Custom Configuration

**Different Docker Socket Location:**
```yaml
volumes:
  - /path/to/your/docker.sock:/var/run/docker.sock
```

**Custom Host Paths:**
```yaml
volumes:
  - /your/custom/config:/app/config
  - /your/custom/logs:/app/logs
```

**Different Port:**
```yaml
ports:
  - "9000:8374"  # Access via port 9000
```

**Resource Limits:**
```yaml
deploy:
  resources:
    limits:
      cpus: '4.0'      # Allow 4 CPU cores
      memory: 1G       # Increase to 1GB RAM
```

## Method 2: Standard Docker

If you prefer using Docker directly without Compose:

```bash
# Build image
docker build -t ddc .

# Run container
docker run -d \
  --name ddc \
  -p 8374:8374 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v $(pwd)/config:/app/config \
  -v $(pwd)/logs:/app/logs \
  -e FLASK_SECRET_KEY="$(openssl rand -hex 32)" \
  --restart unless-stopped \
  ddc
```

## Method 3: Unraid

### Installation via Community Applications

1. **Install Community Applications**
   - In Unraid WebUI, go to "Plugins"
   - Install "Community Applications" if not already installed

2. **Search for DDC**
   - Go to "Apps" tab
   - Search for "DockerDiscordControl"
   - Click "Install"

3. **Configure Template**

   **Basic Settings:**
   - **Name**: `DockerDiscordControl` (or your preferred name)
   - **Repository**: `ghcr.io/dockerdiscordcontrol/dockerdiscordcontrol:latest`
   - **Network Type**: `bridge`

   **Port Configuration:**
   - **Container Port**: `8374`
   - **Host Port**: `8374` (change if port conflicts)

   **Volume Mappings:**
   ```
   Container Path: /app/config
   Host Path: /mnt/user/appdata/dockerdiscordcontrol/config
   Access Mode: Read/Write
   
   Container Path: /app/logs  
   Host Path: /mnt/user/appdata/dockerdiscordcontrol/logs
   Access Mode: Read/Write
   
   Container Path: /var/run/docker.sock
   Host Path: /var/run/docker.sock
   Access Mode: Read/Write
   ```

   **Environment Variables:**
   ```
   FLASK_SECRET_KEY: [Generate 32-byte hex key]
   DDC_ADMIN_PASSWORD: [Your secure password]
   ```

4. **Apply Configuration**
   - Click "Apply" to create and start container
   - Monitor logs during first startup

### Manual Unraid Installation

1. **Access Unraid Terminal**
   ```bash
   # Create app directory
   mkdir -p /mnt/user/appdata/dockerdiscordcontrol/{config,logs}
   
   # Set permissions
   chown -R nobody:users /mnt/user/appdata/dockerdiscordcontrol
   chmod -R 755 /mnt/user/appdata/dockerdiscordcontrol
   ```

2. **Create Docker Command**
   ```bash
   docker run -d \
     --name='DockerDiscordControl' \
     --net='bridge' \
     -e FLASK_SECRET_KEY="$(openssl rand -hex 32)" \
     -e DDC_ADMIN_PASSWORD='your_password' \
     -p '8374:8374' \
     -v '/mnt/user/appdata/dockerdiscordcontrol/config':'/app/config':'rw' \
     -v '/mnt/user/appdata/dockerdiscordcontrol/logs':'/app/logs':'rw' \
     -v '/var/run/docker.sock':'/var/run/docker.sock':'rw' \
     --restart unless-stopped \
     'ghcr.io/dockerdiscordcontrol/dockerdiscordcontrol:latest'
   ```

## Method 4: Synology NAS

### Via Container Manager

1. **Download Image**
   - Open Container Manager
   - Go to "Registry"
   - Search for `dockerdiscordcontrol`
   - Download latest version

2. **Create Container**
   - Go to "Container"
   - Click "Create"
   - Select downloaded image

3. **Configure Container**
   
   **Port Settings:**
   - Local Port: `8374`
   - Container Port: `8374`

   **Volume Settings:**
   ```
   /docker/dockerdiscordcontrol/config → /app/config
   /docker/dockerdiscordcontrol/logs → /app/logs
   /var/run/docker.sock → /var/run/docker.sock
   ```

   **Environment Variables:**
   ```
   FLASK_SECRET_KEY=[Generated key]
   DDC_ADMIN_PASSWORD=[Your password]
   ```

4. **Start Container**
   - Apply settings and start container
   - Access via `http://synology-ip:8374`

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `FLASK_SECRET_KEY` | Yes | None | 32-byte hex key for session security |
| `DDC_ADMIN_PASSWORD` | No | `admin` | Initial web UI password |
| `DOCKER_HOST` | No | `unix:///var/run/docker.sock` | Docker socket path |
| `DDC_DOCKER_CACHE_DURATION` | No | `75` | Cache TTL in seconds |
| `DDC_BACKGROUND_REFRESH_INTERVAL` | No | `30` | Background refresh interval |
| `DDC_TOGGLE_CACHE_DURATION` | No | `150` | Toggle operation cache TTL |
| `DDC_BATCH_SIZE` | No | `3` | Docker operation batch size |

## Post-Installation Setup

1. **Access Web UI**
   - Open browser to `http://your-server-ip:8374`
   - Login with username `admin` and password `admin` (default)

2. **Initial Configuration**
   - Change default password (if using default)
   - Enter Discord bot token
   - Enter Discord guild ID
   - Select containers to manage
   - Configure permissions

3. **Test Installation**
   - Save configuration
   - Restart container: `docker compose restart`
   - Test Discord bot functionality
   - Verify container controls work

## Upgrading

### Docker Compose
```bash
# Pull latest changes
git pull

# Rebuild and restart
docker compose up --build -d
```

### Standard Docker
```bash
# Pull latest image
docker pull ghcr.io/dockerdiscordcontrol/dockerdiscordcontrol:latest

# Stop and remove old container
docker stop ddc && docker rm ddc

# Start new container (use same run command as installation)
```

### Unraid
- Go to "Docker" tab
- Click container's icon → "Update Container"
- Confirm update when prompted

## Common Issues

### Permission Errors
- **Symptom**: Configuration not saving
- **Solution**: Fix file permissions
  ```bash
  docker exec ddc /app/scripts/fix_permissions.sh
  ```

### Port Conflicts
- **Symptom**: Port already in use
- **Solution**: Change host port in configuration
  ```yaml
  ports:
    - "9000:8374"  # Use port 9000 instead
  ```

### Docker Socket Access
- **Symptom**: Cannot connect to Docker
- **Solution**: Verify socket path and permissions
  ```bash
  # Check socket exists
  ls -la /var/run/docker.sock
  
  # Verify container has access
  docker exec ddc ls -la /var/run/docker.sock
  ```

## Next Steps

- [⚙️ Configuration Guide](Configuration) - Configure DDC settings
- [Troubleshooting](Troubleshooting) - Solve common problems  
- [🔒 Security Guide](Security) - Secure your installation 