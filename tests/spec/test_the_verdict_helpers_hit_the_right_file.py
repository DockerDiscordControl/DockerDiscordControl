# -*- coding: utf-8 -*-
"""The module helpers write where the instance reads.

THE FINDING (review C66, section 20 F3): ``GameQuerySupportService.__init__``
takes a ``path``, so an instance can be pointed at a file other than the
default ``_config_dir()/query_support.json``, and ``note_offline`` and
``_set`` honour it by passing ``self._path`` to ``_atomic_update``. The
module-level ``set_testing()`` and ``record_manual_success()`` call
``_atomic_update(_m)`` with no path at all, so they always target the default
location.

Anyone holding an instance with its own path and calling those two - the
obvious way to set the panel's re-test flag - wrote to a different file than
the one their instance reads back through ``reload()``. Nothing said so: both
writes succeed.
"""

import json

import pytest

from services.infrastructure import game_query_support_service as support
from services.infrastructure.game_query_support_service import GameQuerySupportService


@pytest.fixture
def elsewhere(tmp_path, monkeypatch):
    """A default location that is not the instance's file, so a write to the
    wrong one is visible instead of landing in the same place by accident."""
    default_dir = tmp_path / "default"
    default_dir.mkdir()
    monkeypatch.setenv("DDC_CONFIG_DIR", str(default_dir))
    return tmp_path / "own.json"


def _read(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def test_a_module_helper_can_be_given_the_path(elsewhere):
    support.set_testing("valheim", True, path=elsewhere)

    assert _read(elsewhere).get("valheim", {}).get("testing") is True


def test_an_instance_flags_its_own_file(elsewhere):
    service = GameQuerySupportService(path=elsewhere)

    service.set_testing("valheim", True)
    service.reload()

    assert _read(elsewhere).get("valheim", {}).get("testing") is True


def test_an_instance_records_a_manual_success_in_its_own_file(elsewhere):
    service = GameQuerySupportService(path=elsewhere)

    service.record_manual_success("valheim", protocol="source", port=2457)
    service.reload()

    assert service.is_supported("valheim") is True
    assert service.is_final("valheim") is True


def test_without_a_path_the_default_location_is_used(tmp_path, monkeypatch):
    """Counter-check: the web process calls these with no path and must keep
    reaching the one file the bot reads."""
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))

    support.set_testing("valheim", True)

    assert _read(tmp_path / "query_support.json").get("valheim", {}).get("testing") is True


def test_the_instance_does_not_touch_the_default_file(elsewhere, tmp_path):
    """Counter-check, other side: pointing an instance somewhere must keep it
    away from the shared file."""
    service = GameQuerySupportService(path=elsewhere)

    service.set_testing("valheim", True)

    assert not (tmp_path / "default" / "query_support.json").exists()
