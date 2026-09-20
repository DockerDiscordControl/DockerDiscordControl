# -*- coding: utf-8 -*-
"""
THE FINDING (review C28, section 12 F2): a startup migration that dies halfway
is never tried again, and nothing ever says so.

`perform_real_modular_migration()` runs the stages in order: channels first,
containers second. If the container stage raises - a full disk, a locked file,
one bad entry - the exception is logged, re-raised, and
`ensure_modular_structure()` catches it with a single line,
"Falling back to virtual modular structure". `cleanup_legacy_files_after_
migration()` is never reached, so `docker_config.json` survives on disk.

On the next start, `needs_real_modular_migration()` asks whether the modular
structure EXISTS:

    has_real_modular = (channels_dir has any *.json) or
                       (containers_dir has any *.json) or
                       main_config_file.exists()

The channel stage succeeded, so channels_dir is full, so `has_real_modular` is
True, so the method returns False. The migration is never retried.
`load_real_modular_config()` reads only `containers_dir/*.json`, which stayed
empty - and the container list is silently wrong on every later start, with no
log line ever pointing at it again.

"Was it started" is not "was it finished". The question is now asked per stage:
for every legacy file that is still there, is its target populated? And a
completion marker is written when the whole migration really did finish, so a
later version never has to re-derive that answer.

The counter-checks keep the other end: a finished migration is not repeated,
and an installation without legacy files is left alone.
"""

import json
from pathlib import Path

import pytest

from services.config.config_migration_service import ConfigMigrationService


def _load_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default if default is not None else {}


def _save_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")
    return True


@pytest.fixture
def service(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    channels_dir = config_dir / "channels"
    containers_dir = config_dir / "containers"
    return ConfigMigrationService(config_dir, channels_dir, containers_dir)


@pytest.fixture
def legacy(service):
    """An installation as the migration finds it: two legacy files."""
    _save_json(service.channels_config_file, {
        "channel_permissions": {"111111111111111111": {"name": "control"}}})
    _save_json(service.docker_config_file, {
        "servers": [{"docker_name": "web"}, {"docker_name": "db"}]})
    return service


def test_a_migration_that_died_halfway_is_tried_again(legacy, monkeypatch):
    """THE FINDING: the container stage failed, so the work is not done."""
    def _explode(load_json_func, save_json_func):
        raise OSError("no space left on device")

    monkeypatch.setattr(legacy, "migrate_containers_to_files", _explode)
    legacy.ensure_modular_structure(_load_json, _save_json)

    assert list(legacy.channels_dir.glob("*.json")), "premise: channels were written"
    assert legacy.needs_real_modular_migration() is True


def test_the_container_list_is_not_left_empty(legacy, monkeypatch):
    """What the operator would actually notice: no containers, for good."""
    calls = {"n": 0}
    real = legacy.migrate_containers_to_files

    def _fail_once(load_json_func, save_json_func):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("no space left on device")
        return real(load_json_func, save_json_func)

    monkeypatch.setattr(legacy, "migrate_containers_to_files", _fail_once)

    legacy.ensure_modular_structure(_load_json, _save_json)   # dies halfway
    legacy.ensure_modular_structure(_load_json, _save_json)   # next startup

    names = sorted(p.stem for p in legacy.containers_dir.glob("*.json"))
    assert names == ["db", "web"]


def test_a_finished_migration_is_not_repeated(legacy):
    """COUNTER-CHECK: the retry must not become an endless loop.

    Noted honestly: this one passes because the cleanup removes the legacy
    files, not because of the marker or the completeness check. The two tests
    below cover the cases where those actually carry the weight.
    """
    legacy.ensure_modular_structure(_load_json, _save_json)

    assert legacy.needs_real_modular_migration() is False


def test_a_finished_migration_with_nothing_to_write_is_not_repeated(service, monkeypatch):
    """COUNTER-CHECK for the marker: a legacy file with an EMPTY server list
    leaves containers_dir empty, so "is it complete" says no for ever. Without
    the marker this migration would run again at every single startup."""
    _save_json(service.docker_config_file, {"servers": []})
    monkeypatch.setattr(service, "cleanup_legacy_files_after_migration", lambda: None)

    service.ensure_modular_structure(_load_json, _save_json)

    assert service.migration_complete_marker.exists()
    assert service.needs_real_modular_migration() is False


def test_an_old_installation_without_a_marker_is_left_alone(legacy):
    """COUNTER-CHECK for the completeness check: an installation migrated
    before the marker existed, with its legacy files still lying around, must
    not be migrated over again."""
    legacy.ensure_modular_structure(_load_json, _save_json)
    legacy.migration_complete_marker.unlink(missing_ok=True)
    _save_json(legacy.channels_config_file, {
        "channel_permissions": {"111111111111111111": {"name": "control"}}})
    _save_json(legacy.docker_config_file, {"servers": [{"docker_name": "web"}]})

    assert legacy.needs_real_modular_migration() is False


def test_an_installation_without_legacy_files_needs_nothing(service):
    """COUNTER-CHECK: nothing to migrate stays nothing to migrate."""
    assert service.needs_real_modular_migration() is False
