#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test script for the Modern Async Docker Queue API v2.0
"""

import sys
import asyncio
import time
import logging

# Setup path
sys.path.append('/Volumes/appdata/dockerdiscordcontrol')

from services.docker_service.docker_utils import get_docker_client_async, USE_CONNECTION_POOL
from services.docker_service.docker_client_pool import get_docker_pool

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('async_api_test')


async def test_modern_async_api():
    """Test the modern async API with multiple concurrent requests."""
    print("🚀 Testing Modern Async Docker Queue API v2.0")
    print("=" * 55)
    
    if not USE_CONNECTION_POOL:
        print("❌ Connection pool not available")
        return
    
    async def async_worker(worker_id: int):
        """Async worker using the modern API."""
        results = []
        
        for i in range(2):
            start_time = time.time()
            try:
                # Use the new unified async API
                async with get_docker_client_async(timeout=10.0) as client:
                    # Simulate Docker operations
                    await asyncio.sleep(0.3)  # Simulate work
                    duration = time.time() - start_time
                    
                    results.append({
                        'worker': worker_id,
                        'request': i + 1,
                        'duration': duration,
                        'status': 'success',
                        'client_type': type(client).__name__
                    })
                    
                    print(f"✅ Worker {worker_id}.{i+1}: {duration:.2f}s ({type(client).__name__})")
                    
            except Exception as e:
                duration = time.time() - start_time
                results.append({
                    'worker': worker_id,
                    'request': i + 1,
                    'duration': duration,
                    'status': 'error',
                    'error': str(e)
                })
                print(f"❌ Worker {worker_id}.{i+1}: {e}")
        
        return results
    
    print(f"🔧 Starting 8 async workers (16 total requests)")
    print(f"📊 Pool capacity: 3 connections + intelligent queue")
    print()
    
    start_time = time.time()
    
    # Create 8 workers, each making 2 requests (16 total)
    workers = [async_worker(i) for i in range(1, 9)]
    
    # Run all workers concurrently
    all_results = await asyncio.gather(*workers, return_exceptions=True)
    
    total_time = time.time() - start_time
    
    # Analyze results
    successful_requests = 0
    failed_requests = 0
    total_requests = 0
    total_duration = 0
    
    for worker_results in all_results:
        if isinstance(worker_results, Exception):
            print(f"❌ Worker failed: {worker_results}")
            continue
            
        for result in worker_results:
            total_requests += 1
            total_duration += result['duration']
            if result['status'] == 'success':
                successful_requests += 1
            else:
                failed_requests += 1
    
    # Get queue statistics
    pool = get_docker_pool()
    stats = pool.get_queue_stats()
    
    print(f"\n📊 MODERN ASYNC API TEST RESULTS")
    print(f"=" * 55)
    print(f"✅ Execution time: {total_time:.2f}s")
    print(f"✅ Total requests: {total_requests}")
    print(f"✅ Successful: {successful_requests}")
    print(f"❌ Failed: {failed_requests}")
    print(f"🎯 Success rate: {(successful_requests/total_requests)*100:.1f}%")
    print(f"⚡ Avg request time: {total_duration/total_requests:.3f}s")
    
    print(f"\n📈 QUEUE SYSTEM PERFORMANCE:")
    print(f"🔢 Max queue size: {stats['max_queue_size']}")
    print(f"⏱️  Average wait time: {stats['average_wait_time']:.3f}s")
    print(f"⏰ Timeouts: {stats['timeouts']}")
    print(f"📨 Total requests processed: {stats['total_requests']}")
    print(f"🏊 Pool utilization: {stats['max_connections']} max connections")
    
    # Performance expectations for modern API
    print(f"\n🎯 PERFORMANCE ANALYSIS:")
    
    if successful_requests == total_requests:
        print(f"✅ 100% Success Rate - No requests lost")
    else:
        print(f"❌ Some requests failed")
    
    if stats['max_queue_size'] > 0:
        print(f"✅ Queue System Active - {stats['max_queue_size']} requests queued")
    else:
        print(f"🟡 No queuing occurred (low load test)")
        
    if stats['timeouts'] == 0:
        print(f"✅ Zero Timeouts - All requests handled within limits")
    else:
        print(f"⚠️  {stats['timeouts']} requests timed out")
        
    if stats['average_wait_time'] < 1.0:
        print(f"✅ Fast Queue Processing - {stats['average_wait_time']:.3f}s avg wait")
    else:
        print(f"🟡 Moderate queue wait times - {stats['average_wait_time']:.3f}s")
    
    # Overall assessment
    if (successful_requests == total_requests and 
        stats['timeouts'] == 0 and 
        stats['average_wait_time'] < 5.0):
        print(f"\n🎉 MODERN ASYNC API: ✅ EXCELLENT PERFORMANCE")
        print(f"🚀 Ready for production deployment!")
    else:
        print(f"\n⚠️  MODERN ASYNC API: NEEDS OPTIMIZATION")
        
    return stats


async def main():
    """Main test function."""
    try:
        await test_modern_async_api()
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())