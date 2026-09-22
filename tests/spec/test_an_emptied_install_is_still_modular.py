# -*- coding: utf-8 -*-
"""An installation that was deliberately emptied is still a modular one.

THE FINDING (review C54, section 12 F4): ``has_real_modular_structure()``
answered the question "is this a real modular installation?" by counting
``*.json`` files in ``channels/`` and ``containers/``. The marker that
records "the last channel was removed on purpose" is called
``.all_channels_removed`` and is not a ``.json`` file, so an installation
with no containers and no channels left counted as "not modular yet" -
although it had been through the migration.

The loader then took the virtual path, which reads the settings from the v1
split files (``bot_config.json`` and friends). The real modular migration
deletes exactly those, and it keeps the settings in ``auth.json`` /
``web_ui.json`` / ``docker_settings.json`` instead - files the virtual path
never opens. The bot token and the Web-UI password hash therefore vanished
from the loaded configuration.
"""

import json
from pathlib import Path

import pytest

from services.config.config_loader_service import ConfigLoaderService
from services.config.channel_config_service import ALL_CHANNELS_REMOVED_MARKER


class _Defaults:
    get_default_docker_config = staticmethod(lambda: {})
    get_default_bot_config = staticmethod(lambda: {})
    get_default_web_config = staticmethod(lambda: {})
    get_default_channels_config = staticmethod(lambda: {})


def _load_json(path: Path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _loader(config_dir: Path) -> ConfigLoaderService:
    return ConfigLoaderService(
        config_dir, config_dir / "channels", config_dir / "containers",
        config_dir / "config.json", config_dir / "auth.json",
        config_dir / "heartbeat.json", config_dir / "web_ui.json",
        config_dir / "docker_settings.json", config_dir / "bot_config.json",
        config_dir / "docker_config.json", config_dir / "web_config.json",
        config_dir / "channels_config.json", _load_json, _Defaults(),
    )


@pytest.fixture
def emptied_install(tmp_path):
    """A migrated installation whose last channel was removed on purpose.

    No containers are configured, so both directories hold no ``*.json`` at
    all - only the marker.
    """
    config_dir = tmp_path / "config"
    (config_dir / "channels").mkdir(parents=True)
    (config_dir / "containers").mkdir()
    (config_dir / "channels" / ALL_CHANNELS_REMOVED_MARKER).write_text("{}", encoding="utf-8")
    (config_dir / "config.json").write_text(json.dumps({"language": "de"}), encoding="utf-8")
    # What the v2.0 modular migration leaves behind: the settings live here,
    # bot_config.json and friends are gone.
    (config_dir / "auth.json").write_text(
        json.dumps({"bot_token": "THE-REAL-TOKEN"}), encoding="utf-8")
    (config_dir / "web_ui.json").write_text(
        json.dumps({"web_ui_password_hash": "THE-REAL-HASH"}), encoding="utf-8")
    return config_dir


def test_an_emptied_install_counts_as_modular(emptied_install):
    assert _loader(emptied_install).has_real_modular_structure(), (
        "every channel was removed on purpose and no container is configured - "
        "the installation is read as if it had never been migrated"
    )


def test_the_bot_token_survives_the_last_channel(emptied_install):
    config = _loader(emptied_install).load_modular_config()

    assert config.get("bot_token") == "THE-REAL-TOKEN", (
        "the token lives in auth.json, and the path chosen here never opens that file"
    )
    assert config.get("web_ui_password_hash") == "THE-REAL-HASH"


def test_the_removed_channels_stay_removed(emptied_install):
    """The marker must keep meaning what it says on the path taken now."""
    config = _loader(emptied_install).load_modular_config()

    assert config.get("channel_permissions") == {}


def test_a_fresh_install_is_not_modular(tmp_path):
    """Counter-check: without the marker, empty directories mean 'not yet'."""
    config_dir = tmp_path / "config"
    (config_dir / "channels").mkdir(parents=True)
    (config_dir / "containers").mkdir()

    assert not _loader(config_dir).has_real_modular_structure()


def test_a_populated_install_is_modular(tmp_path):
    """Counter-check: the usual case must keep its answer."""
    config_dir = tmp_path / "config"
    (config_dir / "channels").mkdir(parents=True)
    (config_dir / "containers").mkdir()
    (config_dir / "containers" / "web.json").write_text(
        json.dumps({"docker_name": "web"}), encoding="utf-8")

    assert _loader(config_dir).has_real_modular_structure()


def test_channels_alone_are_enough(tmp_path):
    """The marker is an ADDITION, not a replacement: real channel files still count.

    Found by mutation M2 of review C54 - dropping the ``*.json`` count for the
    channels directory broke nothing that was under test.
    """
    config_dir = tmp_path / "config"
    (config_dir / "channels").mkdir(parents=True)
    (config_dir / "containers").mkdir()
    (config_dir / "channels" / "123.json").write_text(
        json.dumps({"channel_id": "123"}), encoding="utf-8")

    assert _loader(config_dir).has_real_modular_structure()
