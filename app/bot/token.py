# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Token retrieval helpers for the Discord bot."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from .runtime import BotRuntime


def get_decrypted_bot_token(runtime: BotRuntime) -> Optional[str]:
    """Resolve the Discord bot token using the available fallbacks."""

    logger = runtime.logger
    config = runtime.config
    dependencies = runtime.dependencies

    token_from_env = os.getenv("DISCORD_BOT_TOKEN")
    if token_from_env:
        logger.info("✅ Using bot token from environment variable DISCORD_BOT_TOKEN (secure)")
        return token_from_env.strip()

    # NOT a warning. Typing the token into the Web UI is the normal,
    # documented way of running DDC - config.json is where the panel saves
    # it, not a degraded fallback. This was the ONLY warning in 579 lines of
    # a healthy log, which teaches its reader that warnings are normal and
    # makes the next real one - a token that will not decrypt - invisible.
    logger.info("No DISCORD_BOT_TOKEN in the environment - reading the token from the configuration")

    # Via utils/config_paths.py (DDC_CONFIG_DIR), where config_service keeps
    # bot_config.json - derived from __file__ before, blind to the variable.
    from utils.config_paths import get_config_dir
    config_dir = get_config_dir()
    bot_config_file = config_dir / "bot_config.json"

    # The token saved in the Web UI (config.json, decrypted by the config service)
    # comes first. A leftover plaintext token in the legacy bot_config.json is only
    # a fallback - otherwise it would shadow every token saved in the Web UI.
    token = config.get("bot_token_decrypted_for_usage")
    if token:
        logger.info("Using bot token from initial config loading")
        return str(token)

    config_service_factory = dependencies.config_service_factory
    if config_service_factory:
        try:
            logger.info("Attempting to use ConfigManager for token decryption")
            config_service = config_service_factory()
            config_data = config_service.get_config(force_reload=True)

            token = config_data.get("bot_token_decrypted_for_usage")
            if token:
                logger.info("Successfully got pre-decrypted token from ConfigService")
                return str(token)

            encrypted_token = config_data.get("bot_token")
            password_hash = config_data.get("web_ui_password_hash")
            if encrypted_token and password_hash:
                decrypted = config_service.decrypt_token(encrypted_token, password_hash)
                if decrypted:
                    logger.info("Successfully decrypted token using ConfigService")
                    return str(decrypted)
        except Exception as e:  # noqa: BLE001
            # Broad on purpose, and it is the CONTRACT of this function rather
            # than laziness: it resolves a token through a chain of fallbacks
            # and answers "a token or None", so a fallback that fails must lead
            # to the next one, never out of here.
            #
            # What made this necessary: decrypt_token raises TokenEncryptionError
            # when the stored token and the stored password hash do not belong
            # together - a restored backup, a hand-edited config, a password
            # change that did not finish. That descends from ConfigServiceError
            # -> DDCBaseException, so the tuple that used to stand here
            # (IOError, OSError, PermissionError, RuntimeError, JSONDecodeError)
            # could never catch it. It escaped into bot.py's retry loop, which
            # has no handler of its own - and that loop exists for exactly this
            # case; its own message says "or could not be decrypted" (E7).
            #
            # Caught by class and not by import: tests/unit/app_modules replaces
            # the whole services package with stubs, so importing
            # services.exceptions here breaks that group outright.
            logger.warning("Could not get the bot token from the ConfigService "
                           "(%s: %s). Fix it in the Web UI - the bot keeps retrying.",
                           type(e).__name__, e)

    try:
        if bot_config_file.exists():
            bot_config = json.loads(bot_config_file.read_text())
            plaintext_token = bot_config.get("bot_token")
            if plaintext_token and not str(plaintext_token).startswith("gAAAAA"):
                logger.info("Using plaintext bot token from legacy bot_config.json (no token in config.json)")
                return str(plaintext_token)
    except (AttributeError, IOError, KeyError, OSError, PermissionError, RuntimeError, TypeError, json.JSONDecodeError) as e:
        logger.debug("Could not read plaintext token: %s", e)

    try:
        logger.info("Attempting manual token decryption")
        web_config_file = config_dir / "web_config.json"

        if bot_config_file.exists() and web_config_file.exists() and config_service_factory:
            bot_config = json.loads(bot_config_file.read_text())
            web_config = json.loads(web_config_file.read_text())

            encrypted_token = bot_config.get("bot_token")
            password_hash = web_config.get("web_ui_password_hash")

            if encrypted_token and password_hash:
                config_service = config_service_factory()
                decrypted = config_service.decrypt_token(encrypted_token, password_hash)
                if decrypted:
                    logger.info("Successfully performed direct token decryption")
                    return str(decrypted)
    except Exception as e:  # noqa: BLE001
        # Same reason as above: this used to catch RuntimeError only, and
        # decrypt_token raises TokenEncryptionError (review E7).
        logger.error("Manual token decryption failed (%s: %s)", type(e).__name__, e)

    logger.error("All token decryption methods failed")
    return None
