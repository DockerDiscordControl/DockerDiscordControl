#!/usr/bin/env python3
"""
Debug script to check Docker queue statistics while the app is running.
"""

import sys
import time
import asyncio
from pathlib import Path

# Add project root to path
sys.path.append('/Volumes/appdata/dockerdiscordcontrol')

async def main():
    print("🔍 Docker Queue Statistics Debug")
    print("=" * 50)
    
    try:
        from services.docker_service.docker_utils import USE_CONNECTION_POOL
        from services.docker_service.docker_client_pool import get_docker_pool
        
        if not USE_CONNECTION_POOL:
            print("❌ Connection pool not available")
            return
        
        pool = get_docker_pool()
        
        for i in range(10):  # Check 10 times over 20 seconds
            stats = pool.get_queue_stats()
            timestamp = time.strftime('%H:%M:%S')
            
            print(f"\n[{timestamp}] Queue Status:")
            print(f"  📊 Current queue size: {stats['current_queue_size']}")
            print(f"  🔗 Available clients: {stats['available_clients']}")
            print(f"  🏃 Clients in use: {stats['clients_in_use']}")
            print(f"  📈 Max connections: {stats['max_connections']}")
            print(f"  📋 Total requests: {stats['total_requests']}")
            print(f"  ⏱️  Average wait: {stats['average_wait_time']:.3f}s")
            print(f"  ⏰ Timeouts: {stats['timeouts']}")
            print(f"  📏 Max queue size seen: {stats['max_queue_size']}")
            
            # Analysis
            utilization = (stats['clients_in_use'] / stats['max_connections']) * 100
            print(f"  🎯 Pool utilization: {utilization:.1f}%")
            
            if stats['current_queue_size'] > 0:
                print(f"  🚨 QUEUE BACKLOG: {stats['current_queue_size']} waiting requests!")
            
            if stats['timeouts'] > 0:
                print(f"  ⚠️  WARNING: {stats['timeouts']} requests have timed out!")
            
            await asyncio.sleep(2)
    
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())