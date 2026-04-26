# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Translation Web Routes                         #
# ============================================================================ #
"""
Web Blueprint for Channel Translation System.
Provides API endpoints for channel pair management, settings, and testing.
"""

import logging
import os
import urllib.parse
from flask import Blueprint, jsonify, request
from app.auth import auth
from services.translation import (
    get_translation_config_service,
    get_translation_service
)
from services.translation.translation_config_service import SUPPORTED_LANGUAGES

logger = logging.getLogger('ddc.web.translation_routes')

translation_bp = Blueprint('translation_bp', __name__)

# SSRF protection: only outbound HTTPS calls to known translation providers are allowed.
_ALLOWED_TRANSLATION_HOSTS = {
    'api.deepl.com',
    'api-free.deepl.com',
    'translation.googleapis.com',
    'api.cognitive.microsofttranslator.com',
}


def _is_allowed_translation_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(url)
    except (ValueError, TypeError):
        return False
    return parsed.scheme == 'https' and parsed.hostname in _ALLOWED_TRANSLATION_HOSTS


# --- Channel Pair Management ---

@translation_bp.route('/api/translation/pairs', methods=['GET'])
@auth.login_required
def get_pairs():
    """Get all configured channel translation pairs."""
    try:
        config_service = get_translation_config_service()
        pairs = config_service.get_pairs()
        return jsonify({'pairs': [p.to_dict() for p in pairs]})
    except Exception as e:
        logger.error(f"Error loading pairs: {e}", exc_info=True)
        return jsonify({'pairs': [], 'error': 'Failed to load pairs'}), 500


@translation_bp.route('/api/translation/pairs', methods=['POST'])
@auth.login_required
def create_pair():
    """Create a new channel translation pair."""
    config_service = get_translation_config_service()
    data = request.json
    if not data:
        return jsonify({'success': False, 'error': 'Request body is required'}), 400

    result = config_service.add_pair(data)
    if result.success:
        return jsonify({'success': True, 'pair': result.data.to_dict()}), 201
    return jsonify({'success': False, 'error': result.error}), 400


@translation_bp.route('/api/translation/pairs/<pair_id>', methods=['PUT'])
@auth.login_required
def update_pair(pair_id):
    """Update an existing channel translation pair."""
    config_service = get_translation_config_service()
    data = request.json
    if not data:
        return jsonify({'success': False, 'error': 'Request body is required'}), 400

    # Check existence first
    if not config_service.get_pair(pair_id):
        return jsonify({'success': False, 'error': 'Pair not found'}), 404

    result = config_service.update_pair(pair_id, data)
    if result.success:
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': result.error}), 400


@translation_bp.route('/api/translation/pairs/<pair_id>', methods=['DELETE'])
@auth.login_required
def delete_pair(pair_id):
    """Delete a channel translation pair."""
    config_service = get_translation_config_service()

    # Check existence first
    if not config_service.get_pair(pair_id):
        return jsonify({'success': False, 'error': 'Pair not found'}), 404

    result = config_service.delete_pair(pair_id)
    if result.success:
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': result.error}), 400


@translation_bp.route('/api/translation/pairs/<pair_id>/toggle', methods=['POST'])
@auth.login_required
def toggle_pair(pair_id):
    """Toggle a pair's enabled state."""
    config_service = get_translation_config_service()

    # Check existence first
    if not config_service.get_pair(pair_id):
        return jsonify({'success': False, 'error': 'Pair not found'}), 404

    result = config_service.toggle_pair(pair_id)
    if result.success:
        # Reset auto-disable if user re-enables
        translation_service = get_translation_service()
        translation_service.reset_auto_disabled(pair_id)
        return jsonify({'success': True, 'enabled': result.data['enabled']})
    return jsonify({'success': False, 'error': result.error}), 400


# --- Settings ---

@translation_bp.route('/api/translation/settings', methods=['GET'])
@auth.login_required
def get_settings():
    """Get global translation settings."""
    try:
        config_service = get_translation_config_service()
        settings = config_service.get_settings()
        # Never expose the actual API key — only whether one is configured
        settings_dict = settings.to_dict()
        has_env_key = bool(os.environ.get(settings.api_key_env, '').strip())
        has_config_key = bool(settings.api_key_encrypted)
        settings_dict['api_key_configured'] = has_env_key or has_config_key
        settings_dict['api_key_source'] = 'env' if has_env_key else ('config' if has_config_key else 'none')
        settings_dict.pop('api_key_encrypted', None)
        return jsonify({'settings': settings_dict})
    except Exception as e:
        logger.error(f"Error loading settings: {e}", exc_info=True)
        return jsonify({'settings': {}, 'error': 'Failed to load settings'}), 500


@translation_bp.route('/api/translation/settings', methods=['POST'])
@auth.login_required
def update_settings():
    """Update global translation settings."""
    config_service = get_translation_config_service()
    data = request.json
    if not data:
        return jsonify({'success': False, 'error': 'Request body is required'}), 400

    result = config_service.update_settings(data)
    if result.success:
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': result.error}), 400


