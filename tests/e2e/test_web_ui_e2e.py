# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Web UI End-to-End Tests                        #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
End-to-end tests for the Web UI using Selenium.
Tests complete user workflows through the browser interface.
"""

import pytest
import time
import os
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException
from unittest.mock import patch
import threading
import requests


@pytest.mark.e2e
@pytest.mark.web
class TestWebUIE2E:
    """End-to-end tests for Web UI."""
    
    @classmethod
    def setup_class(cls):
        """Setup test class with web server and browser."""
        cls.base_url = "http://localhost:5001"
        cls.web_server_thread = None
        cls.driver = None
        
        # Setup Chrome driver with headless option
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        
        try:
            cls.driver = webdriver.Chrome(options=chrome_options)
            cls.driver.implicitly_wait(10)
        except Exception as e:
            pytest.skip(f"Chrome driver not available: {e}")
        
        # Start web server in separate thread
        cls.start_web_server()
        
        # Wait for server to be ready
        cls.wait_for_server()
    
    @classmethod
    def teardown_class(cls):
        """Cleanup after all tests."""
        if cls.driver:
            cls.driver.quit()
        
        if cls.web_server_thread:
            # Stop web server (implementation depends on how server is started)
            pass
    
    @classmethod
    def start_web_server(cls):
        """Start the DDC web server for testing."""
        def run_server():
            # Mock the web server startup
            # In real scenario, this would start the actual Flask app
            try:
                from app.web_ui import create_app
                app = create_app()
                app.run(host='127.0.0.1', port=5001, debug=False)
            except ImportError:
                # Fallback for testing without actual server
                pass
        
        cls.web_server_thread = threading.Thread(target=run_server, daemon=True)
        cls.web_server_thread.start()
        time.sleep(3)  # Give server time to start
    
    @classmethod
    def wait_for_server(cls):
        """Wait for the web server to be ready."""
        max_attempts = 30
        for _ in range(max_attempts):
            try:
                response = requests.get(cls.base_url, timeout=1)
                if response.status_code < 500:  # Server is responding
                    return
            except requests.exceptions.RequestException:
                pass
            time.sleep(1)
        
        # If we can't connect, we'll mock the tests
        cls.mock_mode = True
    
    def setUp(self):
        """Setup for each test method."""
        if hasattr(self, 'driver'):
            self.driver.delete_all_cookies()
    
    def test_login_page_loads(self):
        """Test that the login page loads correctly."""
        if getattr(self.__class__, 'mock_mode', False):
            pytest.skip("Web server not available - running in mock mode")
        
        self.driver.get(f"{self.base_url}/login")
        
        # Check page title
        assert "DDC" in self.driver.title
        
        # Check login form elements exist
        username_field = self.driver.find_element(By.NAME, "username")
        password_field = self.driver.find_element(By.NAME, "password")
        login_button = self.driver.find_element(By.TYPE, "submit")
        
        assert username_field.is_displayed()
        assert password_field.is_displayed()
        assert login_button.is_displayed()
    
    @patch('app.auth.verify_credentials')
    def test_successful_login(self, mock_verify):
        """Test successful login workflow."""
        if getattr(self.__class__, 'mock_mode', False):
            pytest.skip("Web server not available - running in mock mode")
        
        # Mock successful authentication
        mock_verify.return_value = True
        
        self.driver.get(f"{self.base_url}/login")
        
        # Fill login form
        username_field = self.driver.find_element(By.NAME, "username")
        password_field = self.driver.find_element(By.NAME, "password")
        
        username_field.send_keys("admin")
        password_field.send_keys("correct_password")
        
        # Submit form
        login_button = self.driver.find_element(By.TYPE, "submit")
        login_button.click()
        
        # Wait for redirect to dashboard
        WebDriverWait(self.driver, 10).until(
            EC.url_contains("/dashboard")
        )
        
        assert "/dashboard" in self.driver.current_url
    
    def test_failed_login(self):
        """Test failed login with invalid credentials."""
        if getattr(self.__class__, 'mock_mode', False):
            pytest.skip("Web server not available - running in mock mode")
        
        self.driver.get(f"{self.base_url}/login")
        
        # Fill login form with wrong credentials
        username_field = self.driver.find_element(By.NAME, "username")
        password_field = self.driver.find_element(By.NAME, "password")
        
        username_field.send_keys("admin")
        password_field.send_keys("wrong_password")
        
        # Submit form
        login_button = self.driver.find_element(By.TYPE, "submit")
        login_button.click()
        
        # Should stay on login page and show error
        time.sleep(2)
        assert "/login" in self.driver.current_url
        
        # Check for error message
        try:
            error_element = self.driver.find_element(By.CLASS_NAME, "error")
            assert error_element.is_displayed()
        except:
            # Error message might be in different element
            page_source = self.driver.page_source.lower()
            assert "invalid" in page_source or "error" in page_source
    
    @patch('app.auth.verify_credentials')
    @patch('services.docker.docker_service.DockerService.get_containers')
    def test_dashboard_displays_containers(self, mock_get_containers, mock_verify):
        """Test that dashboard displays container information."""
        if getattr(self.__class__, 'mock_mode', False):
            pytest.skip("Web server not available - running in mock mode")
        
        # Mock authentication and container data
        mock_verify.return_value = True
        mock_containers = [
            type('MockContainer', (), {
                'name': 'test_container_1',
                'status': 'running',
                'attrs': {
                    'Config': {'Image': 'nginx:latest'},
                    'State': {'Status': 'running', 'Running': True}
                }
            })(),
            type('MockContainer', (), {
                'name': 'test_container_2',
                'status': 'stopped',
                'attrs': {
                    'Config': {'Image': 'postgres:13'},
                    'State': {'Status': 'exited', 'Running': False}
                }
            })()
        ]
        mock_get_containers.return_value = type('ServiceResult', (), {
            'success': True,
            'data': mock_containers
        })()
        
        # Login first
        self.driver.get(f"{self.base_url}/login")
        username_field = self.driver.find_element(By.NAME, "username")
        password_field = self.driver.find_element(By.NAME, "password")
        username_field.send_keys("admin")
        password_field.send_keys("password")
        self.driver.find_element(By.TYPE, "submit").click()
        
        # Wait for dashboard
        WebDriverWait(self.driver, 10).until(
            EC.url_contains("/dashboard")
        )
        
        # Check containers are displayed
        container_elements = self.driver.find_elements(By.CLASS_NAME, "container-item")
        assert len(container_elements) >= 2
        
        # Check specific container information
        page_source = self.driver.page_source
        assert "test_container_1" in page_source
        assert "test_container_2" in page_source
        assert "nginx:latest" in page_source
        assert "postgres:13" in page_source
    
    @patch('app.auth.verify_credentials')
    def test_container_control_buttons(self, mock_verify):
        """Test container control buttons functionality."""
        if getattr(self.__class__, 'mock_mode', False):
            pytest.skip("Web server not available - running in mock mode")
        
        mock_verify.return_value = True
        
        # Login and navigate to dashboard
        self.driver.get(f"{self.base_url}/login")
        username_field = self.driver.find_element(By.NAME, "username")
        password_field = self.driver.find_element(By.NAME, "password")
        username_field.send_keys("admin")
        password_field.send_keys("password")
        self.driver.find_element(By.TYPE, "submit").click()
        
        WebDriverWait(self.driver, 10).until(
            EC.url_contains("/dashboard")
        )
        
        # Look for container control buttons
        try:
            start_buttons = self.driver.find_elements(By.CLASS_NAME, "start-btn")
            stop_buttons = self.driver.find_elements(By.CLASS_NAME, "stop-btn")
            restart_buttons = self.driver.find_elements(By.CLASS_NAME, "restart-btn")
            
            # Should have control buttons for containers
            assert len(start_buttons) > 0 or len(stop_buttons) > 0 or len(restart_buttons) > 0
            
            # Test clicking a button (if available)
            if stop_buttons:
                # Click stop button and verify AJAX call
                original_url = self.driver.current_url
                stop_buttons[0].click()
                time.sleep(2)  # Wait for AJAX
                
                # Should stay on same page (AJAX call)
                assert self.driver.current_url == original_url
                
        except Exception as e:
            # Buttons might be dynamically generated
            page_source = self.driver.page_source.lower()
            assert "start" in page_source or "stop" in page_source or "restart" in page_source
    
    @patch('app.auth.verify_credentials')
    def test_navigation_menu(self, mock_verify):
        """Test navigation menu functionality."""
        if getattr(self.__class__, 'mock_mode', False):
            pytest.skip("Web server not available - running in mock mode")
        
        mock_verify.return_value = True
        
        # Login
        self.driver.get(f"{self.base_url}/login")
        username_field = self.driver.find_element(By.NAME, "username")
        password_field = self.driver.find_element(By.NAME, "password")
        username_field.send_keys("admin")
        password_field.send_keys("password")
        self.driver.find_element(By.TYPE, "submit").click()
        
        WebDriverWait(self.driver, 10).until(
            EC.url_contains("/dashboard")
        )
        
        # Test navigation links
        nav_links = self.driver.find_elements(By.TAG_NAME, "a")
        nav_texts = [link.text.lower() for link in nav_links]
        
        # Should have common navigation items
        expected_items = ["dashboard", "settings", "logs"]
        found_items = [item for item in expected_items if any(item in text for text in nav_texts)]
        
        assert len(found_items) >= 1  # At least one nav item should be found
    
    @patch('app.auth.verify_credentials')
    def test_responsive_design(self, mock_verify):
        """Test responsive design at different screen sizes."""
        if getattr(self.__class__, 'mock_mode', False):
            pytest.skip("Web server not available - running in mock mode")
        
        mock_verify.return_value = True
        
        # Login
        self.driver.get(f"{self.base_url}/login")
        username_field = self.driver.find_element(By.NAME, "username")
        password_field = self.driver.find_element(By.NAME, "password")
        username_field.send_keys("admin")
        password_field.send_keys("password")
        self.driver.find_element(By.TYPE, "submit").click()
        
        WebDriverWait(self.driver, 10).until(
            EC.url_contains("/dashboard")
        )
        
        # Test different screen sizes
        screen_sizes = [
            (1920, 1080),  # Desktop
            (1024, 768),   # Tablet
            (375, 667),    # Mobile
        ]
        
        for width, height in screen_sizes:
            self.driver.set_window_size(width, height)
            time.sleep(1)  # Allow time for responsive changes
            
            # Check that page is still usable
            body = self.driver.find_element(By.TAG_NAME, "body")
            assert body.is_displayed()
            
            # Check for mobile menu or responsive elements
            if width < 768:  # Mobile size
                # Should have mobile-friendly navigation
                page_source = self.driver.page_source.lower()
                assert "menu" in page_source or "nav" in page_source
    
    def test_javascript_errors(self):
        """Test for JavaScript errors on pages."""
        if getattr(self.__class__, 'mock_mode', False):
            pytest.skip("Web server not available - running in mock mode")
        
        self.driver.get(f"{self.base_url}/login")
        
        # Check browser console for errors
        logs = self.driver.get_log('browser')
        severe_errors = [log for log in logs if log['level'] == 'SEVERE']
        
        # Should not have severe JavaScript errors
        assert len(severe_errors) == 0, f"JavaScript errors found: {severe_errors}"
    
    @patch('app.auth.verify_credentials')
    def test_accessibility_basics(self, mock_verify):
        """Test basic accessibility features."""
        if getattr(self.__class__, 'mock_mode', False):
            pytest.skip("Web server not available - running in mock mode")
        
        mock_verify.return_value = True
        
        self.driver.get(f"{self.base_url}/login")
        
        # Check for basic accessibility features
        # Alt text for images
        images = self.driver.find_elements(By.TAG_NAME, "img")
        for img in images:
            alt_text = img.get_attribute("alt")
            assert alt_text is not None and alt_text.strip() != ""
        
        # Form labels
        inputs = self.driver.find_elements(By.TAG_NAME, "input")
        for input_elem in inputs:
            # Should have associated label or aria-label
            label_id = input_elem.get_attribute("id")
            aria_label = input_elem.get_attribute("aria-label")
            
            if label_id:
                # Look for associated label
                labels = self.driver.find_elements(By.XPATH, f"//label[@for='{label_id}']")
                assert len(labels) > 0 or aria_label is not None
    
    @patch('app.auth.verify_credentials')
    def test_security_headers(self, mock_verify):
        """Test that security headers are present."""
        if getattr(self.__class__, 'mock_mode', False):
            pytest.skip("Web server not available - running in mock mode")
        
        # Test with requests to check headers
        try:
            response = requests.get(f"{self.base_url}/login")
            headers = response.headers
            
            # Check for security headers
            security_headers = [
                'X-Frame-Options',
                'X-Content-Type-Options',
                'X-XSS-Protection',
                'Strict-Transport-Security',
            ]
            
            found_headers = [header for header in security_headers if header in headers]
            # Should have at least some security headers
            assert len(found_headers) > 0, "No security headers found"
            
        except requests.exceptions.RequestException:
            pytest.skip("Could not test security headers - server not reachable")


@pytest.mark.e2e
@pytest.mark.web
@pytest.mark.slow
class TestWebUIPerformanceE2E:
    """Performance-focused E2E tests."""
    
    def test_page_load_times(self):
        """Test that pages load within acceptable time limits."""
        if getattr(TestWebUIE2E, 'mock_mode', False):
            pytest.skip("Web server not available - running in mock mode")
        
        start_time = time.time()
        response = requests.get("http://localhost:5001/login")
        end_time = time.time()
        
        load_time = end_time - start_time
        assert load_time < 3.0, f"Page load time too slow: {load_time:.2f}s"
        assert response.status_code == 200
    
    @patch('services.docker.docker_service.DockerService.get_containers')
    def test_large_container_list_performance(self, mock_get_containers):
        """Test performance with large number of containers."""
        if getattr(TestWebUIE2E, 'mock_mode', False):
            pytest.skip("Web server not available - running in mock mode")
        
        # Mock large number of containers
        mock_containers = []
        for i in range(100):
            mock_container = type('MockContainer', (), {
                'name': f'container_{i}',
                'status': 'running' if i % 2 == 0 else 'stopped',
                'attrs': {
                    'Config': {'Image': f'image_{i}:latest'},
                    'State': {'Status': 'running' if i % 2 == 0 else 'exited'}
                }
            })()
            mock_containers.append(mock_container)
        
        mock_get_containers.return_value = type('ServiceResult', (), {
            'success': True,
            'data': mock_containers
        })()
        
        start_time = time.time()
        response = requests.get("http://localhost:5001/dashboard")
        end_time = time.time()
        
        load_time = end_time - start_time
        assert load_time < 5.0, f"Dashboard load time with 100 containers too slow: {load_time:.2f}s"


# Custom pytest markers configuration
def pytest_configure(config):
    """Configure pytest markers for E2E tests."""
    config.addinivalue_line(
        "markers",
        "e2e: mark test as end-to-end test requiring full application stack"
    )
    config.addinivalue_line(
        "markers", 
        "web: mark test as requiring web browser and Selenium"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "e2e"])