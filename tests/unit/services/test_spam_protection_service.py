# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Spam Protection Service Tests                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Unit tests for the Spam Protection Service.
Tests all spam protection functionality including cooldowns, rate limiting, and user management.
"""

import pytest
import time
from unittest.mock import Mock, patch, AsyncMock
from services.infrastructure.spam_protection_service import (
    SpamProtectionService,
    CooldownManager,
    ServiceResult
)


class TestSpamProtectionService:
    """Test suite for SpamProtectionService."""
    
    def setup_method(self):
        """Setup test fixtures for each test method."""
        self.service = SpamProtectionService()
    
    def test_service_initialization(self):
        """Test that the service initializes correctly."""
        assert self.service is not None
        assert isinstance(self.service, SpamProtectionService)
    
    @patch('services.infrastructure.spam_protection_service.get_config_service')
    def test_check_user_cooldown_not_in_cooldown(self, mock_get_config_service):
        """Test user cooldown check when user is not in cooldown."""
        # Mock config service
        mock_config_service = Mock()
        mock_config = {
            'spam_protection': {
                'cooldowns': {
                    'info_button': 5,
                    'task_button': 10
                },
                'enabled': True
            }
        }
        mock_config_service.get_config.return_value = mock_config
        mock_get_config_service.return_value = mock_config_service
        
        user_id = 123456789
        action_type = 'info_button'
        
        result = self.service.check_user_cooldown(user_id, action_type)
        
        assert result.success is True
        assert result.data['in_cooldown'] is False
        assert result.data['remaining_time'] == 0
    
    @patch('services.infrastructure.spam_protection_service.get_config_service')
    def test_check_user_cooldown_in_cooldown(self, mock_get_config_service):
        """Test user cooldown check when user is in cooldown."""
        mock_config_service = Mock()
        mock_config = {
            'spam_protection': {
                'cooldowns': {
                    'info_button': 5,
                    'task_button': 10
                },
                'enabled': True
            }
        }
        mock_config_service.get_config.return_value = mock_config
        mock_get_config_service.return_value = mock_config_service
        
        user_id = 123456789
        action_type = 'info_button'
        
        # First call should trigger cooldown
        self.service.check_user_cooldown(user_id, action_type)
        
        # Immediately check again - should be in cooldown
        result = self.service.check_user_cooldown(user_id, action_type)
        
        assert result.success is True
        assert result.data['in_cooldown'] is True
        assert result.data['remaining_time'] > 0
        assert result.data['remaining_time'] <= 5
    
    @patch('services.infrastructure.spam_protection_service.get_config_service')
    def test_set_user_cooldown(self, mock_get_config_service):
        """Test setting user cooldown."""
        mock_config_service = Mock()
        mock_config = {
            'spam_protection': {
                'cooldowns': {
                    'info_button': 5
                },
                'enabled': True
            }
        }
        mock_config_service.get_config.return_value = mock_config
        mock_get_config_service.return_value = mock_config_service
        
        user_id = 123456789
        action_type = 'info_button'
        
        result = self.service.set_user_cooldown(user_id, action_type)
        
        assert result.success is True
        assert result.data['user_id'] == user_id
        assert result.data['action_type'] == action_type
        assert result.data['cooldown_set'] is True
        assert result.data['duration'] == 5
    
    @patch('services.infrastructure.spam_protection_service.get_config_service')
    def test_get_spam_protection_settings(self, mock_get_config_service):
        """Test retrieval of spam protection settings."""
        mock_config_service = Mock()
        mock_config = {
            'spam_protection': {
                'enabled': True,
                'cooldowns': {
                    'info_button': 5,
                    'task_button': 10,
                    'protected_info_button': 15
                },
                'rate_limits': {
                    'commands_per_minute': 10,
                    'buttons_per_minute': 20
                },
                'whitelist_roles': ['Admin', 'Moderator'],
                'whitelist_users': [111111111, 222222222]
            }
        }
        mock_config_service.get_config.return_value = mock_config
        mock_get_config_service.return_value = mock_config_service
        
        result = self.service.get_spam_protection_settings()
        
        assert result.success is True
        settings = result.data
        assert settings['enabled'] is True
        assert settings['cooldowns']['info_button'] == 5
        assert settings['cooldowns']['task_button'] == 10
        assert settings['rate_limits']['commands_per_minute'] == 10
        assert 'Admin' in settings['whitelist_roles']
        assert 111111111 in settings['whitelist_users']
    
    @patch('services.infrastructure.spam_protection_service.get_config_service')
    def test_update_spam_protection_settings(self, mock_get_config_service):
        """Test updating spam protection settings."""
        mock_config_service = Mock()
        mock_config = {'spam_protection': {}}
        mock_config_service.get_config.return_value = mock_config
        mock_config_service.save_config.return_value = True
        mock_get_config_service.return_value = mock_config_service
        
        new_settings = {
            'enabled': True,
            'cooldowns': {
                'info_button': 3,
                'task_button': 8,
                'protected_info_button': 12
            },
            'rate_limits': {
                'commands_per_minute': 15,
                'buttons_per_minute': 25
            },
            'whitelist_roles': ['Admin'],
            'whitelist_users': [333333333]
        }
        
        result = self.service.update_spam_protection_settings(new_settings)
        
        assert result.success is True
        assert result.data['updated'] is True
        
        # Verify save was called with correct data
        mock_config_service.save_config.assert_called_once()
        saved_config = mock_config_service.save_config.call_args[0][0]
        assert saved_config['spam_protection'] == new_settings
    
    @patch('services.infrastructure.spam_protection_service.get_config_service')
    def test_is_user_whitelisted_role(self, mock_get_config_service):
        """Test user whitelist check by role."""
        mock_config_service = Mock()
        mock_config = {
            'spam_protection': {
                'whitelist_roles': ['Admin', 'Moderator'],
                'whitelist_users': []
            }
        }
        mock_config_service.get_config.return_value = mock_config
        mock_get_config_service.return_value = mock_config_service
        
        # Mock Discord user with Admin role
        mock_user = Mock()
        mock_user.id = 123456789
        mock_role = Mock()
        mock_role.name = 'Admin'
        mock_user.roles = [mock_role]
        
        result = self.service.is_user_whitelisted(mock_user)
        
        assert result.success is True
        assert result.data['whitelisted'] is True
        assert result.data['reason'] == 'role'
    
    @patch('services.infrastructure.spam_protection_service.get_config_service')
    def test_is_user_whitelisted_user_id(self, mock_get_config_service):
        """Test user whitelist check by user ID."""
        mock_config_service = Mock()
        mock_config = {
            'spam_protection': {
                'whitelist_roles': [],
                'whitelist_users': [123456789, 987654321]
            }
        }
        mock_config_service.get_config.return_value = mock_config
        mock_get_config_service.return_value = mock_config_service
        
        mock_user = Mock()
        mock_user.id = 123456789
        mock_user.roles = []
        
        result = self.service.is_user_whitelisted(mock_user)
        
        assert result.success is True
        assert result.data['whitelisted'] is True
        assert result.data['reason'] == 'user_id'
    
    @patch('services.infrastructure.spam_protection_service.get_config_service')
    def test_is_user_not_whitelisted(self, mock_get_config_service):
        """Test user whitelist check for non-whitelisted user."""
        mock_config_service = Mock()
        mock_config = {
            'spam_protection': {
                'whitelist_roles': ['Admin'],
                'whitelist_users': [999999999]
            }
        }
        mock_config_service.get_config.return_value = mock_config
        mock_get_config_service.return_value = mock_config_service
        
        mock_user = Mock()
        mock_user.id = 123456789
        mock_role = Mock()
        mock_role.name = 'Member'
        mock_user.roles = [mock_role]
        
        result = self.service.is_user_whitelisted(mock_user)
        
        assert result.success is True
        assert result.data['whitelisted'] is False
        assert result.data['reason'] is None
    
    @patch('services.infrastructure.spam_protection_service.get_config_service')
    def test_check_rate_limit_not_exceeded(self, mock_get_config_service):
        """Test rate limit check when limit is not exceeded."""
        mock_config_service = Mock()
        mock_config = {
            'spam_protection': {
                'rate_limits': {
                    'commands_per_minute': 10,
                    'buttons_per_minute': 20
                },
                'enabled': True
            }
        }
        mock_config_service.get_config.return_value = mock_config
        mock_get_config_service.return_value = mock_config_service
        
        user_id = 123456789
        rate_type = 'commands_per_minute'
        
        result = self.service.check_rate_limit(user_id, rate_type)
        
        assert result.success is True
        assert result.data['rate_limited'] is False
        assert result.data['remaining_requests'] > 0
    
    @patch('services.infrastructure.spam_protection_service.get_config_service')
    def test_spam_protection_disabled(self, mock_get_config_service):
        """Test behavior when spam protection is disabled."""
        mock_config_service = Mock()
        mock_config = {
            'spam_protection': {
                'enabled': False,
                'cooldowns': {'info_button': 5}
            }
        }
        mock_config_service.get_config.return_value = mock_config
        mock_get_config_service.return_value = mock_config_service
        
        user_id = 123456789
        action_type = 'info_button'
        
        result = self.service.check_user_cooldown(user_id, action_type)
        
        # When disabled, should never be in cooldown
        assert result.success is True
        assert result.data['in_cooldown'] is False
        assert result.data['remaining_time'] == 0
    
    @patch('services.infrastructure.spam_protection_service.get_config_service')
    def test_get_user_cooldown_status(self, mock_get_config_service):
        """Test getting comprehensive cooldown status for a user."""
        mock_config_service = Mock()
        mock_config = {
            'spam_protection': {
                'enabled': True,
                'cooldowns': {
                    'info_button': 5,
                    'task_button': 10,
                    'protected_info_button': 15
                }
            }
        }
        mock_config_service.get_config.return_value = mock_config
        mock_get_config_service.return_value = mock_config_service
        
        user_id = 123456789
        
        # Set some cooldowns
        self.service.set_user_cooldown(user_id, 'info_button')
        self.service.set_user_cooldown(user_id, 'task_button')
        
        result = self.service.get_user_cooldown_status(user_id)
        
        assert result.success is True
        status = result.data
        assert 'info_button' in status
        assert 'task_button' in status
        assert 'protected_info_button' in status
        assert status['info_button']['in_cooldown'] is True
        assert status['task_button']['in_cooldown'] is True
        assert status['protected_info_button']['in_cooldown'] is False
    
    @patch('services.infrastructure.spam_protection_service.get_config_service')
    def test_clear_user_cooldowns(self, mock_get_config_service):
        """Test clearing all cooldowns for a user."""
        mock_config_service = Mock()
        mock_config = {
            'spam_protection': {
                'enabled': True,
                'cooldowns': {'info_button': 5}
            }
        }
        mock_config_service.get_config.return_value = mock_config
        mock_get_config_service.return_value = mock_config_service
        
        user_id = 123456789
        
        # Set a cooldown
        self.service.set_user_cooldown(user_id, 'info_button')
        
        # Verify cooldown is active
        cooldown_result = self.service.check_user_cooldown(user_id, 'info_button')
        assert cooldown_result.data['in_cooldown'] is True
        
        # Clear cooldowns
        clear_result = self.service.clear_user_cooldowns(user_id)
        assert clear_result.success is True
        
        # Verify cooldown is cleared
        after_clear_result = self.service.check_user_cooldown(user_id, 'info_button')
        assert after_clear_result.data['in_cooldown'] is False
    
    @patch('services.infrastructure.spam_protection_service.get_config_service')
    def test_service_exception_handling(self, mock_get_config_service):
        """Test that service handles exceptions gracefully."""
        # Make config service raise an exception
        mock_get_config_service.side_effect = Exception("Config service error")
        
        result = self.service.get_spam_protection_settings()
        
        assert result.success is False
        assert "Error retrieving spam protection settings" in result.error
        assert "Config service error" in result.error


class TestCooldownManager:
    """Test suite for CooldownManager helper class."""
    
    def test_cooldown_manager_initialization(self):
        """Test CooldownManager initialization."""
        manager = CooldownManager()
        assert manager is not None
    
    def test_set_and_check_cooldown(self):
        """Test setting and checking cooldowns."""
        manager = CooldownManager()
        
        user_id = 123456789
        action_type = 'test_action'
        duration = 2
        
        # Initially not in cooldown
        assert manager.is_in_cooldown(user_id, action_type) is False
        
        # Set cooldown
        manager.set_cooldown(user_id, action_type, duration)
        
        # Should be in cooldown now
        assert manager.is_in_cooldown(user_id, action_type) is True
        
        # Check remaining time
        remaining = manager.get_remaining_time(user_id, action_type)
        assert remaining > 0
        assert remaining <= duration
    
    def test_cooldown_expiry(self):
        """Test that cooldowns expire correctly."""
        manager = CooldownManager()
        
        user_id = 123456789
        action_type = 'test_action'
        duration = 1  # 1 second
        
        manager.set_cooldown(user_id, action_type, duration)
        assert manager.is_in_cooldown(user_id, action_type) is True
        
        # Wait for cooldown to expire
        time.sleep(1.1)
        
        assert manager.is_in_cooldown(user_id, action_type) is False
        assert manager.get_remaining_time(user_id, action_type) == 0
    
    def test_clear_user_cooldowns(self):
        """Test clearing all cooldowns for a user."""
        manager = CooldownManager()
        
        user_id = 123456789
        
        # Set multiple cooldowns
        manager.set_cooldown(user_id, 'action1', 60)
        manager.set_cooldown(user_id, 'action2', 60)
        
        assert manager.is_in_cooldown(user_id, 'action1') is True
        assert manager.is_in_cooldown(user_id, 'action2') is True
        
        # Clear all cooldowns for user
        manager.clear_user_cooldowns(user_id)
        
        assert manager.is_in_cooldown(user_id, 'action1') is False
        assert manager.is_in_cooldown(user_id, 'action2') is False
    
    def test_cleanup_expired_cooldowns(self):
        """Test cleanup of expired cooldowns."""
        manager = CooldownManager()
        
        # Set short cooldown
        manager.set_cooldown(123, 'test', 1)
        
        # Verify it's in the cooldowns dict
        assert len(manager.cooldowns) > 0
        
        # Wait for expiry
        time.sleep(1.1)
        
        # Cleanup should remove expired entries
        manager._cleanup_expired()
        
        # Check if expired cooldown was cleaned up
        assert manager.is_in_cooldown(123, 'test') is False


# Integration test
@pytest.mark.integration
class TestSpamProtectionServiceIntegration:
    """Integration tests for spam protection service."""
    
    @patch('services.infrastructure.spam_protection_service.get_config_service')
    def test_full_spam_protection_workflow(self, mock_get_config_service):
        """Test a complete spam protection workflow."""
        service = SpamProtectionService()
        
        # Setup mock
        mock_config_service = Mock()
        mock_config = {
            'spam_protection': {
                'enabled': True,
                'cooldowns': {
                    'info_button': 5,
                    'task_button': 10
                },
                'rate_limits': {
                    'commands_per_minute': 10
                },
                'whitelist_roles': ['Admin'],
                'whitelist_users': [999999999]
            }
        }
        mock_config_service.get_config.return_value = mock_config
        mock_config_service.save_config.return_value = True
        mock_get_config_service.return_value = mock_config_service
        
        user_id = 123456789
        
        # 1. Check initial state - no cooldown
        initial_check = service.check_user_cooldown(user_id, 'info_button')
        assert initial_check.success is True
        assert initial_check.data['in_cooldown'] is False
        
        # 2. Set cooldown
        set_cooldown = service.set_user_cooldown(user_id, 'info_button')
        assert set_cooldown.success is True
        
        # 3. Check cooldown is active
        active_check = service.check_user_cooldown(user_id, 'info_button')
        assert active_check.success is True
        assert active_check.data['in_cooldown'] is True
        
        # 4. Check rate limit
        rate_check = service.check_rate_limit(user_id, 'commands_per_minute')
        assert rate_check.success is True
        assert rate_check.data['rate_limited'] is False
        
        # 5. Test whitelist
        mock_user = Mock()
        mock_user.id = 999999999  # Whitelisted user
        mock_user.roles = []
        
        whitelist_check = service.is_user_whitelisted(mock_user)
        assert whitelist_check.success is True
        assert whitelist_check.data['whitelisted'] is True
        
        # 6. Get comprehensive status
        status = service.get_user_cooldown_status(user_id)
        assert status.success is True
        assert 'info_button' in status.data
        
        # 7. Clear cooldowns
        clear_result = service.clear_user_cooldowns(user_id)
        assert clear_result.success is True
        
        # 8. Verify cooldowns cleared
        final_check = service.check_user_cooldown(user_id, 'info_button')
        assert final_check.success is True
        assert final_check.data['in_cooldown'] is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])