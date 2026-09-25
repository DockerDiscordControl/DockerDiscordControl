# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Enhanced Token Security Module for DockerDiscordControl
Encrypts the bot token when asked to (never on its own) and reports its status.
"""

from utils.logging_utils import get_module_logger
import logging
import os
from typing import Dict, Any

logger = get_module_logger('token_security')



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

    def _stored_token_and_hash(self):
        """The token as STORED and the password hash, from config.json.

        Every v2 installation keeps both in config.json. This read
        bot_config.json and web_config.json - the split files of the v1 layout,
        which the one-time fold at startup merges into config.json - so on a v2
        installation it found neither and every caller concluded there was no
        token (review E55).
        """
        if not self.config_service:
            raise RuntimeError("ConfigService not available")
        config = self.config_service.get_config(force_reload=True)
        return config.get('bot_token') or '', config.get('web_ui_password_hash') or ''

    @staticmethod
    def _is_encrypted(token: str) -> bool:
        return token.startswith('gAAAA')

    def encrypt_existing_plaintext_token(self) -> bool:
        """Encrypt a plaintext bot token in config.json with the Web UI password.

        What the web panel's "Encrypt token" button runs. It used to look for
        the v1 files, find none on a v2 installation, and return True - which
        the panel reports as "Bot token encrypted successfully" while the token
        stayed plaintext on disk (review E55).

        Returns True when the token is encrypted afterwards or there is none,
        False when it could not be encrypted - no password hash to derive the
        key from, or a failure. Never True for a token still in plaintext.

        The round trip is checked BEFORE anything is written: the key comes from
        the password hash, and a token the bot cannot decrypt is a bot that
        cannot log in.
        """
        try:
            token, password_hash = self._stored_token_and_hash()

            if not token:
                logger.debug("No bot token stored, nothing to encrypt")
                return True
            if self._is_encrypted(token):
                logger.debug("Bot token is already encrypted")
                return True
            if not password_hash:
                logger.warning("Cannot encrypt the bot token: no Web UI password is set "
                               "(the encryption key is derived from it)")
                return False

            encrypted = self.config_service.encrypt_token(token, password_hash)
            if not encrypted or self.config_service.decrypt_token(encrypted, password_hash) != token:
                logger.error("Bot token encryption did not round-trip - nothing was written")
                return False

            result = self.config_service.update_config_fields({'bot_token': encrypted})
            if not getattr(result, 'success', False):
                logger.error("Could not save the encrypted bot token: %s",
                             getattr(result, 'message', result))
                return False

            logger.info("🔒 Bot token encrypted in config.json")
            return True

        except Exception as e:  # noqa: BLE001
            # Broad since review E11: encrypt_token raises TokenEncryptionError
            # (-> ConfigServiceError -> DDCBaseException), which a narrow tuple
            # let escape three layers up to a blank 500 page. Caught by class and
            # not by importing services.exceptions: utils/ importing services/ at
            # module level is a layering inversion (E7).
            logger.error(f"Error encrypting the bot token: {type(e).__name__}: {e}", exc_info=True)
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
                # says NOTHING about what is in config.json. Before,
                # token_exists/is_encrypted stayed at their False defaults, so
                # security_service.py:265 reported 40/40 and "Excellent", the
                # panel showed green, and auto_encrypt_token_on_startup
                # (app/bootstrap/runtime.py:194) never ran - while a plaintext
                # token could sit in the file. The score stays 40/40; only the
                # warning below is added.

            # config.json, where every v2 installation keeps the token. This read
            # the v1 files bot_config.json/web_config.json and so never saw a v2
            # token at all (review E55).
            current_token, password_hash = self._stored_token_and_hash()
            if current_token:
                status['token_exists'] = True
                status['is_encrypted'] = self._is_encrypted(current_token)
            status['password_hash_available'] = bool(password_hash)
            status['can_encrypt'] = status['password_hash_available']

            # Generate recommendations
            if (status['token_exists'] and not status['is_encrypted']
                    and status['environment_token_used']):
                # The dangerous combination: secure source IN USE, insecure copy
                # still readable on disk. Before this fix it was never reported,
                # because the function above returned before looking at the file.
                status['recommendations'].append(
                    "⚠️ Plaintext bot token still present in config.json - the "
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

        except Exception as e:  # noqa: BLE001
            # Broad for the reason the button's handler is (review E11): since
            # E55 the status reads through the ConfigService, whose loader
            # raises ConfigLoadError - a DDCBaseException, in none of the types
            # that stood here. The panel would have got a blank 500 instead of
            # "Error checking token status".
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
    Check the token's encryption status at startup and report it.

    Despite the name, this does not encrypt anything (review E55): the token is
    encrypted when the Web UI button is pressed.
    """
    try:
        security_manager = TokenSecurityManager()

        # Check status first
        status = security_manager.verify_token_encryption_status()

        # Report only - never encrypt here. This used to encrypt a plaintext
        # token at every start; it never saw a v2 token, so it never did.
        # Repairing the status (review E55) would have switched it on for every
        # installation at its first v2.4 start, silently. Decided by the
        # operator: the token is encrypted when the button is pressed.
        if (status['token_exists'] and
            not status['is_encrypted'] and
            status['can_encrypt'] and
            not status['environment_token_used']):
            logger.info("Bot token is stored in plaintext - it can be encrypted in the "
                        "Web UI (Security settings)")

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
