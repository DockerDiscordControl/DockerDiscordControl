# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Flask i18n integration - context processor for Jinja2 templates."""

import logging

from flask import Flask, g

from services.config.config_service import load_config
from services.web.i18n_service import get_i18n_service

logger = logging.getLogger(__name__)


def _request_scoped_config() -> dict:
    """Return the active config, cached on flask.g for the current request.

    Without this cache the i18n context processor reloads the full config
    from disk on *every* template render — multiple times per request when
    a page renders nested templates.
    """
    cached = getattr(g, "_ddc_request_config", None)
    if cached is not None:
        return cached
    try:
        config = load_config()
    except Exception as e:  # noqa: BLE001 - a broken config must not take the panel down
        # Broad on purpose, but no longer silent. This runs on every template
        # render; without a line here the panel simply showed English and
        # default settings, looking healthy, and nothing anywhere said why
        # (review C20).
        logger.warning("Could not load the configuration for this request "
                       "(%s: %s) - rendering with defaults.", type(e).__name__, e)
        config = {}
    g._ddc_request_config = config
    return config


def register_i18n(app: Flask) -> None:
    """Register i18n context processor to inject translation helpers into all templates."""

    @app.context_processor
    def inject_i18n():
        svc = get_i18n_service()

        config = _request_scoped_config()

        ui_lang = config.get('ui_language', 'en')

        def web_translate(key, **kwargs):
            return svc.translate(key, lang=ui_lang, **kwargs)

        return {
            '_t': web_translate,
            'ui_language': ui_lang,
            'ui_rtl': svc.is_rtl(ui_lang),
            'available_languages': svc.get_available_languages(),
            'js_translations_json': svc.get_js_translations_json(ui_lang),
        }
