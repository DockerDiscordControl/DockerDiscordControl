# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Load Testing with Locust                       #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Load testing configuration for Locust.
Simulates realistic user behavior and system load.

Usage:
    locust -f tests/load/locustfile.py --host=http://localhost:5001
    locust -f tests/load/locustfile.py --host=http://localhost:5001 --users=50 --spawn-rate=5 --run-time=300s
"""

from locust import HttpUser, task, between
import random
import json
import time


class DDCWebUser(HttpUser):
    """Simulates a typical DDC web UI user."""
    
    wait_time = between(2, 8)  # Wait 2-8 seconds between requests
    
    def on_start(self):
        """Setup tasks performed when user starts."""
        self.login()
    
    def login(self):
        """Perform login."""
        # Get login page first
        response = self.client.get("/login")
        
        if response.status_code == 200:
            # Attempt login
            login_response = self.client.post("/login", data={
                "username": "admin",
                "password": "admin123"  # Test credentials
            })
            
            if login_response.status_code == 200:
                # Check if we're redirected to dashboard
                self.client.get("/dashboard")
    
    @task(3)
    def view_dashboard(self):
        """View main dashboard - most common action."""
        with self.client.get("/dashboard", catch_response=True) as response:
            if response.status_code != 200:
                response.failure(f"Dashboard returned {response.status_code}")
    
    @task(2)
    def view_container_list(self):
        """View container list."""
        self.client.get("/containers")
    
    @task(1)
    def view_container_info(self):
        """View specific container information."""
        # Simulate looking at different containers
        container_names = [
            "nginx_web_1", "postgres_db_1", "redis_cache_1", 
            "app_backend_1", "monitoring_1"
        ]
        container = random.choice(container_names)
        
        with self.client.get(f"/container/{container}", catch_response=True) as response:
            if response.status_code == 404:
                # Container not found is acceptable in load testing
                response.success()
    
    @task(1)
    def check_system_status(self):
        """Check system status."""
        self.client.get("/api/status")
    
    @task(1)
    def view_logs(self):
        """View container logs."""
        container_names = ["nginx_web_1", "postgres_db_1", "app_backend_1"]
        container = random.choice(container_names)
        
        self.client.get(f"/api/container/{container}/logs")
    
    @task(1)
    def control_container(self):
        """Perform container control actions."""
        actions = ["start", "stop", "restart"]
        containers = ["test_container_1", "test_container_2"]
        
        action = random.choice(actions)
        container = random.choice(containers)
        
        self.client.post("/api/container/control", json={
            "container_name": container,
            "action": action
        })
    
    @task(1)
    def view_donation_history(self):
        """View donation history."""
        self.client.get("/api/donations/history?limit=20")
    
    @task(1)
    def update_container_info(self):
        """Update container information."""
        container = "test_container_1"
        
        self.client.post("/api/container/info/update", json={
            "container_name": container,
            "info": {
                "enabled": True,
                "custom_text": f"Updated at {time.time()}"
            }
        })


class DDCAPIUser(HttpUser):
    """Simulates API-only usage patterns."""
    
    wait_time = between(1, 3)  # Faster API calls
    
    @task(5)
    def get_container_status(self):
        """Get container status via API."""
        containers = ["web_1", "db_1", "cache_1", "app_1"]
        container = random.choice(containers)
        
        self.client.get(f"/api/container/{container}/status")
    
    @task(3)
    def list_all_containers(self):
        """List all containers."""
        self.client.get("/api/containers")
    
    @task(2)
    def get_system_metrics(self):
        """Get system metrics."""
        self.client.get("/api/metrics")
    
    @task(1)
    def container_operations(self):
        """Perform container operations."""
        operations = ["start", "stop", "restart"]
        containers = ["test_app_1", "test_web_1", "test_db_1"]
        
        operation = random.choice(operations)
        container = random.choice(containers)
        
        self.client.post("/api/container/control", json={
            "container_name": container,
            "action": operation
        })
    
    @task(1)
    def get_container_logs(self):
        """Get container logs."""
        containers = ["app_1", "web_1", "worker_1"]
        container = random.choice(containers)
        
        params = {
            "lines": random.randint(10, 100),
            "since": "1h"
        }
        
        self.client.get(f"/api/container/{container}/logs", params=params)


class DDCHeavyUser(HttpUser):
    """Simulates heavy usage patterns that stress the system."""
    
    wait_time = between(0.5, 2)  # Very frequent requests
    
    @task(10)
    def rapid_container_checks(self):
        """Rapidly check multiple containers."""
        containers = [f"stress_test_{i}" for i in range(20)]
        
        for container in containers[:5]:  # Check 5 containers rapidly
            self.client.get(f"/api/container/{container}/status")
    
    @task(3)
    def bulk_log_requests(self):
        """Request logs from multiple containers."""
        containers = ["web_1", "app_1", "worker_1", "db_1", "cache_1"]
        
        for container in containers:
            self.client.get(f"/api/container/{container}/logs?lines=500")
    
    @task(2)
    def dashboard_spam(self):
        """Rapidly refresh dashboard."""
        for _ in range(3):
            self.client.get("/dashboard")
            time.sleep(0.1)
    
    @task(1)
    def concurrent_operations(self):
        """Perform multiple operations in quick succession."""
        container = f"test_heavy_{random.randint(1, 10)}"
        
        # Rapid sequence of operations
        self.client.get(f"/api/container/{container}/status")
        self.client.post("/api/container/control", json={
            "container_name": container,
            "action": "restart"
        })
        self.client.get(f"/api/container/{container}/logs?lines=50")


class DDCMobileUser(HttpUser):
    """Simulates mobile user behavior patterns."""
    
    wait_time = between(3, 10)  # Slower mobile interactions
    
    def on_start(self):
        """Setup mobile user session."""
        # Set mobile user agent
        self.client.headers.update({
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15'
        })
        self.login_mobile()
    
    def login_mobile(self):
        """Mobile login flow."""
        self.client.get("/login")
        
        # Mobile users might take longer to type
        time.sleep(random.uniform(2, 5))
        
        self.client.post("/login", data={
            "username": "mobile_user",
            "password": "mobile123"
        })
    
    @task(5)
    def mobile_dashboard(self):
        """View mobile-optimized dashboard."""
        self.client.get("/dashboard")
    
    @task(2)
    def touch_container_info(self):
        """Touch/tap container for info (mobile pattern)."""
        containers = ["mobile_app", "mobile_web", "mobile_api"]
        container = random.choice(containers)
        
        self.client.get(f"/container/{container}")
    
    @task(1)
    def mobile_settings(self):
        """Access settings on mobile."""
        self.client.get("/settings")
    
    @task(1)
    def quick_container_actions(self):
        """Quick container actions on mobile."""
        container = f"mobile_test_{random.randint(1, 3)}"
        action = random.choice(["start", "stop"])
        
        self.client.post("/api/container/control", json={
            "container_name": container,
            "action": action
        })


# Custom load testing scenarios
class StressTestUser(HttpUser):
    """Stress testing scenario for system limits."""
    
    wait_time = between(0.1, 0.5)  # Very aggressive timing
    
    @task(20)
    def stress_container_list(self):
        """Aggressively request container lists."""
        self.client.get("/api/containers")
    
    @task(10)
    def stress_individual_containers(self):
        """Stress individual container endpoints."""
        container_id = random.randint(1, 100)
        self.client.get(f"/api/container/stress_test_{container_id}/status")
    
    @task(5)
    def stress_operations(self):
        """Stress container operations."""
        container = f"stress_{random.randint(1, 50)}"
        action = random.choice(["start", "stop", "restart"])
        
        self.client.post("/api/container/control", json={
            "container_name": container,
            "action": action
        })
    
    @task(3)
    def stress_logs(self):
        """Stress log endpoints."""
        container = f"log_stress_{random.randint(1, 20)}"
        lines = random.randint(100, 1000)
        
        self.client.get(f"/api/container/{container}/logs?lines={lines}")


# Load test configuration examples
"""
Example Locust commands for different scenarios:

1. Normal web users:
   locust -f locustfile.py --user-class=DDCWebUser --users=20 --spawn-rate=2

2. API-heavy load:
   locust -f locustfile.py --user-class=DDCAPIUser --users=50 --spawn-rate=5

3. Mixed load:
   locust -f locustfile.py --users=100 --spawn-rate=10

4. Stress test:
   locust -f locustfile.py --user-class=StressTestUser --users=200 --spawn-rate=20

5. Mobile users:
   locust -f locustfile.py --user-class=DDCMobileUser --users=30 --spawn-rate=3

6. Long-running test:
   locust -f locustfile.py --users=75 --spawn-rate=5 --run-time=1800s
"""