# -*- coding: utf-8 -*-
"""Saving the container info must find the containers from ``DDC_CONFIG_DIR``.

NO ``@covers`` marker: that would be a new guarantee, and those are the
operator's decision.

THE FINDING. ``ConfigurationSaveService._save_configuration_files``
(``configuration_save_service.py:282``) collects the containers with
``Path('config/containers')`` - RELATIVE to the working directory, ignoring the
variable. ``save_container_info_from_web`` is fed from this list, and only
if it is NOT empty::

    if all_container_names:
        ... clear the info of disabled containers ...
        save_container_info_from_web(form_data, all_container_names)

With the variable set (or a different working directory) the list is empty:
info changes from the web form are SILENTLY not saved, and the info of
disabled containers stays in place. Inside the container the relative path is
only correct today because the working directory happens to be /app.

This spot was only found by the second, broader search of the ratchet
(test_config_dir_single_source.py) - the first scanner version did not see
relative "config/..." paths.

HOW IT IS CHECKED HERE: the two save functions and ``save_config`` are
recorders - the test checks WHAT is passed to them. The container files live
in the test directory; the expectation comes from the test.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from services.web.configuration_save_service import ConfigurationSaveService


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    target = tmp_path / "own_config"
    (target / "containers").mkdir(parents=True)
    for name in ("live", "idle"):
        (target / "containers" / f"{name}.json").write_text(
            json.dumps({"container_name": name}), encoding="utf-8")
    monkeypatch.setenv("DDC_CONFIG_DIR", str(target))
    return target


def _save(form_data):
    info = MagicMock(return_value={})
    with patch("services.config.config_service.save_config"), \
            patch("app.utils.container_info_web_handler.save_container_configs_from_web",
                  return_value={}), \
            patch("app.utils.container_info_web_handler.save_container_info_from_web", info):
        result = ConfigurationSaveService()._save_configuration_files(
            {"servers": [{"docker_name": "live"}]}, form_data, False)
    return result, info


def test_the_info_of_all_containers_is_saved(config_dir):
    """THE FINDING: without containers found, nothing is saved at all."""
    result, info = _save({})

    assert result.success, getattr(result, "error", None)
    info.assert_called_once()
    assert sorted(info.call_args.args[1]) == ["idle", "live"], (
        "The container info is not saved for the containers from "
        f"DDC_CONFIG_DIR: {info.call_args}"
    )


def test_the_info_of_disabled_containers_is_cleared(config_dir):
    """THE FINDING, second consequence."""
    form_data = {}
    _save(form_data)

    assert form_data.get("info_enabled_idle") == "0", (
        "The disabled container 'idle' keeps its info."
    )
    assert "info_enabled_live" not in form_data
