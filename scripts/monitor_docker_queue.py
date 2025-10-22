#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Docker Queue Monitoring Script for DDC Production
Displays real-time queue statistics for debugging and optimization.
"""

import sys
import time
import json
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

def monitor_queue():
    """Monitor Docker queue statistics in real-time."""
    try:
        from services.docker_service.docker_utils import USE_CONNECTION_POOL
        from services.docker_service.docker_client_pool import get_docker_client_service
        
        if not USE_CONNECTION_POOL:
            print("❌ Connection pool not available")
            return
        
        pool = get_docker_client_service()
        print("🔍 Docker Queue Monitor - Press Ctrl+C to exit")
        print("=" * 60)
        
        while True:
            stats = pool.get_queue_stats()
            
            # Clear screen (works on most terminals)
            print("\033[H\033[J", end="")
            
            print(f"🔍 Docker Queue Statistics - {time.strftime('%H:%M:%S')}")
            print("=" * 60)
            print(f"📊 Pool Status:")
            print(f"  • Available clients:     {stats['available_clients']}")
            print(f"  • Clients in use:        {stats['clients_in_use']}")
            print(f"  • Max connections:       {stats['max_connections']}")
            print(f"  • Pool utilization:      {(stats['clients_in_use']/stats['max_connections']*100):.1f}%")
            print()
            print(f"🚀 Queue Metrics:")
            print(f"  • Current queue size:    {stats['current_queue_size']}")
            print(f"  • Max queue size seen:   {stats['max_queue_size']}")
            print(f"  • Total requests:        {stats['total_requests']}")
            print(f"  • Average wait time:     {stats['average_wait_time']:.3f}s")
            print(f"  • Timeouts:              {stats['timeouts']}")
            print()
            
            # Status indicator
            if stats['current_queue_size'] == 0:
                status = "🟢 IDLE"
            elif stats['current_queue_size'] < 5:
                status = "🟡 MODERATE LOAD"
            elif stats['current_queue_size'] < 10:
                status = "🟠 HIGH LOAD"
            else:
                status = "🔴 VERY HIGH LOAD"
            
            print(f"Status: {status}")
            
            if stats['timeouts'] > 0:
                print(f"⚠️  Warning: {stats['timeouts']} requests timed out")
            
            time.sleep(2)  # Update every 2 seconds
            
    except KeyboardInterrupt:
        print("\n\n👋 Monitoring stopped")
    except ImportError:
        print("❌ Could not import Docker service (is the app running?)")
    except Exception as e:
        print(f"❌ Error: {e}")


if __name__ == "__main__":
    monitor_queue()