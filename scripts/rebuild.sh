#!/bin/bash

# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║                    🐳 Docker Discord Control - Rebuild Script               ║
# ║                                                                              ║
# ║  This script rebuilds the DDC container with security updates and           ║
# ║  optimized performance settings for Unraid systems.                         ║
# ║                                                                              ║
# ║  Author: DDC Team                                                            ║
# ║  Version: 2.0 (Enhanced with colors and error handling)                     ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

# 🎨 Colors for pretty output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
WHITE='\033[1;37m'
NC='\033[0m' # No Color

# 📁 Change to parent directory if script is run from scripts/ folder
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# If we're in the scripts directory, move up to the project root
if [[ "$SCRIPT_DIR" == *"/scripts" ]]; then
    cd "$PROJECT_ROOT"
    echo -e "${BLUE}📁 Changed working directory to project root: ${WHITE}$(pwd)${NC}"
fi

# Exits the script immediately if a command fails (except those with || true)
set -e

echo -e "${YELLOW}🛑 Stopping container ddc...${NC}"
if docker stop ddc 2>/dev/null; then
    echo -e "${GREEN}✅ Container stopped successfully${NC}"
else
    echo -e "${CYAN}ℹ️  Container was not running${NC}"
fi
sleep 1

echo -e "${YELLOW}🗑️  Removing container ddc...${NC}"
if docker rm ddc 2>/dev/null; then
    echo -e "${GREEN}✅ Container removed successfully${NC}"
else
    echo -e "${CYAN}ℹ️  Container did not exist${NC}"
fi
sleep 1

# 🧹 Clean up Python cache files
echo -e "${PURPLE}🧹 Removing __pycache__ directories...${NC}"
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
echo -e "${GREEN}✅ Cache directories cleaned${NC}"
sleep 1

# 🐳 Build Docker image
echo -e "${BLUE}🐳 Rebuilding OPTIMIZED Alpine image dockerdiscordcontrol (without cache)...${NC}"
echo -e "${CYAN}⏳ This may take a few minutes...${NC}"
if docker build --no-cache -f Dockerfile.alpine-optimized -t dockerdiscordcontrol .; then
    echo -e "${GREEN}✅ Docker image built successfully!${NC}"
    
    # 🔧 Post-Build: Repair optimized image (if needed)
    echo -e "${YELLOW}🔧 Verifying and optimizing image...${NC}"
    
    # Test if virtual environment works
    if docker run --rm dockerdiscordcontrol /opt/venv/bin/python -c "import sys; print('Python OK')" 2>/dev/null; then
        echo -e "${GREEN}✅ Virtual environment is working correctly${NC}"
    else
        echo -e "${YELLOW}⚠️  Virtual environment needs repair - applying fixes...${NC}"
        
        # Create temporary container to fix virtual environment
        TEMP_CONTAINER=$(docker run -d dockerdiscordcontrol sleep 3600)
        
        # Create virtual environment from scratch (since Docker build doesn't copy it correctly)
        echo -e "${CYAN}📦 Creating virtual environment from scratch...${NC}"
        docker exec $TEMP_CONTAINER python -m venv /opt/venv
        
        # Install all required packages
        echo -e "${CYAN}📦 Installing Python packages...${NC}"
        docker exec $TEMP_CONTAINER /opt/venv/bin/pip install --upgrade pip
        docker exec $TEMP_CONTAINER /opt/venv/bin/pip install py-cord==2.6.1 Flask==3.1.1 gunicorn==23.0.0 gevent PyYAML python-dotenv APScheduler pytz cryptography requests urllib3 aiohttp setuptools python-json-logger cachetools superlance Flask-HTTPAuth docker Werkzeug
        
        # Verify installation
        echo -e "${CYAN}✅ Verifying installation...${NC}"
        docker exec $TEMP_CONTAINER /opt/venv/bin/python -c "import discord; print('Discord: OK')"
        docker exec $TEMP_CONTAINER /opt/venv/bin/python -c "import flask; print('Flask: OK')"
        docker exec $TEMP_CONTAINER /opt/venv/bin/gunicorn --version
        
        # Fix supervisord.conf
        echo -e "${CYAN}⚙️  Configuring supervisor...${NC}"
        docker exec $TEMP_CONTAINER sh -c 'echo "[supervisord]
nodaemon=true
user=root
logfile=/app/logs/supervisord.log
logfile_maxbytes=5MB
logfile_backups=2
loglevel=info

[supervisorctl]
serverurl=unix:///tmp/supervisor.sock

[unix_http_server]
file=/tmp/supervisor.sock

[rpcinterface:supervisor]
supervisor.rpcinterface_factory = supervisor.rpcinterface:make_main_rpcinterface

