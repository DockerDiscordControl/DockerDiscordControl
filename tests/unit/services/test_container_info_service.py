# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Container Info Service Tests                   #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Unit tests for the Container Info Service.
Tests all container information functionality including protected content and settings.
"""

import pytest
from unittest.mock import Mock, patch
from services.infrastructure.container_info_service import (
    ContainerInfoService,
    ServiceResult
)


class TestContainerInfoService:
    """Test suite for ContainerInfoService."""
    
    def setup_method(self):
        """Setup test fixtures for each test method."""
        self.service = ContainerInfoService()
    
    def test_service_initialization(self):
        """Test that the service initializes correctly."""
        assert self.service is not None
        assert isinstance(self.service, ContainerInfoService)
    
    @patch('services.infrastructure.container_info_service.get_config_service')
    def test_get_container_info_success(self, mock_get_config_service):
        """Test successful retrieval of container info."""
        # Mock config service
        mock_config_service = Mock()
        mock_config = {
            'container_info': {
                'test_container': {
                    'enabled': True,
                    'show_ip': True,
                    'custom_ip': '192.168.1.100',
                    'custom_port': '8080',
                    'custom_text': 'Test Container',
                    'protected_enabled': False,
                    'protected_content': '',
                    'protected_password': ''
                }
            }
        }
        mock_config_service.get_config.return_value = mock_config
        mock_get_config_service.return_value = mock_config_service
        
        # Test the method
        result = self.service.get_container_info('test_container')
        
        # Assertions
        assert result.success is True
        assert result.data is not None
        assert result.data['enabled'] is True
        assert result.data['show_ip'] is True
        assert result.data['custom_ip'] == '192.168.1.100'
        assert result.data['custom_port'] == '8080'
        assert result.data['custom_text'] == 'Test Container'
        assert result.data['protected_enabled'] is False
    
    @patch('services.infrastructure.container_info_service.get_config_service')
    def test_get_container_info_not_found(self, mock_get_config_service):
        """Test container info retrieval for non-existent container."""
        mock_config_service = Mock()
        mock_config = {'container_info': {}}
        mock_config_service.get_config.return_value = mock_config
        mock_get_config_service.return_value = mock_config_service
        
        result = self.service.get_container_info('nonexistent_container')
        
        # Should return default values
        assert result.success is True
        assert result.data['enabled'] is False
        assert result.data['show_ip'] is False
        assert result.data['custom_ip'] == ''
        assert result.data['custom_port'] == ''
        assert result.data['custom_text'] == ''
        assert result.data['protected_enabled'] is False
    
    @patch('services.infrastructure.container_info_service.get_config_service')
    def test_update_container_info_success(self, mock_get_config_service):
        """Test successful update of container info."""
        mock_config_service = Mock()
        mock_config = {'container_info': {}}
        mock_config_service.get_config.return_value = mock_config
        mock_config_service.save_config.return_value = True
        mock_get_config_service.return_value = mock_config_service
        
        # Test data
        container_name = 'test_container'
        info_data = {
            'enabled': True,
            'show_ip': True,
            'custom_ip': '10.0.0.5',
            'custom_port': '9090',
            'custom_text': 'Updated Container',
            'protected_enabled': True,
            'protected_content': 'Secret info',
            'protected_password': 'password123'
        }
        
        result = self.service.update_container_info(container_name, info_data)
        
        # Assertions
        assert result.success is True
        assert result.data['container_name'] == container_name
        assert result.data['updated'] is True
        
        # Verify save was called with correct data
        mock_config_service.save_config.assert_called_once()
        saved_config = mock_config_service.save_config.call_args[0][0]
        assert saved_config['container_info'][container_name] == info_data
    
    @patch('services.infrastructure.container_info_service.get_config_service')
    def test_update_container_info_validation_error(self, mock_get_config_service):
        """Test container info update with invalid data."""
        mock_config_service = Mock()
        mock_get_config_service.return_value = mock_config_service
        
        # Invalid data - missing required fields
        invalid_data = {'enabled': True}  # Missing other required fields
        
        result = self.service.update_container_info('test', invalid_data)
        
        assert result.success is False
        assert "validation error" in result.error.lower()
    
    @patch('services.infrastructure.container_info_service.get_config_service')
    def test_delete_container_info_success(self, mock_get_config_service):
        """Test successful deletion of container info."""
        mock_config_service = Mock()
        mock_config = {
            'container_info': {
                'test_container': {
                    'enabled': True,
                    'custom_text': 'To be deleted'
                }
            }
        }
        mock_config_service.get_config.return_value = mock_config
        mock_config_service.save_config.return_value = True
        mock_get_config_service.return_value = mock_config_service
        
        result = self.service.delete_container_info('test_container')
        
        assert result.success is True
        assert result.data['container_name'] == 'test_container'
        assert result.data['deleted'] is True
        
        # Verify the container info was removed from config
        mock_config_service.save_config.assert_called_once()
        saved_config = mock_config_service.save_config.call_args[0][0]
        assert 'test_container' not in saved_config['container_info']
    
    @patch('services.infrastructure.container_info_service.get_config_service')
    def test_delete_container_info_not_found(self, mock_get_config_service):
        """Test deletion of non-existent container info."""
        mock_config_service = Mock()
        mock_config = {'container_info': {}}
        mock_config_service.get_config.return_value = mock_config
        mock_get_config_service.return_value = mock_config_service
        
        result = self.service.delete_container_info('nonexistent')
        
        assert result.success is False
        assert "not found" in result.error.lower()
    
    @patch('services.infrastructure.container_info_service.get_config_service')
    def test_get_all_container_info(self, mock_get_config_service):
        """Test retrieval of all container info."""
        mock_config_service = Mock()
        mock_config = {
            'container_info': {
                'container1': {'enabled': True, 'custom_text': 'First'},
                'container2': {'enabled': False, 'custom_text': 'Second'},
                'container3': {'enabled': True, 'custom_text': 'Third'}
            }
        }
        mock_config_service.get_config.return_value = mock_config
        mock_get_config_service.return_value = mock_config_service
        
        result = self.service.get_all_container_info()
        
        assert result.success is True
        assert len(result.data) == 3
        assert 'container1' in result.data
        assert 'container2' in result.data
        assert 'container3' in result.data
        assert result.data['container1']['custom_text'] == 'First'
    
    @patch('services.infrastructure.container_info_service.get_config_service')
    def test_validate_protected_password_success(self, mock_get_config_service):
        """Test successful protected content password validation."""
        mock_config_service = Mock()
        mock_config = {
            'container_info': {
                'protected_container': {
                    'protected_enabled': True,
                    'protected_password': 'secret123'
                }
            }
        }
        mock_config_service.get_config.return_value = mock_config
        mock_get_config_service.return_value = mock_config_service
        
        result = self.service.validate_protected_password('protected_container', 'secret123')
        
        assert result.success is True
        assert result.data['valid'] is True
    
    @patch('services.infrastructure.container_info_service.get_config_service')
    def test_validate_protected_password_invalid(self, mock_get_config_service):
        """Test protected content password validation with wrong password."""
        mock_config_service = Mock()
        mock_config = {
            'container_info': {
                'protected_container': {
                    'protected_enabled': True,
                    'protected_password': 'secret123'
                }
            }
        }
        mock_config_service.get_config.return_value = mock_config
        mock_get_config_service.return_value = mock_config_service
        
        result = self.service.validate_protected_password('protected_container', 'wrong_password')
        
        assert result.success is True
        assert result.data['valid'] is False
    
    @patch('services.infrastructure.container_info_service.get_config_service')
    def test_validate_protected_password_not_protected(self, mock_get_config_service):
        """Test password validation for non-protected container."""
        mock_config_service = Mock()
        mock_config = {
            'container_info': {
                'normal_container': {
                    'protected_enabled': False
                }
            }
        }
        mock_config_service.get_config.return_value = mock_config
        mock_get_config_service.return_value = mock_config_service
        
        result = self.service.validate_protected_password('normal_container', 'any_password')
        
        assert result.success is True
        assert result.data['valid'] is True  # Always valid for non-protected containers
    
    @patch('services.infrastructure.container_info_service.get_config_service')
    def test_service_exception_handling(self, mock_get_config_service):
        """Test that service handles exceptions gracefully."""
        # Make config service raise an exception
        mock_get_config_service.side_effect = Exception("Config service error")
        
        result = self.service.get_container_info('test')
        
        assert result.success is False
        assert "Error retrieving container info" in result.error
        assert "Config service error" in result.error
    
    @patch('services.infrastructure.container_info_service.get_config_service')
    def test_input_sanitization(self, mock_get_config_service):
        """Test input sanitization for container names and data."""
        mock_config_service = Mock()
        mock_config_service.get_config.return_value = {'container_info': {}}
        mock_get_config_service.return_value = mock_config_service
        
        # Test with potentially malicious container name
        malicious_name = "<script>alert('xss')</script>"
        
        result = self.service.get_container_info(malicious_name)
        
        # Should handle gracefully without executing scripts
        assert result.success is True  # Returns defaults for non-existent containers
        # The service should sanitize or safely handle the input


# Integration test with real dependencies
@pytest.mark.integration
class TestContainerInfoServiceIntegration:
    """Integration tests for container info service."""
    
    @patch('services.infrastructure.container_info_service.get_config_service')
    def test_full_container_info_workflow(self, mock_get_config_service):
        """Test a complete container info management workflow."""
        service = ContainerInfoService()
        
        # Setup mock
        mock_config_service = Mock()
        mock_config = {'container_info': {}}
        mock_config_service.get_config.return_value = mock_config
        mock_config_service.save_config.return_value = True
        mock_get_config_service.return_value = mock_config_service
        
        container_name = 'workflow_test_container'
        
        # 1. Get initial info (should be defaults)
        initial_result = service.get_container_info(container_name)
        assert initial_result.success is True
        assert initial_result.data['enabled'] is False
        
        # 2. Update container info
        new_info = {
            'enabled': True,
            'show_ip': True,
            'custom_ip': '172.16.0.10',
            'custom_port': '3000',
            'custom_text': 'Workflow Test Container',
            'protected_enabled': True,
            'protected_content': 'Secret workflow data',
            'protected_password': 'workflow123'
        }
        
        update_result = service.update_container_info(container_name, new_info)
        assert update_result.success is True
        
        # 3. Verify the update by getting info again
        # Simulate the config having been saved
        mock_config['container_info'][container_name] = new_info
        
        updated_result = service.get_container_info(container_name)
        assert updated_result.success is True
        assert updated_result.data['enabled'] is True
        assert updated_result.data['custom_text'] == 'Workflow Test Container'
        assert updated_result.data['protected_enabled'] is True
        
        # 4. Test password validation
        valid_password_result = service.validate_protected_password(container_name, 'workflow123')
        assert valid_password_result.success is True
        assert valid_password_result.data['valid'] is True
        
        invalid_password_result = service.validate_protected_password(container_name, 'wrong')
        assert invalid_password_result.success is True
        assert invalid_password_result.data['valid'] is False
        
        # 5. Delete container info
        delete_result = service.delete_container_info(container_name)
        assert delete_result.success is True
        
        # Verify save was called multiple times throughout the workflow
        assert mock_config_service.save_config.call_count >= 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])