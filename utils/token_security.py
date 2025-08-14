# -*- coding: utf-8 -*-
"""
Enhanced Token Security Module for DockerDiscordControl
Handles automatic token encryption and security improvements.
"""

import logging
import json
import os
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

class TokenSecurityManager:
    """Manages bot token encryption and security operations."""
    
    def __init__(self, config_manager=None):
        self.config_manager = config_manager
        if not config_manager:
            try:
                from utils.config_manager import ConfigManager
                self.config_manager = ConfigManager()
            except ImportError:
                logger.error("ConfigManager not available for token encryption")
                self.config_manager = None
    
    def encrypt_existing_plaintext_token(self) -> bool:
        """
        Check if bot_config.json contains a plaintext token and encrypt it.
        This is for migration from plaintext to encrypted storage.
        
        Returns:
            bool: True if encryption was successful or not needed, False if failed
        """
        try:
            config_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            bot_config_file = os.path.join(config_dir, "config", "bot_config.json")
            web_config_file = os.path.join(config_dir, "config", "web_config.json")
            
            # Check if files exist
            if not os.path.exists(bot_config_file) or not os.path.exists(web_config_file):
                logger.debug("Config files not found, skipping token encryption migration")
                return True
            
            # Load configurations
            with open(bot_config_file, 'r') as f:
                bot_config = json.load(f)
            
            with open(web_config_file, 'r') as f:
                web_config = json.load(f)
            
            # Get token and password hash
            current_token = bot_config.get('bot_token', '')
            password_hash = web_config.get('web_ui_password_hash')
            
            # Check if token needs encryption
            if not current_token:
                logger.debug("No bot token found, skipping encryption")
                return True
            
            if current_token.startswith('gAAAAA'):
                logger.debug("Bot token is already encrypted")
                return True
            
            if not password_hash:
                logger.warning("No password hash available for token encryption")
                return True
            
            # Encrypt the token
            if not self.config_manager:
                logger.error("ConfigManager not available for encryption")
                return False
            
            encrypted_token = self.config_manager._encrypt_token(current_token, password_hash)
            
            if encrypted_token:
                # Update bot config with encrypted token
                bot_config['bot_token'] = encrypted_token
                
                # Save the updated config
                with open(bot_config_file, 'w') as f:
                    json.dump(bot_config, f, indent=2)
                
                logger.info("🔒 Successfully encrypted existing plaintext bot token")
                return True
            else:
                logger.error("Failed to encrypt bot token")
                return False
                
        except Exception as e:
            logger.error(f"Error during token encryption migration: {e}")
            return False
    
    def verify_token_encryption_status(self) -> Dict[str, Any]:
        """
        Check the current encryption status of the bot token.
        
        Returns:
            dict: Status information about token encryption
        """
        status = {
            'token_exists': False,
            'is_encrypted': False,
            'can_encrypt': False,
            'password_hash_available': False,
            'environment_token_used': False,
            'recommendations': []
        }
        
        try:
            # Check environment variable first
            env_token = os.getenv('DISCORD_BOT_TOKEN')
            if env_token:
                status['environment_token_used'] = True
                status['recommendations'].append("✅ Using secure environment variable")
                return status
            
            # Check config files
            config_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            bot_config_file = os.path.join(config_dir, "config", "bot_config.json")
            web_config_file = os.path.join(config_dir, "config", "web_config.json")
            
            if os.path.exists(bot_config_file):
                with open(bot_config_file, 'r') as f:
                    bot_config = json.load(f)
                
                current_token = bot_config.get('bot_token', '')
                if current_token:
                    status['token_exists'] = True
                    status['is_encrypted'] = current_token.startswith('gAAAAA')
            
            if os.path.exists(web_config_file):
                with open(web_config_file, 'r') as f:
                    web_config = json.load(f)
                
                status['password_hash_available'] = bool(web_config.get('web_ui_password_hash'))
                status['can_encrypt'] = status['password_hash_available']
            
            # Generate recommendations
            if not status['token_exists']:
                status['recommendations'].append("⚠️  No bot token configured")
            elif not status['is_encrypted'] and status['can_encrypt']:
                status['recommendations'].append("🔒 Token can be encrypted for better security")
            elif not status['is_encrypted'] and not status['can_encrypt']:
                status['recommendations'].append("⚠️  Set admin password to enable token encryption")
            elif status['is_encrypted']:
                status['recommendations'].append("✅ Token is encrypted and secure")
            
            # Always recommend environment variable
            if not status['environment_token_used']:
                status['recommendations'].append("💡 Consider using DISCORD_BOT_TOKEN environment variable")
            
        except Exception as e:
            logger.error(f"Error checking token encryption status: {e}")
            status['recommendations'].append("❌ Error checking token status")
        
        return status
    
    def migrate_to_environment_variable(self) -> Dict[str, str]:
        """
        Help user migrate from encrypted config file to environment variable.
        
        Returns:
            dict: Migration information and instructions
        """
        result = {
            'success': False,
            'plaintext_token': '',
            'instructions': [],
            'error': ''
        }
        
        try:
            if not self.config_manager:
                result['error'] = "ConfigManager not available"
                return result
            
            # Load current configuration
            config = self.config_manager.get_config()
            decrypted_token = config.get('bot_token_decrypted_for_usage')
            
            if decrypted_token:
                result['success'] = True
                result['plaintext_token'] = decrypted_token
                result['instructions'] = [
                    "1. Copy the token shown above",
                    "2. Set environment variable: export DISCORD_BOT_TOKEN='your_token_here'",
                    "3. Or add to .env file: DISCORD_BOT_TOKEN=your_token_here",
                    "4. Restart DDC container",
                    "5. Optionally remove token from config file for maximum security"
                ]
            else:
                result['error'] = "Could not decrypt token - check admin password"
                result['instructions'] = [
                    "Token decryption failed. Possible reasons:",
                    "- Token is not encrypted",
                    "- Wrong admin password",
                    "- Corrupted token data"
                ]
        
        except Exception as e:
            result['error'] = str(e)
        
        return result


def auto_encrypt_token_on_startup():
    """
    Automatically encrypt plaintext tokens on application startup.
    This function can be called during DDC initialization.
    """
    try:
        security_manager = TokenSecurityManager()
        
        # Check status first
        status = security_manager.verify_token_encryption_status()
        
        # Auto-encrypt if possible and beneficial
        if (status['token_exists'] and 
            not status['is_encrypted'] and 
            status['can_encrypt'] and 
            not status['environment_token_used']):
            
            logger.info("🔒 Auto-encrypting plaintext bot token...")
            success = security_manager.encrypt_existing_plaintext_token()
            
            if success:
                logger.info("✅ Bot token auto-encryption completed successfully")
            else:
                logger.warning("⚠️  Bot token auto-encryption failed")
        
        return status
        
    except Exception as e:
        logger.error(f"Error during token auto-encryption: {e}")
        return None


# For backwards compatibility
encrypt_existing_plaintext_token = lambda: TokenSecurityManager().encrypt_existing_plaintext_token()
verify_token_encryption_status = lambda: TokenSecurityManager().verify_token_encryption_status()