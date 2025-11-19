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
    echo -e "${YELLOW}No .env file found. Using generated secret key.${NC}"
    echo -e "${YELLOW}For production use, create a .env file with secure values.${NC}"
    FLASK_SECRET_KEY="dev-only-$(date +%s)"
fi

# Check for Python availability
PYTHON_CMD=""
if command -v python3 &> /dev/null; then
    echo -e "${GREEN}Python 3 found (python3 command)${NC}"
    PYTHON_CMD="python3"
elif command -v python &> /dev/null; then
    echo -e "${YELLOW}Python command found, checking version...${NC}"
    # Check if python is Python 3+
    PYTHON_VERSION=$(python --version 2>&1 | cut -d " " -f 2 | cut -d "." -f 1)
    if [ "$PYTHON_VERSION" -ge "3" ]; then
        echo -e "${GREEN}Python version is $PYTHON_VERSION (Python 3+)${NC}"
        PYTHON_CMD="python"
    else
        echo -e "${RED}Python version is $PYTHON_VERSION, but Python 3+ is required${NC}"
        echo -e "${YELLOW}Trying Docker instead...${NC}"
    fi
else
    echo -e "${RED}Python3 not found, trying Docker...${NC}"
fi

# Check for Docker availability
DOCKER_AVAILABLE=false
if command -v docker &> /dev/null; then
    echo -e "${GREEN}Docker is available${NC}"
    DOCKER_AVAILABLE=true
else
    echo -e "${RED}Docker not found${NC}"
    if [ -z "$PYTHON_CMD" ]; then
        echo -e "${RED}Neither Python 3+ nor Docker is available. Please install one of them.${NC}"
        exit 1
    fi
fi

# Create required directories if they don't exist
echo -e "${GREEN}Creating required directories...${NC}"
mkdir -p config logs app/logs

# Ask user for preferred method if both are available
METHOD=""
if [ -n "$PYTHON_CMD" ] && [ "$DOCKER_AVAILABLE" = true ]; then
    echo -e "${YELLOW}Both Python and Docker are available. Which method do you prefer?${NC}"
    echo "1) Python (direct)"
    echo "2) Docker (containerized)"
    read -p "Choice (1/2): " choice
    case $choice in
        1) METHOD="python" ;;
        2) METHOD="docker" ;;
        *) echo -e "${YELLOW}Invalid selection, default is Python${NC}"; METHOD="python" ;;
    esac
elif [ -n "$PYTHON_CMD" ]; then
    METHOD="python"
elif [ "$DOCKER_AVAILABLE" = true ]; then
    METHOD="docker"
else
    echo -e "${RED}No valid method found to start the application${NC}"
    exit 1
fi

# Run the application with the selected method
if [ "$METHOD" = "python" ]; then
    echo -e "${GREEN}Starting with Python...${NC}"
    
    # Check for virtual environment
    if [ ! -d "venv" ]; then
        echo -e "${YELLOW}Creating virtual environment...${NC}"
        $PYTHON_CMD -m venv venv
    fi
    
    # Activate virtual environment
    if [ -f "venv/bin/activate" ]; then
        echo -e "${GREEN}Activating virtual environment...${NC}"
        source venv/bin/activate
    else
        echo -e "${RED}Could not create virtual environment${NC}"
        exit 1
    fi
    
    # Install dependencies
    echo -e "${GREEN}Installing dependencies...${NC}"
    pip install -r requirements.txt
    
    # Start the application
    echo -e "${GREEN}Starting Discord Bot...${NC}"
    $PYTHON_CMD bot.py &
    
    echo -e "${GREEN}Starting Web UI...${NC}"
    FLASK_APP=app.web_ui FLASK_SECRET_KEY="${FLASK_SECRET_KEY}" $PYTHON_CMD -m gunicorn --bind 0.0.0.0:9374 --worker-class gevent "app.web_ui:create_app()" -c gunicorn_config.py
    
elif [ "$METHOD" = "docker" ]; then
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
fi

echo -e "${GREEN}Done!${NC}" 