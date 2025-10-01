# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Security Routes for DockerDiscordControl
Handles token security, encryption status, and migration features.
"""

from flask import Blueprint, request, jsonify, render_template
from services.config.config_service import load_config
from app.auth import auth
import logging

logger = logging.getLogger(__name__)

# Create blueprint
security_bp = Blueprint('security', __name__, url_prefix='/api')

@security_bp.route('/token-security-status', methods=['GET'])
@auth.login_required
def get_token_security_status():
    """Get the current security status of the bot token using SecurityService."""
    try:
        # Use SecurityService for business logic
        from services.web.security_service import get_security_service, TokenSecurityStatusRequest

        service = get_security_service()
        request_obj = TokenSecurityStatusRequest()

        # Get token security status through service
        result = service.get_token_security_status(request_obj)

        if result.success:
            return jsonify({
                'success': True,
                **result.data
            })
        else:
            return jsonify({
                'success': False,
                'error': result.error,
                **result.data
            }), result.status_code

    except Exception as e:
        logger.error(f"Error in get_token_security_status route: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'token_exists': False,
            'is_encrypted': False,
            'can_encrypt': False,
            'password_hash_available': False,
            'environment_token_used': False,
            'recommendations': ['❌ Error checking security status']
        }), 500

@security_bp.route('/encrypt-token', methods=['POST'])
@auth.login_required
def encrypt_token():
    """Encrypt a plaintext bot token using SecurityService."""
    try:
        # Use SecurityService for business logic
        from services.web.security_service import get_security_service, TokenEncryptionRequest

        service = get_security_service()
        request_obj = TokenEncryptionRequest()

        # Encrypt token through service
        result = service.encrypt_token(request_obj)

        if result.success:
            return jsonify({
                'success': True,
                **result.data
            })
        else:
            return jsonify({
                'success': False,
                'error': result.error
            }), result.status_code

    except Exception as e:
        logger.error(f"Error in encrypt_token route: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@security_bp.route('/migration-help', methods=['GET'])
@auth.login_required
def get_migration_help():
    """Get help information for migrating to environment variable using SecurityService."""
    try:
        # Use SecurityService for business logic
        from services.web.security_service import get_security_service, MigrationHelpRequest

        service = get_security_service()
        request_obj = MigrationHelpRequest()

        # Get migration help through service
        result = service.get_migration_help(request_obj)

        if result.success:
            return jsonify(result.data)
        else:
            return jsonify({
                'success': False,
                'error': result.error,
                **result.data
            }), result.status_code

    except Exception as e:
        logger.error(f"Error in get_migration_help route: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'instructions': []
        }), 500

@security_bp.route('/security-audit', methods=['GET'])
@auth.login_required
def get_security_audit():
    """Get a comprehensive security audit using SecurityService."""
    try:
        # Use SecurityService for business logic
        from services.web.security_service import get_security_service, SecurityAuditRequest

        service = get_security_service()
        request_obj = SecurityAuditRequest(request_object=request)

        # Get security audit through service
        result = service.get_security_audit(request_obj)

        if result.success:
            return jsonify({
                'success': True,
                **result.data
            })
        else:
            return jsonify({
                'success': False,
                'error': result.error
            }), result.status_code

    except Exception as e:
        logger.error(f"Error in get_security_audit route: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500