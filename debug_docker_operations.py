#!/usr/bin/env python3
"""
Debug Docker operations step by step to find where the delay is happening.
"""

import sys
import time
import asyncio
import logging
from pathlib import Path

# Add project root to path
sys.path.append('/Volumes/appdata/dockerdiscordcontrol')

# Set debug logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger('docker_debug')

async def test_single_operation():
    """Test a single Docker operation with detailed timing."""
    print("🔍 Docker Operation Debug - Single Container Test")
    print("=" * 60)
    
    container_name = "ProjectZomboid"  # Use the failing container
    
    try:
        from services.docker_service.docker_utils import get_docker_client_async, get_smart_timeout
        
        print(f"Testing container: {container_name}")
        operation_timeout = get_smart_timeout('info', container_name)
        print(f"Operation timeout: {operation_timeout}s")
        print()
        
        print("Step 1: Getting Docker client from pool...")
        start_time = time.time()
        
        async with get_docker_client_async(operation='info', container_name=container_name) as client:
            pool_time = (time.time() - start_time) * 1000
            print(f"✅ Got client from pool in {pool_time:.1f}ms")
            
            print("Step 2: Testing client.ping()...")
            ping_start = time.time()
            try:
                await asyncio.to_thread(client.ping)
                ping_time = (time.time() - ping_start) * 1000
                print(f"✅ Docker ping successful in {ping_time:.1f}ms")
            except Exception as e:
                print(f"❌ Docker ping failed: {e}")
                return
            
            print("Step 3: Testing client.containers.get()...")
            get_start = time.time()
            try:
                container = await asyncio.wait_for(
                    asyncio.to_thread(client.containers.get, container_name),
                    timeout=operation_timeout
                )
                get_time = (time.time() - get_start) * 1000
                print(f"✅ containers.get() successful in {get_time:.1f}ms")
            except asyncio.TimeoutError:
                get_time = (time.time() - get_start) * 1000
                print(f"❌ containers.get() TIMEOUT after {get_time:.1f}ms (limit was {operation_timeout}s)")
                return
            except Exception as e:
                print(f"❌ containers.get() failed: {e}")
                return
        
        total_time = (time.time() - start_time) * 1000
        print(f"\n🎯 TOTAL TIME: {total_time:.1f}ms")
        print("✅ Operation completed successfully!")
        
    except Exception as e:
        total_time = (time.time() - start_time) * 1000
        print(f"❌ FAILED after {total_time:.1f}ms: {e}")
        import traceback
        traceback.print_exc()

async def test_pool_stats():
    """Test the pool status during operation."""
    print("\n🔍 Docker Pool Status Check")
    print("=" * 40)
    
    try:
        from services.docker_service.docker_client_pool import get_docker_pool
        pool = get_docker_pool()
        
        for i in range(5):
            stats = pool.get_queue_stats()
            print(f"[{i+1}] Queue: {stats['current_queue_size']}, "
                  f"Available: {stats['available_clients']}, "
                  f"In Use: {stats['clients_in_use']}, "
                  f"Total Requests: {stats['total_requests']}, "
                  f"Timeouts: {stats['timeouts']}")
            await asyncio.sleep(1)
            
    except Exception as e:
        print(f"❌ Pool stats failed: {e}")

async def main():
    """Main debug function."""
    await test_pool_stats()
    await test_single_operation()

if __name__ == "__main__":
    asyncio.run(main())