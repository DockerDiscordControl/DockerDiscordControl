# -*- coding: utf-8 -*-
"""Five services, each with its own file, must follow ``DDC_CONFIG_DIR``.

NO ``@covers`` marker: that would be a new guarantee, and those are the
operator's decision.

THE FINDING. Each of these services is the only reader/writer of its file
and derives it from ``Path(__file__).parents[2] / "config"``::

    TranslationConfigService  channel_translations.json  (writes in the constructor)
    UpdateNotifier            update_status.json         (mkdir in the constructor)
    server_order              server_order.json          (module value at import)
    load_custom_timeout_config container_timeouts.json   (read only)
    SchedulerRuntime          tasks.json                  (fallback value)

Consequences as with the admin list (8ac5427) and the auto actions (71176fa):
with ``DDC_CONFIG_DIR`` on the volume, translation channels, server order and
SCHEDULED TASKS live outside of it and are gone after the container is
recreated; custom timeouts are not read. And Z2: two constructors write into
the REAL config/.

TWO DELIMITATIONS, because redirects already exist here:
1. ``DDC_SCHEDULER_CONFIG_DIR`` keeps precedence over ``DDC_CONFIG_DIR`` - only
   the scheduler's FALLBACK VALUE changes.
2. ``server_order.ORDER_FILE`` remains a settable module value - seven
   existing tests redirect it via monkeypatch. When unset (None) the path
   comes from the shared source at call time.
"""

import json

import pytest

from services.docker_service import docker_utils
from services.docker_service import server_order
from services.infrastructure.update_notifier import UpdateNotifier
from services.scheduling.runtime import SchedulerRuntime
from services.translation.translation_config_service import TranslationConfigService


@pytest.fixture
def config_root(tmp_path, monkeypatch):
    target = tmp_path / "own_config"
    target.mkdir()
    monkeypatch.setenv("DDC_CONFIG_DIR", str(target))
    monkeypatch.delenv("DDC_SCHEDULER_CONFIG_DIR", raising=False)
    return target


def test_translation_channels_live_in_the_config_dir(config_root):
    service = TranslationConfigService()
    assert service.config_file == config_root / "channel_translations.json"
    assert service.config_file.exists(), "The default file was not created in DDC_CONFIG_DIR."


def test_update_status_lives_in_the_config_dir(config_root):
    assert UpdateNotifier().status_file == config_root / "update_status.json"


def test_the_server_order_is_saved_in_the_config_dir(config_root, monkeypatch):
    monkeypatch.setattr(server_order, "ORDER_FILE", None, raising=False)

    assert server_order.save_server_order(["b", "a"]) is True

    file = config_root / "server_order.json"
    assert file.exists(), "server_order.json was not created in DDC_CONFIG_DIR."
    assert json.loads(file.read_text(encoding="utf-8"))["server_order"] == ["b", "a"]
    assert server_order.load_server_order() == ["b", "a"]


def test_custom_timeouts_come_from_the_config_dir(config_root, monkeypatch):
    monkeypatch.setattr(docker_utils, "_custom_config_loaded", False)
    monkeypatch.setattr(docker_utils, "_custom_timeout_config", None)
    content = {"container_overrides": {"probe": {"stats_timeout": 42.0}}}
    (config_root / "container_timeouts.json").write_text(json.dumps(content), encoding="utf-8")

    assert docker_utils.load_custom_timeout_config() == content


def test_scheduled_tasks_live_in_the_config_dir(config_root):
    assert SchedulerRuntime().config_dir == config_root


def test_the_own_scheduler_variable_keeps_precedence(config_root, tmp_path, monkeypatch):
    """Delimitation 1."""
    own = tmp_path / "scheduler_only"
    monkeypatch.setenv("DDC_SCHEDULER_CONFIG_DIR", str(own))
    assert SchedulerRuntime().config_dir == own


def test_a_set_order_file_still_applies(config_root, tmp_path, monkeypatch):
    """Delimitation 2: the redirect used by the existing tests."""
    file = tmp_path / "elsewhere" / "order.json"
    monkeypatch.setattr(server_order, "ORDER_FILE", file)

    assert server_order.save_server_order(["x"]) is True
    assert file.exists()
    assert not (config_root / "server_order.json").exists()
