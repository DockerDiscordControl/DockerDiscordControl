# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Internationalization service for the Web UI."""

import json
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

import logging
from utils.logging_utils import setup_logger

logger = setup_logger('ddc.i18n_service', level=logging.DEBUG)

_LOCALES_DIR = Path(__file__).resolve().parent.parent.parent / 'locales'

_instance = None
_instance_lock = threading.Lock()


class I18nService:
    """Loads and serves translations for the Web UI from JSON locale files."""

    def __init__(self):
        self._translations: Dict[str, Dict[str, str]] = {}
        self._meta: Dict[str, Dict[str, Any]] = {}
        self._load_meta()
        self._load_translations()

    def _load_meta(self):
        """Load language metadata from meta.json."""
        meta_file = _LOCALES_DIR / 'meta.json'
        if meta_file.exists():
            try:
                with open(meta_file, 'r', encoding='utf-8') as f:
                    self._meta = json.load(f)
                logger.debug(f"Loaded metadata for {len(self._meta)} languages")
            except (json.JSONDecodeError, OSError) as e:
                logger.error(f"Failed to load meta.json: {e}")

    def _load_translations(self):
        """Load all translation JSON files."""
        if not _LOCALES_DIR.exists():
            logger.warning(f"Locales directory not found: {_LOCALES_DIR}")
            return

        for json_file in sorted(_LOCALES_DIR.glob('*.json')):
            if json_file.stem.startswith('_') or json_file.stem == 'meta':
                continue
            lang_code = json_file.stem
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    self._translations[lang_code] = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                logger.error(f"Failed to load locale '{lang_code}': {e}")

        logger.info(f"Web i18n loaded: {sorted(self._translations.keys())}")

    def reload(self):
        """Reload all translations from disk."""
        self._load_meta()
        self._load_translations()
        logger.info("Web i18n reloaded")

    def translate(self, key: str, lang: str = 'en', **kwargs) -> str:
        """Translate a key for the web UI.

        Lookup chain: lang -> en -> return key as-is.
        Supports {placeholder} substitution via kwargs.
        """
        result = None

        # Try requested language
        if lang in self._translations:
            result = self._translations[lang].get(key)

        # Fallback to English
        if not result and lang != 'en' and 'en' in self._translations:
            result = self._translations['en'].get(key)

        # Last resort: return the key itself
        if not result:
            result = key

        # Substitute placeholders
        if kwargs:
            try:
                result = result.format(**kwargs)
            except (KeyError, IndexError):
                pass

        return result

    def get_js_translations(self, lang: str = 'en') -> Dict[str, str]:
        """Get translations for JS (keys starting with 'js.')."""
        js_trans = {}
        lang_dict = self._translations.get(lang, {})
        en_dict = self._translations.get('en', {})

        # Collect all js.* keys from English (source of truth)
        for key in en_dict:
            if key.startswith('js.'):
                short_key = key[3:]  # strip 'js.' prefix
                value = lang_dict.get(key) or en_dict.get(key, key)
                js_trans[short_key] = value

        return js_trans

    def get_js_translations_json(self, lang: str = 'en') -> str:
        """Get JS translations as JSON string for embedding in templates."""
        return json.dumps(self.get_js_translations(lang), ensure_ascii=False)

    def get_available_languages(self) -> List[Dict[str, str]]:
        """Return list of available languages with metadata."""
        languages = []
        for code, meta in sorted(self._meta.items(), key=lambda x: x[1].get('name', '')):
            languages.append({
                'code': code,
                'name': meta.get('name', code),
                'native': meta.get('native', code),
                'rtl': meta.get('rtl', False),
            })
        return languages

    def get_language_meta(self, code: str) -> Optional[Dict[str, Any]]:
        """Get metadata for a specific language."""
        return self._meta.get(code)

    def is_rtl(self, lang: str) -> bool:
        """Check if a language is right-to-left."""
        meta = self._meta.get(lang, {})
        return meta.get('rtl', False)


def get_i18n_service() -> I18nService:
    """Get or create the singleton I18nService instance."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = I18nService()
    return _instance
