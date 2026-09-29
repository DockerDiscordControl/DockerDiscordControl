# -*- coding: utf-8 -*-
# @covers Z9
"""A plaintext bot token is encrypted as soon as a Web UI password exists.

THE FINDING (stage 4 review before v3.1.0, section 13 pass 4 F2): a bot
token in config.json in plain text - entered before any password existed,
or carried over from an old installation - stayed plain text after a
password was set, after every save and after every start. Only the
"Encrypt token" button encrypted it: review E55 (2026-09-22) had switched
off the encryption at startup. SPEC Z9 promises the token never lies on
disk in plain text.

THE OPERATOR (2026-09-29): encrypt it automatically; Z9 holds without an
exception. The only time it stays plain is when there is no password yet -
there is no key to encrypt it with.

HOW THIS TEST CAN FAIL: a password change, a save or a start leaves the
token in plain text; or the encrypted token no longer decrypts to the one
the bot needs.

COUNTER-CHECK (2026-09-29): all three cases red before the change; the
no-password case green before and after.
"""

import json

import pytest
from werkzeug.security import generate_password_hash

import services.config.config_service as cs_mod

TOKEN = "NOT-A-REAL-TOKEN.for-tests-only.plaintext-to-cipher-000000"
PASSWORD = "Probe-Password-2026"


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    monkeypatch.setattr(cs_mod, "_PBKDF2_ITERATIONS", 1000)
    monkeypatch.setattr(cs_mod, "_PASSWORD_HASH_METHOD", "pbkdf2:sha256:1000")
    monkeypatch.setattr(cs_mod.ConfigService, "_instance", None)
    monkeypatch.setattr(cs_mod, "_config_service_instance", None)  # what the start asks
    return tmp_path


def _write(config_dir, **fields):
    (config_dir / "config.json").write_text(json.dumps(fields), encoding="utf-8")


def _stored(config_dir):
    return json.loads((config_dir / "config.json").read_text(encoding="utf-8"))


def _decrypts(service, config_dir):
    stored = _stored(config_dir)
    assert stored["bot_token"] != TOKEN, "the token lies on disk in plain text"
    assert service.decrypt_token(stored["bot_token"], stored["web_ui_password_hash"]) == TOKEN


def test_setting_a_password_encrypts_the_token(config_dir):
    _write(config_dir, bot_token=TOKEN, guild_id="1")
    service = cs_mod.ConfigService()
    service.change_web_ui_password(PASSWORD)
    _decrypts(service, config_dir)


def test_a_save_encrypts_a_plaintext_token(config_dir):
    _write(config_dir, bot_token=TOKEN, guild_id="1",
           web_ui_password_hash=generate_password_hash(PASSWORD, method="pbkdf2:sha256:1000"))
    service = cs_mod.ConfigService()
    assert service.save_config({"guild_id": "2"}).success
    _decrypts(service, config_dir)


def test_a_start_encrypts_a_plaintext_token(config_dir):
    _write(config_dir, bot_token=TOKEN, guild_id="1",
           web_ui_password_hash=generate_password_hash(PASSWORD, method="pbkdf2:sha256:1000"))
    from utils.token_security import auto_encrypt_token_on_startup
    auto_encrypt_token_on_startup()
    _decrypts(cs_mod.ConfigService(), config_dir)


def test_without_a_password_there_is_nothing_to_encrypt_with(config_dir):
    _write(config_dir, bot_token=TOKEN, guild_id="1")
    assert cs_mod.ConfigService().save_config({"guild_id": "2"}).success
    assert _stored(config_dir)["bot_token"] == TOKEN
