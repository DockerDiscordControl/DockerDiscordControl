#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Security Service                               #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""
Security Service - Handles comprehensive security operations including token
management, encryption, security auditing, and migration assistance.
"""

import os
import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class TokenSecurityStatusRequest:
    """Represents a token security status request."""
    pass


@dataclass
class TokenEncryptionRequest:
    """Represents a token encryption request."""
    pass


@dataclass
class MigrationHelpRequest:
    """Represents a migration help request."""
    pass


@dataclass
class SecurityAuditRequest:
    """Represents a security audit request."""
    request_object: Any = None  # Flask request object for HTTPS detection


@dataclass
class SecurityResult:
    """Represents the result of security operations."""
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    status_code: int = 200


class SecurityService:
    """Service for comprehensive security management and auditing."""

    def __init__(self):
        self.logger = logger

    def get_token_security_status(self, request: TokenSecurityStatusRequest) -> SecurityResult:
        """
        Get the current security status of the bot token.

        Args:
            request: TokenSecurityStatusRequest

        Returns:
            SecurityResult with token security status information
        """
        try:
            from utils.token_security import TokenSecurityManager

            security_manager = TokenSecurityManager()
            status = security_manager.verify_token_encryption_status()

            return SecurityResult(
                success=True,
                data=status
            )

        except Exception as e:
            self.logger.error(f"Error getting token security status: {e}")
            return SecurityResult(
                success=False,
                error=str(e),
                data={
                    'token_exists': False,
                    'is_encrypted': False,
                    'can_encrypt': False,
                    'password_hash_available': False,
                    'environment_token_used': False,
                    'recommendations': ['❌ Error checking security status']
                },
                status_code=500
            )

    def encrypt_token(self, request: TokenEncryptionRequest) -> SecurityResult:
        """
        Encrypt a plaintext bot token using the admin password.

        Args:
            request: TokenEncryptionRequest

        Returns:
            SecurityResult with encryption operation result
        """
        try:
            from utils.token_security import TokenSecurityManager

            security_manager = TokenSecurityManager()
            success = security_manager.encrypt_existing_plaintext_token()

            if success:
                # Log the action
                self._log_security_action(
                    action="TOKEN_ENCRYPT",
                    target="bot_token",
                    details="Bot token encrypted for enhanced security"
                )

                return SecurityResult(
                    success=True,
                    data={'message': 'Bot token encrypted successfully'}
                )
            else:
                return SecurityResult(
                    success=False,
                    error="Token encryption failed - check admin password is set",
                    status_code=400
                )

        except Exception as e:
            self.logger.error(f"Error encrypting token: {e}")
            return SecurityResult(
                success=False,
                error=str(e),
                status_code=500
            )

    def get_migration_help(self, request: MigrationHelpRequest) -> SecurityResult:
        """
        Get help information for migrating to environment variable.

        Args:
            request: MigrationHelpRequest

        Returns:
            SecurityResult with migration help information
        """
        try:
            from utils.token_security import TokenSecurityManager

            security_manager = TokenSecurityManager()
            migration_info = security_manager.migrate_to_environment_variable()

            # 🔒 SECURITY ENHANCEMENT: Log access but never log token content
            if migration_info['success']:
                self._log_security_action(
                    action="TOKEN_MIGRATION_HELP",
                    target="bot_token",
                    details="Migration help accessed for environment variable setup (token provided securely)"
                )

            # 🔒 SECURITY: Return token only if successfully decrypted
            response_data = {
                'success': migration_info['success'],
                'instructions': migration_info['instructions'],
                'error': migration_info.get('error')
            }

            # Only include token if decryption successful
            if migration_info['success'] and migration_info['plaintext_token']:
                response_data['token'] = migration_info['plaintext_token']

            return SecurityResult(
                success=True,
                data=response_data
            )

        except Exception as e:
            self.logger.error(f"Error getting migration help: {e}")
            return SecurityResult(
                success=False,
                error=str(e),
                data={
                    'success': False,
                    'instructions': []
                },
                status_code=500
            )

    def get_security_audit(self, request: SecurityAuditRequest) -> SecurityResult:
        """
        Get a comprehensive security audit of the current configuration.

        Args:
            request: SecurityAuditRequest with request object for HTTPS detection

        Returns:
            SecurityResult with comprehensive security audit information
        """
        try:
            from utils.token_security import TokenSecurityManager
            from services.config.config_service import load_config

            security_manager = TokenSecurityManager()
            token_status = security_manager.verify_token_encryption_status()

            config = load_config() or {}

            # Comprehensive security audit
            audit_results = self._perform_security_audit(token_status, config, request.request_object)

            return SecurityResult(
                success=True,
                data=audit_results
            )

        except Exception as e:
            self.logger.error(f"Error performing security audit: {e}")
            return SecurityResult(
                success=False,
                error=str(e),
                status_code=500
            )

    # ========================================================================
    # Private Helper Methods
    # ========================================================================

    def _perform_security_audit(self, token_status: Dict[str, Any], config: Dict[str, Any], request_object: Any) -> Dict[str, Any]:
        """Perform comprehensive security audit with scoring."""
        audit_results = {
            'token_security': token_status,
            'configuration_security': {
                'flask_secret_set': bool(os.getenv('FLASK_SECRET_KEY')),
                'admin_password_set': bool(config.get('web_ui_password_hash')),
                'docker_socket_accessible': os.path.exists('/var/run/docker.sock'),
                'running_as_non_root': os.getuid() != 0 if hasattr(os, 'getuid') else None,
                'https_enabled': request_object.is_secure if request_object else False,
            },
            'recommendations': [],
            'security_score': 0
        }

        # Calculate security score and recommendations
        score = self._calculate_security_score(audit_results)
        audit_results['security_score'] = min(score, 100)

        # Overall rating
        rating_info = self._get_security_rating(score)
        audit_results.update(rating_info)

        return audit_results

    def _calculate_security_score(self, audit_results: Dict[str, Any]) -> int:
        """Calculate security score based on various security factors."""
        score = 0
        token_status = audit_results['token_security']
        config_security = audit_results['configuration_security']

        # Token security (40 points)
        if token_status['environment_token_used']:
            score += 40
            audit_results['recommendations'].append('✅ Excellent: Using environment variable for token')
        elif token_status['is_encrypted']:
            score += 25
            audit_results['recommendations'].append('🔒 Good: Token is encrypted, consider environment variable')
        elif token_status['token_exists']:
            audit_results['recommendations'].append('⚠️ Critical: Encrypt or move token to environment variable')

        # Configuration security (30 points)
        if config_security['flask_secret_set']:
            score += 15
        else:
            audit_results['recommendations'].append('⚠️ Set FLASK_SECRET_KEY environment variable')

        if config_security['admin_password_set']:
            score += 15
        else:
            audit_results['recommendations'].append('⚠️ Set admin password for Web UI')

        # Transport security (15 points)
        if config_security['https_enabled']:
            score += 15
            audit_results['recommendations'].append('✅ HTTPS is enabled')
        else:
            audit_results['recommendations'].append('💡 Enable HTTPS for production use')

        # System security (15 points)
        if config_security['running_as_non_root']:
            score += 15
            audit_results['recommendations'].append('✅ Running as non-root user')
        elif config_security['running_as_non_root'] is False:
            audit_results['recommendations'].append('⚠️ Consider running as non-root user')

        return score

    def _get_security_rating(self, score: int) -> Dict[str, str]:
        """Get security rating based on score."""
        if score >= 85:
            return {'rating': 'Excellent', 'rating_class': 'success'}
        elif score >= 65:
            return {'rating': 'Good', 'rating_class': 'primary'}
        elif score >= 45:
            return {'rating': 'Fair', 'rating_class': 'warning'}
        else:
            return {'rating': 'Poor', 'rating_class': 'danger'}

    def _log_security_action(self, action: str, target: str, details: str):
        """Log security action for audit trail."""
        try:
            from services.infrastructure.action_logger import log_user_action
            from flask import session

            user = session.get('user', 'Unknown')
            log_user_action(
                action=action,
                target=target,
                user=user,
                source="Web UI - Security",
                details=details
            )
        except Exception as e:
            self.logger.warning(f"Could not log security action: {e}")


# Singleton instance
_security_service = None


def get_security_service() -> SecurityService:
    """Get the singleton SecurityService instance."""
    global _security_service
    if _security_service is None:
        _security_service = SecurityService()
    return _security_service