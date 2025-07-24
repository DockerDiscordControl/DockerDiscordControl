#!/bin/bash
# =============================================================================
# DDC Ultra-Optimized Alpine Build Script
# Builds the optimized image and compares performance metrics
# =============================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
IMAGE_NAME="ddc-optimized"
TAG="alpine-ultra"
DOCKERFILE="../Dockerfile.alpine-optimized"

echo -e "${BLUE}=== DDC Ultra-Optimized Alpine Build ===${NC}"
echo "Building optimized DDC image with maximum performance..."

# Check if original image exists for comparison
ORIGINAL_EXISTS=false
if docker images | grep -q "ddc.*alpine"; then
    ORIGINAL_EXISTS=true
    ORIGINAL_IMAGE=$(docker images --format "table {{.Repository}}:{{.Tag}}" | grep ddc | grep alpine | head -1)
    echo -e "${YELLOW}Found existing DDC Alpine image: ${ORIGINAL_IMAGE}${NC}"
fi

# Build the optimized image
echo -e "\n${BLUE}Building optimized image...${NC}"
BUILD_START=$(date +%s)

docker build \
    --file "${DOCKERFILE}" \
    --tag "${IMAGE_NAME}:${TAG}" \
    --progress=plain \
    --no-cache \
    .. || {
    echo -e "${RED}Build failed!${NC}"
    exit 1
}

BUILD_END=$(date +%s)
BUILD_TIME=$((BUILD_END - BUILD_START))

echo -e "${GREEN}✅ Build completed in ${BUILD_TIME} seconds${NC}"

# Get image information
echo -e "\n${BLUE}=== Image Analysis ===${NC}"

# New image stats
NEW_SIZE=$(docker images "${IMAGE_NAME}:${TAG}" --format "{{.Size}}")
NEW_SIZE_BYTES=$(docker inspect "${IMAGE_NAME}:${TAG}" --format='{{.Size}}')

echo -e "${GREEN}Optimized Image Stats:${NC}"
echo "  Size: ${NEW_SIZE}"
echo "  Layers: $(docker history "${IMAGE_NAME}:${TAG}" --quiet | wc -l)"

# Compare with original if it exists
if [ "$ORIGINAL_EXISTS" = true ]; then
    ORIGINAL_SIZE=$(docker images "${ORIGINAL_IMAGE}" --format "{{.Size}}")
    ORIGINAL_SIZE_BYTES=$(docker inspect "${ORIGINAL_IMAGE}" --format='{{.Size}}')
    
    echo -e "\n${YELLOW}Original Image Stats:${NC}"
    echo "  Size: ${ORIGINAL_SIZE}"
    echo "  Layers: $(docker history "${ORIGINAL_IMAGE}" --quiet | wc -l)"
    
    # Calculate size reduction
    if [ "$ORIGINAL_SIZE_BYTES" -gt 0 ] && [ "$NEW_SIZE_BYTES" -gt 0 ]; then
        REDUCTION=$(echo "scale=1; (($ORIGINAL_SIZE_BYTES - $NEW_SIZE_BYTES) * 100) / $ORIGINAL_SIZE_BYTES" | bc -l)
        echo -e "\n${GREEN}📉 Size Reduction: ${REDUCTION}%${NC}"
    fi
fi

# Test the optimized image
echo -e "\n${BLUE}=== Performance Test ===${NC}"
echo "Starting optimized container for testing..."

# Stop any existing test containers
docker stop ddc-test-optimized 2>/dev/null || true
docker rm ddc-test-optimized 2>/dev/null || true

# Start test container
docker run -d \
    --name ddc-test-optimized \
    --publish 9374:9374 \
    --volume /var/run/docker.sock:/var/run/docker.sock \
    --env DDC_DOCKER_CACHE_DURATION=45 \
    --env DDC_BACKGROUND_REFRESH_INTERVAL=30 \
    --env GUNICORN_WORKERS=1 \
    "${IMAGE_NAME}:${TAG}"

# Wait for startup
echo "Waiting for container to start..."
sleep 10

# Test startup time
STARTUP_START=$(date +%s)
while ! curl -s http://localhost:9374/ >/dev/null 2>&1; do
    sleep 1
    CURRENT=$(date +%s)
    if [ $((CURRENT - STARTUP_START)) -gt 60 ]; then
        echo -e "${RED}❌ Container failed to start within 60 seconds${NC}"
        docker logs ddc-test-optimized
        docker stop ddc-test-optimized
        docker rm ddc-test-optimized
        exit 1
    fi
done

STARTUP_END=$(date +%s)
STARTUP_TIME=$((STARTUP_END - STARTUP_START))

echo -e "${GREEN}✅ Container started in ${STARTUP_TIME} seconds${NC}"

# Get container stats
echo -e "\n${BLUE}=== Runtime Performance ===${NC}"
STATS=$(docker stats ddc-test-optimized --no-stream --format "table {{.MemUsage}}\t{{.CPUPerc}}")
echo "Memory & CPU Usage:"
echo "$STATS"

# Test Web UI response
echo -e "\n${BLUE}Testing Web UI performance...${NC}"
RESPONSE_TIME=$(curl -o /dev/null -s -w '%{time_total}' http://localhost:9374/)
echo -e "${GREEN}Web UI Response Time: ${RESPONSE_TIME}s${NC}"

# Test performance endpoint
if curl -s http://localhost:9374/performance_stats >/dev/null 2>&1; then
    echo -e "${GREEN}✅ Performance monitoring endpoint accessible${NC}"
else
    echo -e "${YELLOW}⚠️  Performance monitoring endpoint requires authentication${NC}"
fi

# Cleanup
echo -e "\n${BLUE}Cleaning up test container...${NC}"
docker stop ddc-test-optimized
docker rm ddc-test-optimized

# Summary
echo -e "\n${GREEN}=== OPTIMIZATION SUMMARY ===${NC}"
echo "✅ Ultra-optimized DDC Alpine image built successfully"
echo "📦 Image: ${IMAGE_NAME}:${TAG}"
echo "🏗️  Build Time: ${BUILD_TIME}s"
echo "🚀 Startup Time: ${STARTUP_TIME}s"
echo "📊 Response Time: ${RESPONSE_TIME}s"
echo "💾 Image Size: ${NEW_SIZE}"

if [ "$ORIGINAL_EXISTS" = true ] && [ -n "$REDUCTION" ]; then
    echo "📉 Size Reduction: ${REDUCTION}%"
fi

echo -e "\n${BLUE}=== OPTIMIZATIONS INCLUDED ===${NC}"
echo "• Removed testing dependencies (pytest, etc.)"
echo "• Compiled Python bytecode for faster startup"
echo "• Removed documentation and man pages"
echo "• Optimized supervisor configuration"
echo "• Minimal Gunicorn worker configuration"
echo "• Pre-configured performance environment variables"
echo "• Cleaned up Python package caches"
echo "• Removed unnecessary build artifacts"

echo -e "\n${BLUE}=== USAGE ===${NC}"
echo "To use the optimized image:"
echo "  docker run -d \\"
echo "    --name ddc-optimized \\"
echo "    -p 9374:9374 \\"
echo "    -v /var/run/docker.sock:/var/run/docker.sock \\"
echo "    ${IMAGE_NAME}:${TAG}"

echo -e "\n${GREEN}🎉 Optimization complete!${NC}"