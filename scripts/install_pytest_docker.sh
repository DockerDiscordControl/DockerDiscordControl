#!/bin/bash
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Install Pytest in Docker Container             #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${YELLOW}=== Installing Pytest in DDC Container ===${NC}"

# Find container
CONTAINER=$(docker ps --format "{{.Names}}" | grep -i "dockerdiscordcontrol\|ddc" | head -1)

if [[ -z "$CONTAINER" ]]; then
    echo -e "${RED}✗ No DDC container found${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Found container: $CONTAINER${NC}"

# Try different installation methods
echo -e "\n${BLUE}Method 1: Installing with --user flag...${NC}"
if docker exec "$CONTAINER" python3 -m pip install --user pytest pytest-mock pytest-asyncio 2>/dev/null; then
    echo -e "${GREEN}✓ Installed with --user flag${NC}"
else
    echo -e "${YELLOW}ℹ --user installation failed, trying alternative...${NC}"
    
    echo -e "\n${BLUE}Method 2: Installing to .local directory...${NC}"
    if docker exec "$CONTAINER" /bin/bash -c "
        mkdir -p ~/.local
        export PYTHONUSERBASE=~/.local
        export PATH=~/.local/bin:\$PATH
        python3 -m pip install --user pytest pytest-mock pytest-asyncio
    " 2>/dev/null; then
        echo -e "${GREEN}✓ Installed to .local directory${NC}"
    else
        echo -e "${YELLOW}ℹ .local installation failed, trying root...${NC}"
        
        echo -e "\n${BLUE}Method 3: Installing as root user...${NC}"
        if docker exec --user root "$CONTAINER" python3 -m pip install pytest pytest-mock pytest-asyncio 2>/dev/null; then
            echo -e "${GREEN}✓ Installed as root${NC}"
        else
            echo -e "${RED}✗ All installation methods failed${NC}"
            echo -e "${YELLOW}You may need to rebuild the container with pytest included${NC}"
            exit 1
        fi
    fi
fi

# Test if pytest works
echo -e "\n${BLUE}Testing pytest installation...${NC}"
if docker exec "$CONTAINER" python3 -c "import pytest; print(f'✓ pytest {pytest.__version__} is working')" 2>/dev/null; then
    echo -e "${GREEN}✓ Pytest is working!${NC}"
    
    echo -e "\n${GREEN}✅ Installation successful!${NC}"
    echo ""
    echo "You can now run tests with:"
    echo "  docker exec $CONTAINER python3 -m pytest tests/unit/ -v"
    echo "  docker exec $CONTAINER python3 -m pytest --help"
else
    echo -e "${YELLOW}ℹ Pytest installed but may need PATH adjustment${NC}"
    echo ""
    echo "Try running with full path:"
    echo "  docker exec $CONTAINER ~/.local/bin/pytest tests/unit/ -v"
fi