# -*- coding: utf-8 -*-
"""
THE FINDING (review E55, found by the v2.3.1 -> v2.4 upgrade test on
2026-09-22): the web panel's "Encrypt token" button reported success and left
the token in plaintext.

`TokenSecurityManager.encrypt_existing_plaintext_token` looked for the token in
`bot_config.json` and the password hash in `web_config.json` - the split files
of the v1 layout. Every v2 installation keeps both in `config.json`. So the
button found neither file, logged "Config files not found, skipping", and
returned True, which the security service turns into "Bot token encrypted
successfully". The operator believed the token was protected. On disk it was
exactly as readable as before. Measured on real data written by the published
v2.3.1 image: RESULT True, ON DISK plaintext.

`verify_token_encryption_status` read the same two files, so the status panel
did not see the token at all.

Decided by the operator on 2026-09-22: encryption happens when the button is
pressed, NOT automatically. `auto_encrypt_token_on_startup` was meant to do it
at every start, but it never saw a v2 token either - repairing the status would
have switched it on for every installation at its first v2.4 start, silently.
The last test here holds that decision.

The guarantee that matters most is the second test: after the button, the bot
still gets the same token. The key is derived from the password hash, so the
button verifies the round trip BEFORE it writes, and cannot store a token the
bot cannot read.
"""

import json

import pytest
from werkzeug.security import generate_password_hash

import services.config.config_service as cs_mod
from services.config.config_cache_service import ConfigCacheService
from services.config.config_loader_service import ConfigLoaderService
from services.config.config_migration_service import ConfigMigrationService
from services.config.config_service import get_config_service
from utils.token_security import TokenSecurityManager, auto_encrypt_token_on_startup

# Dotted and past fifty characters, which is all looks_like_discord_token
# asks - but not shaped like a real Discord token: GitHub push protection
# blocks that shape, and it stopped this very test on 2026-09-22.
TOKEN = "NOT-A-REAL-TOKEN.for-tests-only.encrypt-button-padding-00000"


@pytest.fixture(autouse=True)
def _fast_kdf(monkeypatch):
    monkeypatch.setattr(cs_mod, "_PBKDF2_ITERATIONS", 1000)
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)


@pytest.fixture
def svc(tmp_path, monkeypatch):
    """The ConfigService singleton on a temp dir with the real v2 layout."""
    service = get_config_service()
    saved_state = dict(service.__dict__)

    config_dir = tmp_path / "config"
    (config_dir / "containers").mkdir(parents=True)
    (config_dir / "channels").mkdir()
    monkeypatch.setenv("DDC_CONFIG_DIR", str(config_dir))

    service.config_dir = config_dir
    service.channels_dir = config_dir / "channels"
    service.containers_dir = config_dir / "containers"
    service.main_config_file = config_dir / "config.json"
    service.auth_config_file = config_dir / "auth.json"
    service.heartbeat_config_file = config_dir / "heartbeat.json"
    service.web_ui_config_file = config_dir / "web_ui.json"
    service.docker_settings_file = config_dir / "docker_settings.json"
    service.bot_config_file = config_dir / "bot_config.json"
    service.docker_config_file = config_dir / "docker_config.json"
    service.web_config_file = config_dir / "web_config.json"
    service.channels_config_file = config_dir / "channels_config.json"
    service._migration_service = ConfigMigrationService(config_dir, service.channels_dir, service.containers_dir)
    service._cache_service = ConfigCacheService()
    service._loader_service = ConfigLoaderService(
        config_dir, service.channels_dir, service.containers_dir,
        service.main_config_file, service.auth_config_file, service.heartbeat_config_file,
        service.web_ui_config_file, service.docker_settings_file, service.bot_config_file,
        service.docker_config_file, service.web_config_file, service.channels_config_file,
        service._load_json_file, service._validation_service,
    )
    yield service

    service.__dict__.clear()
    service.__dict__.update(saved_state)


def _v2_install(svc, *, with_password=True, token=TOKEN):
    """config.json as a v2.3.1 installation leaves it: plaintext token."""
    data = {"bot_token": token, "guild_id": "999999999999999999", "language": "de"}
    if with_password:
        data["web_ui_password_hash"] = generate_password_hash("Upgrade-Test-2026", method="pbkdf2:sha256:1000")
    svc.main_config_file.write_text(json.dumps(data))
    return data


def _on_disk(svc):
    return json.loads(svc.main_config_file.read_text())


def test_the_button_really_encrypts_a_v2_token(svc):
    """THE FINDING: success must mean the token on disk is encrypted."""
    installed = _v2_install(svc)

    assert TokenSecurityManager(svc).encrypt_existing_plaintext_token() is True

    stored = _on_disk(svc)["bot_token"]
    assert stored.startswith("gAAAA"), (
        "the button reported success and the token is still plaintext on disk"
    )
    assert svc.decrypt_token(stored, installed["web_ui_password_hash"]) == TOKEN


def test_the_bot_still_gets_the_same_token(svc):
    """The one thing that must not break: what the bot reads after the click."""
    _v2_install(svc)

    TokenSecurityManager(svc).encrypt_existing_plaintext_token()

    assert svc.get_config(force_reload=True)["bot_token_decrypted_for_usage"] == TOKEN


def test_the_rest_of_config_json_is_untouched(svc):
    installed = _v2_install(svc)

    TokenSecurityManager(svc).encrypt_existing_plaintext_token()

    after = _on_disk(svc)
    for key in ("guild_id", "language", "web_ui_password_hash"):
        assert after[key] == installed[key], f"{key} changed when only the token should"


def test_the_status_panel_sees_the_token(svc):
    """The status read the v1 files too, and reported no token at all."""
    _v2_install(svc)
    manager = TokenSecurityManager(svc)

    before = manager.verify_token_encryption_status()
    assert before["token_exists"] is True, "a plaintext token in config.json was not seen"
    assert before["is_encrypted"] is False
    assert before["can_encrypt"] is True

    manager.encrypt_existing_plaintext_token()

    assert manager.verify_token_encryption_status()["is_encrypted"] is True


def test_without_a_password_there_is_no_false_success(svc):
    """The key comes from the password hash. Without one the button cannot
    encrypt - and must say so rather than report success."""
    _v2_install(svc, with_password=False)

    assert TokenSecurityManager(svc).encrypt_existing_plaintext_token() is False
    assert _on_disk(svc)["bot_token"] == TOKEN


def test_an_encrypted_token_is_left_alone(svc):
    """COUNTER-CHECK: a second click must not encrypt the ciphertext again."""
    _v2_install(svc)
    manager = TokenSecurityManager(svc)
    manager.encrypt_existing_plaintext_token()
    first = _on_disk(svc)["bot_token"]

    assert manager.encrypt_existing_plaintext_token() is True
    assert _on_disk(svc)["bot_token"] == first
    assert svc.get_config(force_reload=True)["bot_token_decrypted_for_usage"] == TOKEN


def test_startup_does_not_encrypt(svc):
    """THE OPERATOR'S DECISION: the token is encrypted when the button is
    pressed, never silently at the first start after an upgrade."""
    _v2_install(svc)

    auto_encrypt_token_on_startup()

    assert _on_disk(svc)["bot_token"] == TOKEN, (
        "the startup encrypted the token on its own - the operator decided "
        "this happens only on request"
    )
