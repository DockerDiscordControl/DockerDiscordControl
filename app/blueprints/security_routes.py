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
from app.auth import auth
import logging

logger = logging.getLogger(__name__)

# Create blueprint
security_bp = Blueprint('security', __name__, url_prefix='/api')

@security_bp.route('/token-security-status', methods=['GET'])
@auth.login_required
def get_token_security_status():
    """Get the current security status of the bot token."""
    try:
        from utils.token_security import TokenSecurityManager
        
        security_manager = TokenSecurityManager()
        status = security_manager.verify_token_encryption_status()
        
        return jsonify({
            'success': True,
            **status
        })
        
    except Exception as e:
        logger.error(f"Error getting token security status: {e}")
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
    """Encrypt a plaintext bot token using the admin password."""
    try:
        from utils.token_security import TokenSecurityManager
        
        security_manager = TokenSecurityManager()
        success = security_manager.encrypt_existing_plaintext_token()
        
        if success:
            # Log the action
            from services.infrastructure.action_logger import log_user_action
            from flask import session
            user = session.get('user', 'Unknown')
            
            log_user_action(
                action="TOKEN_ENCRYPT",
                target="bot_token", 
                user=user,
                source="Web UI - Security",
                details="Bot token encrypted for enhanced security"
            )
            
            return jsonify({
                'success': True,
                'message': 'Bot token encrypted successfully'
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Token encryption failed - check admin password is set'
            }), 400
            
    except Exception as e:
        logger.error(f"Error encrypting token: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@security_bp.route('/migration-help', methods=['GET'])
@auth.login_required
def get_migration_help():
    """Get help information for migrating to environment variable."""
    try:
        from utils.token_security import TokenSecurityManager
        
        security_manager = TokenSecurityManager()
        migration_info = security_manager.migrate_to_environment_variable()
        
        # 🔒 SECURITY ENHANCEMENT: Log access but never log token content
        if migration_info['success']:
            from services.infrastructure.action_logger import log_user_action
            from flask import session
            user = session.get('user', 'Unknown')
            
            log_user_action(
                action="TOKEN_MIGRATION_HELP",
                target="bot_token",
                user=user, 
                source="Web UI - Security",
                details="Migration help accessed for environment variable setup (token provided securely)"
            )
        
        # 🔒 SECURITY: Return token only if successfully decrypted
        response_data = {
            'success': migration_info['success'],
            'instructions': migration_info['instructions'],
            'error': migration_info.get('error')
        }
        
        # Only include token if request is authenticated and decryption successful
        if migration_info['success'] and migration_info['plaintext_token']:
            response_data['token'] = migration_info['plaintext_token']
        
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"Error getting migration help: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'instructions': []
        }), 500

@security_bp.route('/security-audit', methods=['GET'])
@auth.login_required  
def get_security_audit():
    """Get a comprehensive security audit of the current configuration."""
    try:
        from utils.token_security import TokenSecurityManager
        
        security_manager = TokenSecurityManager()
        token_status = security_manager.verify_token_encryption_status()
        
        # Additional security checks
        import os
        from utils.config_cache import get_cached_config
        
        config = get_cached_config() or {}
        
        audit_results = {
            'token_security': token_status,
            'configuration_security': {
                'flask_secret_set': bool(os.getenv('FLASK_SECRET_KEY')),
                'admin_password_set': bool(config.get('web_ui_password_hash')),
                'docker_socket_accessible': os.path.exists('/var/run/docker.sock'),
                'running_as_non_root': os.getuid() != 0 if hasattr(os, 'getuid') else None,
                'https_enabled': request.is_secure,
            },
            'recommendations': [],
            'security_score': 0
        }
        
        # Calculate security score and recommendations
        score = 0
        
        # Token security (40 points)
        if token_status['environment_token_used']:
            score += 40
            audit_results['recommendations'].append('✅ Excellent: Using environment variable for token')
        elif token_status['is_encrypted']:
            score += 25
            audit_results['recommendations'].append('🔒 Good: Token is encrypted, consider environment variable')
        elif token_status['token_exists']:
            audit_results['recommendations'].append('⚠️  Critical: Encrypt or move token to environment variable')
        
        # Configuration security (30 points)
        if audit_results['configuration_security']['flask_secret_set']:
            score += 15
        else:
            audit_results['recommendations'].append('⚠️  Set FLASK_SECRET_KEY environment variable')
            
        if audit_results['configuration_security']['admin_password_set']:
            score += 15
        else:
            audit_results['recommendations'].append('⚠️  Set admin password for Web UI')
        
        # Transport security (15 points)
        if audit_results['configuration_security']['https_enabled']:
            score += 15
            audit_results['recommendations'].append('✅ HTTPS is enabled')
        else:
            audit_results['recommendations'].append('💡 Enable HTTPS for production use')
        
        # System security (15 points)
        if audit_results['configuration_security']['running_as_non_root']:
            score += 15
            audit_results['recommendations'].append('✅ Running as non-root user')
        elif audit_results['configuration_security']['running_as_non_root'] is False:
            audit_results['recommendations'].append('⚠️  Consider running as non-root user')
        
        audit_results['security_score'] = min(score, 100)
        
        # Overall rating
        if score >= 85:
            audit_results['rating'] = 'Excellent'
            audit_results['rating_class'] = 'success'
        elif score >= 65:
            audit_results['rating'] = 'Good' 
            audit_results['rating_class'] = 'primary'
        elif score >= 45:
            audit_results['rating'] = 'Fair'
            audit_results['rating_class'] = 'warning'
        else:
            audit_results['rating'] = 'Poor'
            audit_results['rating_class'] = 'danger'
        
        return jsonify({
            'success': True,
            **audit_results
        })
        
    except Exception as e:
        logger.error(f"Error performing security audit: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500