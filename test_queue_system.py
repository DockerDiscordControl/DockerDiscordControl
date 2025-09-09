#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test script for the new Docker Queue System
"""

import sys
import asyncio
import time
import logging
from concurrent.futures import ThreadPoolExecutor

# Setup path
sys.path.append('/Volumes/appdata/dockerdiscordcontrol')

from services.docker_service.docker_client_pool import DockerClientPool

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('queue_test')


async def test_queue_system():
    """Test the queue system with concurrent requests."""
    print("🧪 Testing Docker Connection Pool Queue System")
    print("=" * 50)
    
    # Create pool
    pool = DockerClientPool(max_connections=3, timeout=300)
    
    async def worker(worker_id: int, requests: int = 3):
        """Worker that makes multiple Docker requests."""
        print(f"🔧 Worker {worker_id} starting {requests} requests")
        results = []
        
        for i in range(requests):
            start_time = time.time()
            try:
                # Use the new async queue system
                async with pool.get_client_async(timeout=15.0) as client:
                    # Simulate Docker work
                    await asyncio.sleep(0.5)  # Simulate work
                    duration = time.time() - start_time
                    results.append({
                        'worker': worker_id,
                        'request': i + 1,
                        'duration': duration,
                        'status': 'success'
                    })
                    print(f"✅ Worker {worker_id} request {i+1}: {duration:.2f}s")
                    
            except Exception as e:
                duration = time.time() - start_time
                results.append({
                    'worker': worker_id,
                    'request': i + 1,
                    'duration': duration,
                    'status': 'error',
                    'error': str(e)
                })
                print(f"❌ Worker {worker_id} request {i+1}: {e}")
        
        return results
    
    # Test concurrent requests (more than pool size)
    print(f"\n🚀 Starting 6 workers with 3 max connections (should queue)")
    
    start_time = time.time()
    
    # Create 6 workers, each making 2 requests (12 total requests, 3 concurrent max)
    tasks = [worker(i, 2) for i in range(1, 7)]
    
    # Run all workers concurrently
    all_results = await asyncio.gather(*tasks, return_exceptions=True)
    
    total_time = time.time() - start_time
    
    # Analyze results
    successful_requests = 0
    failed_requests = 0
    total_requests = 0
    
    for worker_results in all_results:
        if isinstance(worker_results, Exception):
            print(f"❌ Worker failed: {worker_results}")
            continue
            
        for result in worker_results:
            total_requests += 1
            if result['status'] == 'success':
                successful_requests += 1
            else:
                failed_requests += 1
    
    # Get queue statistics
    stats = pool.get_queue_stats()
    
    print(f"\n📊 QUEUE SYSTEM TEST RESULTS")
    print(f"=" * 50)
    print(f"Total time: {total_time:.2f}s")
    print(f"Total requests: {total_requests}")
    print(f"Successful: {successful_requests}")
    print(f"Failed: {failed_requests}")
    print(f"Success rate: {(successful_requests/total_requests)*100:.1f}%")
    print(f"\n📈 QUEUE STATISTICS:")
    print(f"Max queue size reached: {stats['max_queue_size']}")
    print(f"Average wait time: {stats['average_wait_time']:.3f}s")
    print(f"Timeouts: {stats['timeouts']}")
    print(f"Total requests processed: {stats['total_requests']}")
    print(f"Max connections: {stats['max_connections']}")
    
    # Expected behavior: 
    # - All requests should succeed
    # - Some should be queued (max_queue_size > 0)
    # - No emergency clients needed
    
    if successful_requests == total_requests and stats['max_queue_size'] > 0:
        print(f"\n🎉 QUEUE SYSTEM TEST: ✅ PASSED")
        print(f"✅ All requests successful without emergency clients")
        print(f"✅ Queue system working properly")
    else:
        print(f"\n❌ QUEUE SYSTEM TEST: FAILED")
        if successful_requests != total_requests:
            print(f"❌ Some requests failed")
        if stats['max_queue_size'] == 0:
            print(f"❌ No requests were queued (may indicate queue not working)")
    
    return stats


async def main():
    """Main test function."""
    try:
        await test_queue_system()
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())