@translation_bp.route('/api/translation/apikey', methods=['POST'])
@auth.login_required
def save_api_key():
    """Save or clear the translation API key (encrypted in config)."""
    data = request.json
    if not data:
        return jsonify({'success': False, 'error': 'Request body is required'}), 400

    api_key = data.get('api_key', '').strip()
    config_service = get_translation_config_service()

    try:
        if not api_key:
            # Clear the stored key
            result = config_service.save_api_key(None)
        else:
            result = config_service.save_api_key(api_key)

        if result.success:
            return jsonify({'success': True})
        return jsonify({'success': False, 'error': result.error}), 400
    except Exception as e:
        logger.error(f"Error saving API key: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Failed to save API key'}), 500


# --- Test ---

@translation_bp.route('/api/translation/test', methods=['POST'])
@auth.login_required
def test_translation():
    """Test translation with current settings (synchronous via urllib)."""
    import urllib.request
    import urllib.parse
    import urllib.error
    import json as json_lib
    import ssl

    # Create SSL context (gevent monkey-patches requests/ssl causing recursion)
    ssl_ctx = ssl.create_default_context()

    def _api_post(url, headers=None, json_body=None, form_data=None, params=None, timeout=15):
        """Simple HTTP POST without requests library (avoids gevent recursion)."""
        # SSRF guard — reject anything not on the explicit translation-provider allow-list.
        if not _is_allowed_translation_url(url):
            logger.warning("Blocked outbound translation request to disallowed URL: %s", url)
            return 400, None
        if params:
            url = url + '?' + urllib.parse.urlencode(params)
        if json_body is not None:
            body = json_lib.dumps(json_body).encode('utf-8')
            headers = headers or {}
            headers['Content-Type'] = 'application/json'
        elif form_data is not None:
            body = urllib.parse.urlencode(form_data).encode('utf-8')
            headers = headers or {}
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
        else:
            body = b''
        req = urllib.request.Request(url, data=body, headers=headers or {}, method='POST')
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ssl_ctx) as resp:
                return resp.status, json_lib.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            return e.code, None

    data = request.json
    if not data:
        return jsonify({'success': False, 'error': 'Request body is required'}), 400

    text = data.get('text', '').strip()
    target_lang = data.get('target_language', 'DE')
    source_lang = data.get('source_language')

    if not text:
        return jsonify({'success': False, 'error': 'Text is required'}), 400
    if len(text) > 1000:
        return jsonify({'success': False, 'error': 'Test text too long (max 1000 chars)'}), 400

    config_service = get_translation_config_service()
    settings = config_service.get_settings()

    # Resolve API key
    api_key = os.environ.get(settings.api_key_env, '').strip()
    if not api_key and settings.api_key_encrypted:
        stored = settings.api_key_encrypted
        if stored.startswith('gAAAAA'):
            try:
                fernet = config_service._get_encryption_key()
                api_key = fernet.decrypt(stored.encode()).decode()
            except Exception:
                pass
        else:
            api_key = stored

    if not api_key:
        return jsonify({'success': False, 'error': 'No API key configured'}), 400

    try:
        provider = settings.provider
        timeout = 15

        if provider == 'deepl':
            payload = {"text": [text], "target_lang": target_lang.upper()}
            if source_lang:
                payload["source_lang"] = source_lang.upper()
            status, resp_data = _api_post(
                settings.deepl_api_url,
                headers={"Authorization": f"DeepL-Auth-Key {api_key}"},
                json_body=payload, timeout=timeout
            )
            if status == 200 and resp_data:
                t = resp_data.get("translations", [{}])[0]
                return jsonify({
                    'success': True,
                    'translated_text': t.get("text", ""),
                    'detected_language': t.get("detected_source_language"),
                    'provider': 'DeepL',
                    'characters_used': len(text)
                })
            return jsonify({'success': False, 'error': f"DeepL API error: HTTP {status}"}), 400

        elif provider == 'google':
            form = {"q": text, "target": target_lang.lower()[:2], "format": "text"}
            if source_lang:
                form["source"] = source_lang.lower()[:2]
            status, resp_data = _api_post(
                "https://translation.googleapis.com/language/translate/v2",
                params={"key": api_key},
                form_data=form, timeout=timeout
            )
            if status == 200 and resp_data:
                t = resp_data.get("data", {}).get("translations", [{}])[0]
                return jsonify({
                    'success': True,
                    'translated_text': t.get("translatedText", ""),
                    'detected_language': t.get("detectedSourceLanguage"),
                    'provider': 'Google',
                    'characters_used': len(text)
                })
            return jsonify({'success': False, 'error': f"Google API error: HTTP {status}"}), 400

        elif provider == 'microsoft':
            ms_params = {"api-version": "3.0", "to": target_lang.lower()[:2]}
            if source_lang:
                ms_params["from"] = source_lang.lower()[:2]
            status, resp_data = _api_post(
                "https://api.cognitive.microsofttranslator.com/translate",
                params=ms_params,
                json_body=[{"text": text}],
                headers={"Ocp-Apim-Subscription-Key": api_key},
                timeout=timeout
            )
            if status == 200 and resp_data:
                if resp_data and resp_data[0].get("translations"):
                    t = resp_data[0]["translations"][0]
                    detected = resp_data[0].get("detectedLanguage", {}).get("language")
                    return jsonify({
                        'success': True,
                        'translated_text': t.get("text", ""),
                        'detected_language': detected,
                        'provider': 'Microsoft',
                        'characters_used': len(text)
                    })
            return jsonify({'success': False, 'error': f"Microsoft API error: HTTP {status}"}), 400

        else:
            return jsonify({'success': False, 'error': f"Unknown provider: {provider}"}), 400

    except (urllib.error.URLError, TimeoutError) as e:
        logger.error(f"Translation API error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Translation API error. Check server logs.'}), 400
    except Exception as e:
        logger.error(f"Error testing translation: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Translation test failed. Check server logs.'}), 500


# --- Languages ---

@translation_bp.route('/api/translation/languages', methods=['GET'])
@auth.login_required
def get_languages():
    """Get supported languages list."""
    try:
        return jsonify({'languages': SUPPORTED_LANGUAGES})
    except Exception as e:
        logger.error(f"Error loading languages: {e}", exc_info=True)
        return jsonify({'languages': {}}), 500
