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

from flask import Blueprint, request, jsonify
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

    except (ImportError, AttributeError, RuntimeError) as e:
        # Service dependency errors (security_service unavailable, service method failures)
        logger.error(f"Service error in get_token_security_status route: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': 'Service error checking security status',
            'token_exists': False,
            'is_encrypted': False,
            'can_encrypt': False,
            'password_hash_available': False,
            'environment_token_used': False,
            'recommendations': ['❌ Service error checking security status']
        }), 500
    except (ValueError, TypeError, KeyError) as e:
        # Data errors (invalid response data, JSON serialization)
        logger.error(f"Data error in get_token_security_status route: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': 'Data error checking security status',
            'token_exists': False,
            'is_encrypted': False,
            'can_encrypt': False,
            'password_hash_available': False,
            'environment_token_used': False,
            'recommendations': ['❌ Data error checking security status']
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

    except (ImportError, AttributeError, RuntimeError) as e:
        # Service dependency errors (security_service unavailable, service method failures)
        logger.error(f"Service error in encrypt_token route: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': 'Service error encrypting token'
        }), 500
    except (ValueError, TypeError, KeyError) as e:
        # Data errors (encryption failures, response processing)
        logger.error(f"Data error in encrypt_token route: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': 'Data error encrypting token'
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

    except (ImportError, AttributeError, RuntimeError) as e:
        # Service dependency errors (security_service unavailable, service method failures)
        logger.error(f"Service error in get_migration_help route: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': 'Service error retrieving migration help',
            'instructions': []
        }), 500
    except (ValueError, TypeError, KeyError) as e:
        # Data errors (response processing failures, JSON serialization)
        logger.error(f"Data error in get_migration_help route: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': 'Data error retrieving migration help',
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

    except (ImportError, AttributeError, RuntimeError) as e:
        # Service dependency errors (security_service unavailable, service method failures)
        logger.error(f"Service error in get_security_audit route: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': 'Service error performing security audit'
        }), 500
    except (ValueError, TypeError, KeyError) as e:
        # Data errors (audit data processing, JSON serialization)
        logger.error(f"Data error in get_security_audit route: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': 'Data error performing security audit'
        }), 500