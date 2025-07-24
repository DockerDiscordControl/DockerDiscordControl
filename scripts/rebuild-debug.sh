#!/bin/bash

# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║                🐳 Docker Discord Control - Debug Rebuild Script             ║
# ║                                                                              ║
# ║  Enhanced rebuild script with detailed error reporting and debug output     ║
# ║  Use this when the regular rebuild.sh fails                                 ║
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

# Function for error handling
handle_error() {
    echo -e "${RED}❌ Error occurred in: $1${NC}"
    echo -e "${YELLOW}🔍 Debug Info:${NC}"
    echo -e "${CYAN}   Docker version: $(docker --version)${NC}"
    echo -e "${CYAN}   Available space: $(df -h . | tail -1 | awk '{print $4}')${NC}"
    echo -e "${CYAN}   Current user: $(whoami)${NC}"
    echo -e "${CYAN}   Working directory: $(pwd)${NC}"
    exit 1
}

echo -e "${PURPLE}🔍 Pre-build checks...${NC}"

# Check Docker
if ! command -v docker &> /dev/null; then
    echo -e "${RED}❌ Docker is not installed or not in PATH${NC}"
    exit 1
fi
echo -e "${GREEN}✅ Docker found: $(docker --version)${NC}"

# Check available space
AVAILABLE_SPACE=$(df . | tail -1 | awk '{print $4}')
if [ "$AVAILABLE_SPACE" -lt 1000000 ]; then  # Less than 1GB
    echo -e "${YELLOW}⚠️  Low disk space: $(df -h . | tail -1 | awk '{print $4}') available${NC}"
fi

# Check Dockerfile
if [ ! -f "Dockerfile" ]; then
    echo -e "${RED}❌ Dockerfile not found in current directory${NC}"
    exit 1
fi
echo -e "${GREEN}✅ Dockerfile found${NC}"

# Check requirements.txt
if [ ! -f "requirements.txt" ]; then
    echo -e "${RED}❌ requirements.txt not found${NC}"
    exit 1
fi
echo -e "${GREEN}✅ requirements.txt found${NC}"

echo -e "${YELLOW}🛑 Stopping container ddc...${NC}"
if docker stop ddc 2>/dev/null; then
    echo -e "${GREEN}✅ Container stopped successfully${NC}"
else
    echo -e "${CYAN}ℹ️  Container was not running${NC}"
fi

echo -e "${YELLOW}🗑️  Removing container ddc...${NC}"
if docker rm ddc 2>/dev/null; then
    echo -e "${GREEN}✅ Container removed successfully${NC}"
else
    echo -e "${CYAN}ℹ️  Container did not exist${NC}"
fi

# 🧹 Clean up Python cache files
echo -e "${PURPLE}🧹 Removing __pycache__ directories...${NC}"
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
echo -e "${GREEN}✅ Cache directories cleaned${NC}"

# Clean up Docker build cache
echo -e "${PURPLE}🧹 Cleaning Docker build cache...${NC}"
docker builder prune -f &>/dev/null || true
echo -e "${GREEN}✅ Docker build cache cleaned${NC}"

# 🐳 Build Docker image with FULL error output
echo -e "${BLUE}🐳 Rebuilding Alpine image dockerdiscordcontrol (without cache)...${NC}"
echo -e "${CYAN}⏳ This may take a few minutes...${NC}"
echo -e "${YELLOW}🔍 Build output (showing all details):${NC}"
echo -e "${WHITE}===========================================${NC}"

# Build with full error output and timing
START_TIME=$(date +%s)
if docker build --no-cache --progress=plain -t dockerdiscordcontrol .; then
    END_TIME=$(date +%s)
    BUILD_TIME=$((END_TIME - START_TIME))
    echo -e "${WHITE}===========================================${NC}"
    echo -e "${GREEN}✅ Docker image built successfully in ${BUILD_TIME}s!${NC}"
else
    echo -e "${WHITE}===========================================${NC}"
    echo -e "${RED}❌ Docker build failed${NC}"
    handle_error "docker build"
fi

# Verify the image was created
if docker images | grep -q "dockerdiscordcontrol"; then
    IMAGE_SIZE=$(docker images dockerdiscordcontrol --format "table {{.Size}}" | tail -n +2)
    echo -e "${GREEN}✅ Image created successfully (Size: ${IMAGE_SIZE})${NC}"
else
    echo -e "${RED}❌ Image was not created properly${NC}"
    handle_error "image verification"
fi

# 🔑 Check for existing bot token
echo -e "${PURPLE}🔑 Checking for existing bot token...${NC}"
if [ -f "./config/bot_config.json" ]; then
    TOKEN_EXISTS=$(grep -c "bot_token" ./config/bot_config.json 2>/dev/null || echo "0")
    
    if [ "$TOKEN_EXISTS" -gt "0" ]; then
        echo -e "${GREEN}✅ Bot token found and configured${NC}"
    else
        echo -e "${YELLOW}⚠️  No bot token found in configuration. Please set it in the web UI.${NC}"
    fi
else
    echo -e "${CYAN}ℹ️  No configuration file found yet${NC}"
fi

# Environment configuration
if [ -f ".env" ]; then
    echo -e "${GREEN}✅ Using .env file for environment variables${NC}"
    source .env
else
    echo -e "${CYAN}ℹ️  No .env file found${NC}"
fi

if [ -z "$FLASK_SECRET_KEY" ]; then
    echo -e "${YELLOW}⚠️  FLASK_SECRET_KEY not set. Using a temporary key for development purposes only.${NC}"
    FLASK_SECRET_KEY="temporary-dev-key-$(date +%s)"
fi

# 🚀 Start the container with error handling
echo -e "${GREEN}🚀 Starting new container ddc...${NC}"

CONTAINER_START=$(docker run -d \
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
  dockerdiscordcontrol 2>&1)

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ Container started successfully!${NC}"
    
    # Wait a moment and check if container is still running
    sleep 3
    if docker ps | grep -q "ddc"; then
        echo -e "${GREEN}✅ Container is running properly${NC}"
    else
        echo -e "${RED}❌ Container started but stopped immediately${NC}"
        echo -e "${YELLOW}🔍 Container logs:${NC}"
        docker logs ddc
        handle_error "container startup"
    fi
    
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
    echo -e "${YELLOW}🔍 Error details: ${CONTAINER_START}${NC}"
    handle_error "container startup"
fi 