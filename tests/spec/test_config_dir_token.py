# -*- coding: utf-8 -*-
"""Token check, token migration and the token fallback must follow
``DDC_CONFIG_DIR``.

NO ``@covers`` marker: that would be a new guarantee, and those are the
operator's decision.

THE FINDING. ``config_service`` writes ``bot_config.json`` and
``web_config.json`` into the directory from the variable. These three paths read
at the old location (``Path(__file__).parents[N] / "config"``)::

    TokenSecurityManager.verify_token_encryption_status  token_security.py:169
    TokenSecurityManager.encrypt_existing_plaintext_token  token_security.py:72
    get_decrypted_bot_token (fallback bot_config.json)   app/bot/token.py:34

Both methods first only check whether the files EXIST. If they are missing at
the old location, the status reports "no token" (and the security display rates
a setup that does not exist - Z9 territory), and the startup migration ends
with "nothing to do": silently and successfully, while a plaintext token sits in
the real directory.

HOW IT IS CHECKED HERE: the test creates the files in the configured directory.
``DISCORD_BOT_TOKEN`` is removed, otherwise the bot path takes it first.
The encryption is a recorder - what is checked is THAT and WHERE something is
written, not the cryptography.
"""

import json
import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.bot import token as bot_token
from utils.token_security import TokenSecurityManager

PLAINTEXT = "plaintext-token-probe"


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    target = tmp_path / "own_config"
    target.mkdir()
    monkeypatch.setenv("DDC_CONFIG_DIR", str(target))
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    (target / "bot_config.json").write_text(json.dumps({"bot_token": PLAINTEXT}), encoding="utf-8")
    (target / "web_config.json").write_text(
        json.dumps({"web_ui_password_hash": "pbkdf2:sha256:1$abc$def"}), encoding="utf-8")
    return target


def test_the_security_status_sees_the_plaintext_token(config_dir):
    """THE FINDING, display."""
    status = TokenSecurityManager(config_service=MagicMock()).verify_token_encryption_status()

    assert status["token_exists"] is True, (
        f"The status does not see the token in DDC_CONFIG_DIR: {status}"
    )
    assert status["is_encrypted"] is False
    assert status["password_hash_available"] is True


def test_the_startup_migration_encrypts_in_the_config_dir(config_dir):
    """THE FINDING, migration: 'nothing to do' with plaintext in the real directory."""
    service = MagicMock()
    service.encrypt_token.return_value = "gAAAAA-encrypted"

    assert TokenSecurityManager(config_service=service).encrypt_existing_plaintext_token() is True

    saved = json.loads((config_dir / "bot_config.json").read_text(encoding="utf-8"))
    assert saved["bot_token"] == "gAAAAA-encrypted", (
        "The plaintext token in DDC_CONFIG_DIR was not encrypted."
    )


def test_the_bot_finds_the_token_in_the_fallback(config_dir):
    """THE FINDING, bot start: no token in config.json, no factory - then
    bot_config.json is the last path."""
    runtime = SimpleNamespace(
        logger=logging.getLogger("test.config_dir.token"),
        config={},
        dependencies=SimpleNamespace(config_service_factory=None),
    )

    assert bot_token.get_decrypted_bot_token(runtime) == PLAINTEXT
