#!/bin/bash

# Change to parent directory if script is run from scripts/ folder
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# If we're in the scripts directory, move up to the project root
if [[ "$SCRIPT_DIR" == *"/scripts" ]]; then
    cd "$PROJECT_ROOT"
    echo ">>> Changed working directory to project root: $(pwd)"
fi

# Colors for terminal output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Print header
echo -e "${GREEN}==========================================${NC}"
echo -e "${GREEN}DockerDiscordControl - Startup Script${NC}"
echo -e "${GREEN}==========================================${NC}"

# Check for .env file and prompt for secrets if needed
if [ -f ".env" ]; then
    echo -e "${GREEN}Using .env file for environment variables${NC}"
    source .env
else
    # No predictable fallback key here: with an empty FLASK_SECRET_KEY DDC generates a
    # random key once and keeps it in config/.flask_secret_key.
    echo -e "${YELLOW}No .env file found. DDC will generate a persistent secret key (config/.flask_secret_key).${NC}"
    echo -e "${YELLOW}For production use, create a .env file with secure values.${NC}"
fi

# DDC runs as a single process (run.py: Web UI + bot) inside its Docker image.
# The former "Python (direct)" mode of this script started bot.py and a gunicorn
# web server as two separate processes with a gunicorn_config.py that no longer
# exists, so it could not work; it now fails fast instead of pretending to work.
if ! command -v docker &> /dev/null; then
    echo -e "${RED}Docker not found.${NC}"
    echo -e "${RED}Running DDC directly with Python via this script is no longer supported.${NC}"
    echo -e "${YELLOW}Install Docker and run this script again, or use scripts/rebuild.sh${NC}"
    echo -e "${YELLOW}(builds the image and starts the container) / the published Docker image.${NC}"
    exit 1
fi
echo -e "${GREEN}Docker is available${NC}"

# Create required directories if they don't exist
echo -e "${GREEN}Creating required directories...${NC}"
mkdir -p config logs

echo -e "${GREEN}Starting with Docker...${NC}"

# Check if Docker Compose is available
if command -v docker-compose &> /dev/null; then
    COMPOSE_CMD="docker-compose"
elif docker compose version &> /dev/null; then
    COMPOSE_CMD="docker compose"
else
    echo -e "${RED}Docker Compose not found${NC}"
    echo -e "${YELLOW}Falling back to manual Docker commands...${NC}"
    COMPOSE_CMD=""
fi

if [ -n "$COMPOSE_CMD" ]; then
    # If docker-compose.yml exists, use it
    if [ -f "docker-compose.yml" ]; then
        echo -e "${GREEN}Using Docker Compose...${NC}"
        $COMPOSE_CMD up --build
    else
        echo -e "${RED}docker-compose.yml not found${NC}"
        echo -e "${YELLOW}Falling back to manual Docker commands...${NC}"
        COMPOSE_CMD=""
    fi
fi

# If Docker Compose failed or is not available, use direct Docker commands
if [ -z "$COMPOSE_CMD" ] || [ ! -f "docker-compose.yml" ]; then
    echo -e "${GREEN}Building Docker Image...${NC}"
    docker build -t dockerdiscordcontrol .

    echo -e "${GREEN}Starting Docker Container...${NC}"
    docker run -p 9374:9374 \
        -v $(pwd)/config:/app/config \
        -v $(pwd)/logs:/app/logs \
        -v /var/run/docker.sock:/var/run/docker.sock \
        -e FLASK_SECRET_KEY="${FLASK_SECRET_KEY}" \
        dockerdiscordcontrol
fi

echo -e "${GREEN}Done!${NC}"
