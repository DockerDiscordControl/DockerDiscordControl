#!/usr/bin/env python3
"""
Compare Docker Pool performance vs. Direct Docker API calls
"""

import sys
import time
import asyncio
import docker
from pathlib import Path

# Add project root to path
sys.path.append('/Volumes/appdata/dockerdiscordcontrol')

async def test_direct_docker():
    """Test direct Docker API calls (old way)."""
    print("🔧 Testing DIRECT Docker API (old way)")
    print("-" * 50)
    
    container_name = "ProjectZomboid"
    
    try:
        start_time = time.time()
        
        # Direct connection (like before)
        print("Step 1: Creating direct Docker client...")
        client_start = time.time()
        client = docker.from_env()
        client_time = (time.time() - client_start) * 1000
        print(f"✅ Direct client created in {client_time:.1f}ms")
        
        # Ping test
        print("Step 2: Testing direct ping...")
        ping_start = time.time()
        client.ping()
        ping_time = (time.time() - ping_start) * 1000
        print(f"✅ Direct ping in {ping_time:.1f}ms")
        
        # Get container
        print("Step 3: Direct containers.get()...")
        get_start = time.time()
        container = client.containers.get(container_name)
        get_time = (time.time() - get_start) * 1000
        print(f"✅ Direct containers.get() in {get_time:.1f}ms")
        
        # Get stats
        print("Step 4: Direct container.stats()...")
        stats_start = time.time()
        stats = container.stats(stream=False)
        stats_time = (time.time() - stats_start) * 1000
        print(f"✅ Direct container.stats() in {stats_time:.1f}ms")
        
        client.close()
        
        total_time = (time.time() - start_time) * 1000
        print(f"\n🎯 DIRECT TOTAL: {total_time:.1f}ms")
        
        return total_time
        
    except Exception as e:
        total_time = (time.time() - start_time) * 1000
        print(f"❌ Direct failed after {total_time:.1f}ms: {e}")
        return total_time

async def test_pool_docker():
    """Test Docker Pool API calls (new way)."""
    print("\n🔧 Testing POOL Docker API (new way)")  
    print("-" * 50)
    
    container_name = "ProjectZomboid"
    
    try:
        from services.docker_service.docker_utils import get_docker_client_async
        
        start_time = time.time()
        
        print("Step 1: Getting client from pool...")
        pool_start = time.time()
        async with get_docker_client_async(operation='stats', container_name=container_name) as client:
            pool_time = (time.time() - pool_start) * 1000
            print(f"✅ Pool client acquired in {pool_time:.1f}ms")
            
            # Ping test  
            print("Step 2: Testing pool ping...")
            ping_start = time.time()
            await asyncio.to_thread(client.ping)
            ping_time = (time.time() - ping_start) * 1000
            print(f"✅ Pool ping in {ping_time:.1f}ms")
            
            # Get container
            print("Step 3: Pool containers.get()...")
            get_start = time.time()
            container = await asyncio.to_thread(client.containers.get, container_name)
            get_time = (time.time() - get_start) * 1000
            print(f"✅ Pool containers.get() in {get_time:.1f}ms")
            
            # Get stats
            print("Step 4: Pool container.stats()...")
            stats_start = time.time()
            stats = await asyncio.to_thread(container.stats, stream=False)
            stats_time = (time.time() - stats_start) * 1000
            print(f"✅ Pool container.stats() in {stats_time:.1f}ms")
        
        total_time = (time.time() - start_time) * 1000
        print(f"\n🎯 POOL TOTAL: {total_time:.1f}ms")
        
        return total_time
        
    except Exception as e:
        total_time = (time.time() - start_time) * 1000
        print(f"❌ Pool failed after {total_time:.1f}ms: {e}")
        return total_time

async def main():
    """Compare both approaches."""
    print("🔍 DOCKER PERFORMANCE COMPARISON")
    print("=" * 60)
    
    # Test both approaches
    direct_time = await test_direct_docker()
    pool_time = await test_pool_docker()
    
    print("\n📊 COMPARISON RESULTS:")
    print("=" * 30)
    print(f"Direct API: {direct_time:.1f}ms")
    print(f"Pool API:   {pool_time:.1f}ms")
    
    if pool_time > direct_time:
        overhead = pool_time - direct_time
        overhead_percent = (overhead / direct_time) * 100
        print(f"Pool Overhead: +{overhead:.1f}ms (+{overhead_percent:.1f}%)")
        
        if overhead > 1000:  # More than 1 second overhead
            print("⚠️  SIGNIFICANT POOL OVERHEAD DETECTED!")
            print("The pool system may be causing the delays.")
        else:
            print("✅ Pool overhead is reasonable.")
    else:
        print("✅ Pool is actually faster!")

if __name__ == "__main__":
    asyncio.run(main())