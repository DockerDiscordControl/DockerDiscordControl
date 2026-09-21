# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Enhanced Token Security Module for DockerDiscordControl
Handles automatic token encryption and security improvements.
"""

import logging
import json
import os
import stat
import tempfile
from typing import Dict, Any

logger = logging.getLogger(__name__)

from pathlib import Path


def _atomic_write_json(path, data: Dict[str, Any]) -> None:
    """Write JSON via temp file + os.replace so a crash never truncates ``path``."""
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp_", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        try:
            # Keep the original file mode (mkstemp creates the temp file with 0600)
            os.chmod(tmp_path, stat.S_IMODE(os.stat(path).st_mode))
        except OSError:
            pass
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


class TokenSecurityManager:
    """Manages bot token encryption and security operations."""

    def __init__(self, config_service=None):
        self.config_service = config_service
        if not config_service:
            try:
                from services.config.config_service import get_config_service
                self.config_service = get_config_service()
            except ImportError:
                logger.error("ConfigService not available for token encryption")
                self.config_service = None

    def encrypt_existing_plaintext_token(self) -> bool:
        """
        Check if bot_config.json contains a plaintext token and encrypt it.
        This is for migration from plaintext to encrypted storage.

        Returns:
            bool: True if encryption was successful or not needed, False if failed
        """
        try:
            # Via utils/config_paths.py (DDC_CONFIG_DIR) - config_service writes
            # bot_config.json/web_config.json there. Derived from __file__ before,
            # this looked at the old place: with the files missing there, the
            # migration reported "nothing to do" and the status "no token".
            from utils.config_paths import get_config_dir
            config_dir = get_config_dir()

            bot_config_file = config_dir / "bot_config.json"
            web_config_file = config_dir / "web_config.json"

            # Check if files exist
            if not bot_config_file.exists() or not web_config_file.exists():
                logger.debug("Config files not found, skipping token encryption migration")
                return True

            # Load configurations
            with open(bot_config_file, 'r', encoding='utf-8') as f:
                bot_config = json.load(f)

            with open(web_config_file, 'r', encoding='utf-8') as f:
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
            if not self.config_service:
                logger.error("ConfigService not available for encryption")
                return False

            encrypted_token = self.config_service.encrypt_token(current_token, password_hash)

            if encrypted_token:
                # Update bot config with encrypted token
                bot_config['bot_token'] = encrypted_token

                # Save the updated config (atomically - this file holds the token)
                _atomic_write_json(bot_config_file, bot_config)

                logger.info("🔒 Successfully encrypted existing plaintext bot token")
                return True
            else:
                logger.error("Failed to encrypt bot token")
                return False

        except Exception as e:  # noqa: BLE001
            # OSError: unreadable/root-owned file; ValueError: truncated/empty JSON
            # (JSONDecodeError); AttributeError/TypeError: JSON that isn't an object.
            # The migration is optional - never let it break the startup.
            #
            # Broad since review E11, because the tuple that used to stand here
            # did NOT keep that promise: encrypt_token raises TokenEncryptionError
            # (-> ConfigServiceError -> DDCBaseException), which was in none of
            # those types. It escaped this layer, the security service above it
            # and the route above that - three handlers in a row - and the
            # operator pressed a button and got a blank 500 page.
            #
            # Caught by class and not by importing services.exceptions: utils/
            # importing from services/ at module level is a layering inversion
            # and broke a whole test group the last time I tried it (E7).
            logger.error(f"Error during token encryption migration: {type(e).__name__}: {e}",
                         exc_info=True)
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
                # NO early return any more: that the environment variable is used
                # says NOTHING about what is in bot_config.json. Before,
                # token_exists/is_encrypted stayed at their False defaults, so
                # security_service.py:265 reported 40/40 and "Excellent", the
                # panel showed green, and auto_encrypt_token_on_startup
                # (app/bootstrap/runtime.py:194) never ran - while a plaintext
                # token could sit in the file. The score stays 40/40; only the
                # warning below is added.

            # Check config files - via utils/config_paths.py, see
            # encrypt_existing_plaintext_token.
            from utils.config_paths import get_config_dir
            config_dir = get_config_dir()

            bot_config_file = config_dir / "bot_config.json"
            web_config_file = config_dir / "web_config.json"

            if bot_config_file.exists():
                with open(bot_config_file, 'r', encoding='utf-8') as f:
                    bot_config = json.load(f)

                current_token = bot_config.get('bot_token', '')
                if current_token:
                    status['token_exists'] = True
                    status['is_encrypted'] = current_token.startswith('gAAAAA')

            if web_config_file.exists():
                with open(web_config_file, 'r', encoding='utf-8') as f:
                    web_config = json.load(f)

                status['password_hash_available'] = bool(web_config.get('web_ui_password_hash'))
                status['can_encrypt'] = status['password_hash_available']

            # Generate recommendations
            if (status['token_exists'] and not status['is_encrypted']
                    and status['environment_token_used']):
                # The dangerous combination: secure source IN USE, insecure copy
                # still readable on disk. Before this fix it was never reported,
                # because the function above returned before looking at the file.
                status['recommendations'].append(
                    "⚠️ Plaintext bot token still present in bot_config.json - the "
                    "environment variable is in use, but the file copy is readable. "
                    "Encrypt it or remove it."
                )
            elif not status['token_exists']:
                # Only report when there REALLY is no token. If it comes from the
                # environment variable, "no token configured" is wrong and needlessly
                # alarming - exactly the normal case of a clean setup.
                if not status['environment_token_used']:
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

        except (AttributeError, KeyError, OSError, RuntimeError, TypeError, ValueError) as e:
            logger.error(f"Error checking token encryption status: {e}", exc_info=True)
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
            # config_service, not config_manager: __init__ (:51-59) sets ONLY
            # config_service. The attribute config_manager never existed - the
            # AttributeError was caught at :247 and passed on as the error text,
            # so the operator saw the raw Python text as a dialog in the token
            # window. This path was therefore unreachable from the start, and
            # SPEC.md B5 described a risk that did not exist in practice.
            if not self.config_service:
                result['error'] = "ConfigService not available"
                return result

            # Load current configuration
            config = self.config_service.get_config()
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

        except (AttributeError, KeyError, RuntimeError, TypeError) as e:
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

    except (OSError, ValueError, AttributeError, TypeError, RuntimeError) as e:
        logger.error(f"Error during token auto-encryption: {e}", exc_info=True)
        return None


# For backwards compatibility
def encrypt_existing_plaintext_token():
    """Wrapper function for backwards compatibility."""
    return TokenSecurityManager().encrypt_existing_plaintext_token()

def verify_token_encryption_status():
    """Wrapper function for backwards compatibility."""
    return TokenSecurityManager().verify_token_encryption_status()
