#!/bin/bash
echo "Checking bot process..."
docker exec dockerdiscordcontrol /bin/sh -c "cd /app && timeout 5 strace -p 27 2>&1 | head -50"
