# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
import json
import os
import threading
from pathlib import Path
from services.config.config_service import load_config
import logging
from utils.logging_utils import setup_logger

logger = setup_logger('ddc.translation_manager', level=logging.DEBUG)

# Resolve locales directory (works both in dev and Docker /app/locales)
_LOCALES_DIR = Path(__file__).resolve().parent.parent / 'locales'


class TranslationManager:
    """Singleton class for translations loaded from JSON files."""
    _instance = None
    _translations = None
    _current_language = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(TranslationManager, cls).__new__(cls)
            cls._instance._load_translations()
        return cls._instance

    def _load_translations(self):
        """Load translations from JSON files in locales/ directory."""
        self._translations = {}
        locales_dir = _LOCALES_DIR

        if not locales_dir.exists():
            logger.warning(f"Locales directory not found: {locales_dir}")
            return

        for json_file in sorted(locales_dir.glob('*.json')):
            if json_file.stem.startswith(('_', 'meta')):
                continue
            lang_code = json_file.stem
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    self._translations[lang_code] = json.load(f)
                logger.debug(f"Loaded {len(self._translations[lang_code])} translations for '{lang_code}'")
            except (json.JSONDecodeError, OSError) as e:
                logger.error(f"Failed to load translations for '{lang_code}': {e}")

        logger.info(f"Translations loaded: {sorted(self._translations.keys())} ({len(self._translations)} languages)")

    def reload_translations(self):
        """Reload all translation files from disk (hot-reload)."""
        with self._lock:
            self._load_translations()
            logger.info(f"Translations reloaded: {sorted(self._translations.keys())}")

    def get_available_languages(self):
        """Return list of available language codes."""
        return sorted(self._translations.keys())

    def get_current_language(self):
        """Returns the current bot language from configuration."""
        try:
            config = load_config()
        except Exception:
            return 'en'

        lang = config.get('language', 'en')
        if lang not in self._translations:
            lang = 'en'
        self._current_language = lang
        return lang

    def _(self, text):
        """Translate text to the current bot language."""
        lang = self.get_current_language()
        return self.translate(text, lang)

    def translate(self, text, lang=None):
        """Translate text to a specific language with fallback chain."""
        if lang is None:
            lang = self.get_current_language()

        # Try requested language
        if lang in self._translations:
            result = self._translations[lang].get(text)
            if result:
                return result

        # Fallback to English
        if lang != 'en' and 'en' in self._translations:
            result = self._translations['en'].get(text)
            if result:
                return result

        # Return original text as last resort
        return text


# Global instance
translation_manager = TranslationManager()


def _(text):
    """Global translation function for bot strings."""
    return translation_manager._(text)


def get_translations():
    """Returns the translation dictionary with all languages."""
    return translation_manager._translations
