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

    logger.warning("⚠️  Environment variable DISCORD_BOT_TOKEN not found, falling back to config file")

    config_dir = Path(__file__).resolve().parents[2] / "config"
    bot_config_file = config_dir / "bot_config.json"

    try:
        if bot_config_file.exists():
            bot_config = json.loads(bot_config_file.read_text())
            plaintext_token = bot_config.get("bot_token")
            if plaintext_token and not str(plaintext_token).startswith("gAAAAA"):
                logger.info("Using plaintext bot token from bot_config.json")
                return str(plaintext_token)
    except Exception as exc:
        logger.debug("Could not read plaintext token: %s", exc)

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
        except Exception as exc:
            logger.warning("Error using ConfigManager: %s", exc)

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
    except Exception as exc:
        logger.error("Manual token decryption failed: %s", exc)

    logger.error("All token decryption methods failed")
    return None
