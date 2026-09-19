# -*- coding: utf-8 -*-
"""Container and channel configuration must follow ``DDC_CONFIG_DIR``.

NO ``@covers`` marker: that would be a new guarantee, and those are the
operator's decision. The work itself has been decided
("configuration path", 2026-09-19).

THE FINDING. ``DDC_CONFIG_DIR`` is documented for USERS (README.md:141,
docs/CONFIGURATION.md:148: "Override config directory"). Six places follow
it, around thirty derive ``<project>/config`` themselves. Whoever sets the
variable gets a split configuration - and here the split is most visible:
the web panel reads via ``config_service`` (follows the variable), but these
five read and write next to it::

    ServerConfigService._load_container_configs  <project>/config/containers
    ContainerConfigSaveService.__init__          <project>/config/containers
    ChannelConfigService.__init__                <project>/config/channels, config.json
    ContainerInfoService.__init__                <project>/config/containers
    ConfigurationPageService._process_docker_containers  (order)

The bot thus managed containers the panel does not show, and vice versa.

SECOND CONSEQUENCE, Z2: ChannelConfigService and ContainerConfigSaveService
already create directories under the REAL config/ in the constructor - even in
the test run, in which tests/conftest.py sets the variable to a temp directory.
Today only the empty mount in scripts/ddc_test.sh protects against that.

HOW IT IS CHECKED HERE: the variable points to a fresh directory in which
the test places files; what is checked is whether the services find EXACTLY
THESE (or point there). The expectation comes from the test, not from the service.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from services.config.channel_config_service import ChannelConfigService
from services.config.container_config_save_service import ContainerConfigSaveService
from services.config.server_config_service import ServerConfigService
from services.infrastructure.container_info_service import ContainerInfoService
from services.web.configuration_page_service import ConfigurationPageService


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    target = tmp_path / "own_config"
    (target / "containers").mkdir(parents=True)
    monkeypatch.setenv("DDC_CONFIG_DIR", str(target))
    return target


def _container(config_dir, name, **fields):
    data = {"container_name": name, "active": True, **fields}
    (config_dir / "containers" / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")


def test_the_bot_finds_the_containers_from_the_config_dir(config_dir):
    """THE FINDING, most visible form: the bot does not know the containers that
    are in the configured directory."""
    _container(config_dir, "probe_container")

    names = [s.get("docker_name") for s in ServerConfigService().get_all_servers()]

    assert "probe_container" in names, (
        f"ServerConfigService does not read from DDC_CONFIG_DIR ({config_dir}); "
        f"found: {names!r}"
    )


def test_saving_goes_into_the_config_dir(config_dir):
    assert ContainerConfigSaveService().containers_dir == config_dir / "containers"


def test_channels_live_in_the_config_dir(config_dir):
    service = ChannelConfigService()
    assert service.channels_dir == config_dir / "channels"
    assert service.config_file == config_dir / "config.json"


def test_container_infos_live_in_the_config_dir(config_dir):
    assert ContainerInfoService().containers_dir == config_dir / "containers"


def test_the_configuration_page_sorts_by_the_config_dir(config_dir):
    """The order comes from the ``order`` fields of the container files."""
    _container(config_dir, "alpha", order=1)
    _container(config_dir, "beta", order=2)
    live = [{"name": "beta"}, {"name": "alpha"}]

    with patch("app.utils.web_helpers.get_docker_containers_live", return_value=(live, None)):
        result = ConfigurationPageService()._process_docker_containers({})

    assert [c["name"] for c in result["live_containers"]] == ["alpha", "beta"], (
        "The configuration page does not sort by the order values from "
        "DDC_CONFIG_DIR."
    )
