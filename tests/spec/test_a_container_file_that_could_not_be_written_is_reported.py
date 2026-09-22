# -*- coding: utf-8 -*-
"""A container file that could not be written is not reported as saved.

THE FINDING: the per-container writes - allowed actions and display name in
config/containers/<name>.json, and the info fields beside them - return a
dict of name -> success. Both results were logged and then dropped, and the
save returned success regardless. The failure that makes this real is the
project's own rule: a file written by root (a `docker exec` without `-u ddc`)
cannot be written by the app afterwards. The operator then unticks "stop" for
a container, reads "Configuration saved successfully", and the bot keeps
allowing stop.

The channel path already reports its failures (review B5 / SPEC Z3); the
container path did not.

COUNTER-CHECK (2026-09-22): red before - a write that failed for two
containers still reported success.
"""

from unittest.mock import patch

import pytest

from services.web.configuration_save_service import ConfigurationSaveService


@pytest.fixture
def service(tmp_path, monkeypatch):
    import json

    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    containers = tmp_path / "containers"
    containers.mkdir()
    for name in ("web", "db"):  # the files the save walks over
        (containers / f"{name}.json").write_text(
            json.dumps({"docker_name": name, "info": {}}), encoding="utf-8")
    return ConfigurationSaveService()


PROCESSED = {"servers": [{"docker_name": "web", "name": "web"},
                         {"docker_name": "db", "name": "db"}]}
FORM = {"info_enabled_web": "1", "info_enabled_db": "1"}


def _save(service, config_results, info_results):
    with patch("services.config.config_service.save_config", return_value=True), \
         patch("app.utils.container_info_web_handler.save_container_configs_from_web",
               return_value=config_results), \
         patch("app.utils.container_info_web_handler.save_container_info_from_web",
               return_value=info_results):
        return service._save_configuration_files(PROCESSED, dict(FORM), config_split_enabled=False)


def test_a_failed_container_config_write_is_reported(service):
    result = _save(service, {"web": True, "db": False}, {"web": True, "db": True})

    assert result.success is False
    assert "db" in (result.error or "")


def test_a_failed_info_write_is_reported(service):
    result = _save(service, {"web": True}, {"web": False})

    assert result.success is False
    assert "web" in (result.error or "")


def test_everything_written_is_still_a_success(service):
    """Counter-check: a save that worked must not start failing."""
    result = _save(service, {"web": True, "db": True}, {"web": True, "db": True})

    assert result.success is True and not result.error
