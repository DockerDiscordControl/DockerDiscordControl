# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                      #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""One way to read an Advanced Setting - config first, environment second.

The panel offers 23 ``DDC_*`` keys and writes them into
``config['advanced_settings']`` (config_form_parser_service.py:415-425). Nine
places read three of those keys straight from ``os.environ`` instead, so they
never saw what the user had set: the setting worked in the web part and was
silently ineffective in the Discord part. No error, no hint - the classic "the
user notices nothing" case.

``app/utils/web_helpers.py:_get_advanced_setting`` already did the right thing,
and cogs/status_handlers.py:341 even imports it - but that module pulls ``docker``
and ``werkzeug`` at import time, so using it from the Discord side drags half the
web part along. Hence this module: no imports beyond the standard library at
module level.

Two deliberate differences from the original:

* The config service is imported INSIDE the function. Every other module in
  ``utils/`` does it that way, and a module-level import here would read
  configuration during import - the very thing fixed in docker_utils.py today.
* A fallback to the environment is LOGGED. The original swallowed the failure
  silently, which is exactly the "values quietly tidied away" pattern this
  programme hunts. Removing one silent site while building the next one would
  be a poor trade.
"""

import logging
import os
from typing import Any, Callable

logger = logging.getLogger('ddc.settings')


def get_setting(key: str, default: Any, value_type: Callable[[Any], Any] = int) -> Any:
    """Read ``key`` from the Advanced Settings, falling back to the environment.

    Order: ``config['advanced_settings']`` -> ``os.environ`` -> ``default``.

    Args:
        key: the setting name, e.g. ``DDC_DOCKER_CACHE_DURATION``.
        default: value to use when neither source has it.
        value_type: ``int``, ``float``, ``str`` or ``bool``. ``bool`` accepts the
            usual textual forms because the config stores strings.

    Never raises: a broken setting must not take a service down with it. What it
    does instead of raising is say so.
    """
    raw_value = None
    source = None

    try:
        from services.config.config_service import get_config_service
        advanced = get_config_service().get_config().get('advanced_settings') or {}
        if key in advanced:
            raw_value, source = advanced[key], 'config'
    except Exception as exc:  # noqa: BLE001 - see the docstring: never raise here
        # Not silent: this is why a panel setting may appear to have no effect.
        logger.warning(
            "Could not read advanced setting %s from the configuration (%s: %s) - "
            "falling back to environment/default.", key, type(exc).__name__, exc,
        )

    if raw_value is None and key in os.environ:
        raw_value, source = os.environ[key], 'environment'

    if raw_value is None:
        return _convert(key, default, value_type, default)

    value = _convert(key, raw_value, value_type, default)
    logger.debug("Advanced setting %s = %r (from %s)", key, value, source)
    return value


def _convert(key: str, raw_value: Any, value_type: Callable[[Any], Any], default: Any) -> Any:
    """Convert to the wanted type; on nonsense fall back to ``default`` loudly."""
    try:
        if value_type is bool:
            if isinstance(raw_value, bool):
                return raw_value
            return str(raw_value).strip().lower() in ('true', '1', 'yes', 'on')
        return value_type(raw_value)
    except (TypeError, ValueError):
        logger.warning(
            "Advanced setting %s has the unusable value %r - using the default %r instead.",
            key, raw_value, default,
        )
        try:
            return value_type(default) if value_type is not bool else bool(default)
        except (TypeError, ValueError):
            return default