[program:discordbot]
command=/opt/venv/bin/python /app/bot.py
directory=/app
autostart=true
autorestart=true
startretries=3
stopwaitsecs=10
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
user=root
environment=FLASK_SECRET_KEY=\"%(ENV_ENV_FLASK_SECRET_KEY)s\",DOCKER_SOCKET=\"/var/run/docker.sock\"

[program:webui]
command=/opt/venv/bin/gunicorn -c /app/gunicorn_config.py app.web_ui:create_app()
directory=/app
autostart=true
autorestart=true
startretries=3
stopwaitsecs=10
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
user=root
environment=FLASK_SECRET_KEY=\"%(ENV_ENV_FLASK_SECRET_KEY)s\",DOCKER_SOCKET=\"/var/run/docker.sock\"

[group:ddc]
programs=discordbot,webui
priority=999" > /etc/supervisor/conf.d/supervisord.conf'
        
        # Commit the fixed container as new image
        echo -e "${CYAN}💾 Saving optimized image...${NC}"
        docker commit $TEMP_CONTAINER dockerdiscordcontrol
        docker stop $TEMP_CONTAINER
        docker rm $TEMP_CONTAINER
        
        echo -e "${GREEN}✅ Post-build optimizations completed!${NC}"
    fi
else
    echo -e "${RED}❌ Docker build failed${NC}"
    exit 1
fi

sleep 1

# 🔑 Check for existing bot token
echo -e "${PURPLE}🔑 Checking for existing bot token...${NC}"
if [ -f "./config/bot_config.json" ]; then
    # Try to extract the token (without decrypting it)
    TOKEN_EXISTS=$(grep -c "bot_token" ./config/bot_config.json 2>/dev/null || echo "0")
    
    if [ "$TOKEN_EXISTS" -gt "0" ]; then
        echo -e "${GREEN}✅ Bot token found and configured${NC}"
    else
        echo -e "${YELLOW}⚠️  No bot token found in configuration. Please set it in the web UI.${NC}"
    fi
else
    echo -e "${CYAN}ℹ️  No configuration file found yet${NC}"
fi

# Set environment variable for restricted logging
export PYTHONWARNINGS="ignore"
export LOGGING_LEVEL="WARNING"

# 🔧 Environment configuration
if [ -f ".env" ]; then
    echo -e "${GREEN}✅ Using .env file for environment variables${NC}"
    source .env
else
    echo -e "${CYAN}ℹ️  No .env file found${NC}"
fi

if [ -z "$FLASK_SECRET_KEY" ]; then
    echo -e "${YELLOW}⚠️  FLASK_SECRET_KEY not set. Using a temporary key for development purposes only.${NC}"
    echo -e "${CYAN}ℹ️  For production, create a .env file with a secure FLASK_SECRET_KEY value.${NC}"
    FLASK_SECRET_KEY="temporary-dev-key-$(date +%s)"
fi

# 🚀 Start the container
echo -e "${GREEN}🚀 Starting new container ddc...${NC}"
docker run -d \
  --name ddc \
  -p 8374:9374 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v ./config:/app/config \
  -v ./logs:/app/logs \
  -e FLASK_SECRET_KEY="${FLASK_SECRET_KEY}" \
  -e ENV_FLASK_SECRET_KEY="${FLASK_SECRET_KEY}" \
  -e PYTHONWARNINGS="ignore" \
  -e LOGGING_LEVEL="INFO" \
  -e DDC_CACHE_TTL="60" \
  -e DDC_DOCKER_CACHE_DURATION="120" \
  -e DDC_DISCORD_SKIP_TOKEN_LOCK="true" \
  --restart unless-stopped \
  --log-driver json-file \
  --log-opt max-size=10m \
  --log-opt max-file=3 \
  --cpus 2.0 \
  --memory 512M \
  --memory-reservation 128M \
  dockerdiscordcontrol 2>/dev/null

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ Container started successfully!${NC}"
    sleep 1
    echo -e "${BLUE}📋 Script finished! Check the logs with: ${WHITE}docker logs ddc -f${NC}"
    echo ""
    echo -e "${PURPLE}🌐 Web UI available at:${NC}"
    
    # Get local IP address
    LOCAL_IP=$(hostname -I | awk '{print $1}' 2>/dev/null || ip route get 1 | awk '{print $7}' 2>/dev/null || echo "localhost")
    
    echo -e "${WHITE}   📍 Local:    ${CYAN}http://localhost:8374${NC}"
    if [ "$LOCAL_IP" != "localhost" ] && [ -n "$LOCAL_IP" ]; then
        echo -e "${WHITE}   🌍 Network:  ${CYAN}http://${LOCAL_IP}:8374${NC}"
    fi
    echo ""
else
    echo -e "${RED}❌ Failed to start container${NC}"
    exit 1
fi
