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


# --- Since review E55 -------------------------------------------------------
# The token manager no longer reads a file of its own. It asks the ConfigService
# for the token and the password hash and writes through it, so it follows
# DDC_CONFIG_DIR exactly as far as the ConfigService does - one rule in one
# place. The two tests below therefore build a REAL ConfigService in the
# configured directory, with the token where every v2 installation keeps it:
# config.json. The bot_config.json the fixture above writes is the v1 layout,
# which v2.4 folds into config.json at startup; the tests that read it
# expected the token in a file no v2 installation has.


@pytest.fixture
def real_service(tmp_path, monkeypatch):
    import services.config.config_service as cs_mod
    from werkzeug.security import generate_password_hash

    target = tmp_path / "own_config"
    target.mkdir()
    monkeypatch.setenv("DDC_CONFIG_DIR", str(target))
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    monkeypatch.setattr(cs_mod, "_PBKDF2_ITERATIONS", 1000)
    monkeypatch.setattr(cs_mod.ConfigService, "_instance", None)
    (target / "config.json").write_text(json.dumps({
        "bot_token": "NOT-A-REAL-TOKEN.for-tests-only.config-dir-probe-padding-000",
        "web_ui_password_hash": generate_password_hash("Probe-Password-2026", method="pbkdf2:sha256:1000"),
    }), encoding="utf-8")
    return cs_mod.ConfigService(), target


def test_the_security_status_sees_the_plaintext_token(real_service):
    """THE FINDING, display: the status sees the token in DDC_CONFIG_DIR."""
    service, _ = real_service
    status = TokenSecurityManager(config_service=service).verify_token_encryption_status()

    assert status["token_exists"] is True, (
        f"The status does not see the token in DDC_CONFIG_DIR: {status}"
    )
    assert status["is_encrypted"] is False
    assert status["password_hash_available"] is True


def test_the_encrypt_button_encrypts_in_the_config_dir(real_service):
    """THE FINDING, migration: plaintext in the real directory gets encrypted.

    This was test_the_startup_migration_encrypts_in_the_config_dir. Encryption
    at startup was switched off by the operator on 2026-09-22 (review E55): it
    happens when the button is pressed. The guarantee - it lands in the
    configured directory, not somewhere else - is unchanged.
    """
    service, target = real_service

    assert TokenSecurityManager(config_service=service).encrypt_existing_plaintext_token() is True

    saved = json.loads((target / "config.json").read_text(encoding="utf-8"))
    assert saved["bot_token"].startswith("gAAAA"), (
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
