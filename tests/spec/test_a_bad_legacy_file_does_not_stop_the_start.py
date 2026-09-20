# -*- coding: utf-8 -*-
"""A broken legacy file costs the migration, not the start.

THE FINDING (review C55, section 12 F5): ``ensure_modular_structure`` promises
a fallback - it logs "Falling back to virtual modular structure" and carries
on. It only catches ``(OSError, IOError, PermissionError, AttributeError)``,
while ``perform_real_modular_migration`` below it re-raises
``json.JSONDecodeError``, ``TypeError``, ``ValueError`` and ``KeyError`` as
well. A legacy file with an unexpected shape - a channel entry that is a
string instead of an object - therefore raises a ``TypeError`` straight out
of the method.

``ensure_modular_structure`` is called in ``ConfigService.__init__``, so that
exception leaves the constructor, and ``get_config_service()`` fails for
everyone. One bad line in a file from the previous version takes the whole
installation down on the one startup that was supposed to upgrade it.
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
    return ConfigMigrationService(config_dir, config_dir / "channels",
                                  config_dir / "containers")


def test_a_channel_entry_of_the_wrong_shape_is_survived(service, caplog):
    """A channel that is a string, not an object: `channel_config["channel_id"] = ...`
    raises TypeError inside the channel stage."""
    _save_json(service.channels_config_file,
               {"channel_permissions": {"111111111111111111": "control"}})
    _save_json(service.docker_config_file, {"servers": [{"docker_name": "web"}]})

    service.ensure_modular_structure(_load_json, _save_json)

    assert [r for r in caplog.records if r.levelno >= 40], (
        "the migration failed and nothing in the log says so"
    )
    # The fallback is this method's own promise, and the stages below it log
    # their own errors - without this line the promise could be gone and the
    # log would still look the same (found by mutation M2 of review C55).
    assert any("Falling back" in r.getMessage() for r in caplog.records), (
        "nothing says the installation carries on without the modular structure"
    )


def test_the_failure_is_not_recorded_as_a_finished_migration(service):
    """A migration that died must be picked up again on the next start."""
    _save_json(service.channels_config_file,
               {"channel_permissions": {"111111111111111111": "control"}})
    _save_json(service.docker_config_file, {"servers": [{"docker_name": "web"}]})

    service.ensure_modular_structure(_load_json, _save_json)

    assert service.needs_real_modular_migration() is True


def test_a_sound_installation_still_migrates(service):
    """Counter-check: swallowing everything must not swallow the work itself."""
    _save_json(service.channels_config_file,
               {"channel_permissions": {"111111111111111111": {"name": "control"}}})
    _save_json(service.docker_config_file, {"servers": [{"docker_name": "web"}]})

    service.ensure_modular_structure(_load_json, _save_json)

    assert (service.containers_dir / "web.json").exists()
    assert service.needs_real_modular_migration() is False
