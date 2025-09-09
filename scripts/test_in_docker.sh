#!/bin/bash
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Simple Docker Test Runner                      #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${YELLOW}=== DDC Simple Docker Test ===${NC}"

# Find container
CONTAINER=$(docker ps --format "{{.Names}}" | grep -i "dockerdiscordcontrol\|ddc" | head -1)

if [[ -z "$CONTAINER" ]]; then
    echo -e "${RED}✗ No DDC container found${NC}"
    echo "Available containers:"
    docker ps --format "table {{.Names}}\t{{.Status}}"
    exit 1
fi

echo -e "${GREEN}✓ Found container: $CONTAINER${NC}"

# Test 1: Check Python
echo -e "\n${BLUE}Test 1: Python Environment${NC}"
docker exec "$CONTAINER" python3 --version || {
    echo -e "${RED}✗ Python not available${NC}"
    exit 1
}

# Test 2: Import test (no pytest needed)
echo -e "\n${BLUE}Test 2: DDC Service Imports${NC}"
docker exec "$CONTAINER" python3 -c "
import sys
import os

# Add app directory to path
sys.path.insert(0, '/app')
os.chdir('/app')

print('Testing imports...')

try:
    # Test core service imports
    print('Testing core services...')
    
    from services.donation.donation_management_service import DonationManagementService, DonationStats
    print('✓ DonationManagementService imported')
    
    from services.config.config_service import get_config_service
    print('✓ ConfigService imported')
    
    from services.mech.mech_service import get_mech_service
    print('✓ MechService imported')
    
    # Test infrastructure services
    print('Testing infrastructure services...')
    
    from services.infrastructure.action_log_service import get_action_log_service
    print('✓ ActionLogService imported')
    
    from services.infrastructure.container_info_service import ContainerInfoService
    print('✓ ContainerInfoService imported')
    
    # Try Docker service (may not exist yet)
    try:
        from services.docker_service.docker_service import DockerService
        print('✓ DockerService imported')
    except ImportError:
        print('ℹ DockerService not available (expected)')
    
    # Test service creation
    print('Testing service initialization...')
    
    donation_service = DonationManagementService()
    print('✓ DonationManagementService initialized')
    
    config_service = get_config_service()
    print('✓ ConfigService initialized')
    
    container_info_service = ContainerInfoService()
    print('✓ ContainerInfoService initialized')
    
    # Test data classes
    stats = DonationStats(100.0, 5, 20.0)
    print(f'✓ DonationStats created: {stats.total_power} power, {stats.total_donations} donations')
    
    # Test from_data method
    test_donations = [{'amount': 10}, {'amount': 20}, {'amount': 30}]
    stats2 = DonationStats.from_data(test_donations, 60.0)
    print(f'✓ Stats from data: avg={stats2.average_donation:.1f}')
    
    print('\n✅ All core services working!')
    
except Exception as e:
    print(f'✗ Error: {e}')
    import traceback
    traceback.print_exc()
    sys.exit(1)
"

if [[ $? -eq 0 ]]; then
    echo -e "\n${GREEN}✅ Basic tests passed successfully!${NC}"
else
    echo -e "\n${RED}✗ Tests failed${NC}"
    exit 1
fi

# Test 3: Check if pytest is available (optional)
echo -e "\n${BLUE}Test 3: Pytest Availability${NC}"
if docker exec "$CONTAINER" python3 -c "import pytest; print(f'✓ pytest {pytest.__version__} available')" 2>/dev/null; then
    echo -e "${GREEN}Pytest is available - you can run full test suite${NC}"
    echo ""
    echo "Run full tests with:"
    echo "  docker exec $CONTAINER python3 -m pytest tests/unit/ -v"
else
    echo -e "${YELLOW}ℹ Pytest not installed (optional)${NC}"
    echo "Tests can still run using basic Python"
fi

# Summary
echo -e "\n${YELLOW}=== Summary ===${NC}"
echo -e "${GREEN}✓ DDC container is running${NC}"
echo -e "${GREEN}✓ Python is available${NC}"  
echo -e "${GREEN}✓ Services can be imported${NC}"
echo -e "${GREEN}✓ Basic functionality works${NC}"

echo ""
echo "Manual test commands:"
echo "  docker exec $CONTAINER python3 -c \"from services.donation.donation_management_service import *; print('OK')\""
echo "  docker exec -it $CONTAINER /bin/bash  # Enter container"

echo -e "\n${GREEN}✅ Test completed successfully!${NC}"