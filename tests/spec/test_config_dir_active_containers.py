# -*- coding: utf-8 -*-
"""The list of active containers for the web panel must follow
``DDC_CONFIG_DIR``.

NO ``@covers`` marker: that would be a new guarantee, and guarantees are the
operator's decision.

THE FINDING. ``app/utils/shared_data.py`` computes ``CONTAINERS_DIR`` at
IMPORT time from ``Path(__file__).parents[2] / "config"`` and ignores the
variable. ``load_active_containers_from_config`` feeds from it the active
containers for the configuration page (configuration_page_service.py:238), the
task management (task_management_service.py:423) and the web background
(app/web/background.py). After 16eca1e the bot reads the containers from
``DDC_CONFIG_DIR`` - this list kept reading from the old location. So the
container gap was not fully closed; noticed while reading the next hit of the
ratchet, not before.

HOW IT IS CHECKED HERE: the test creates the container files, one of them
inactive. The shared list (module state) is restored afterwards - otherwise
this test would bleed into others.
"""

import json

import pytest

from app.utils import shared_data


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    target = tmp_path / "own_config"
    (target / "containers").mkdir(parents=True)
    monkeypatch.setenv("DDC_CONFIG_DIR", str(target))
    before = shared_data.get_active_containers()
    try:
        yield target
    finally:
        shared_data.set_active_containers(before)


def test_the_active_containers_come_from_the_config_dir(config_dir):
    for name, active in (("running", True), ("idle", False)):
        (config_dir / "containers" / f"{name}.json").write_text(
            json.dumps({"container_name": name, "active": active}), encoding="utf-8")

    assert shared_data.load_active_containers_from_config() == ["running"], (
        "The active containers for the web panel do not come from DDC_CONFIG_DIR."
    )
    assert shared_data.get_active_containers() == ["running"]
