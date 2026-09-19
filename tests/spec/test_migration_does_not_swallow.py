# -*- coding: utf-8 -*-
"""An unreadable legacy configuration must not look like "none".

NO ``@covers`` marker: that would be a new guarantee, and those are the
operator's decision.

THE FINDING (stage 2, point 2 - "where something disappears silently"):
``ConfigMigrationService.migrate_legacy_v1_config_if_needed`` checks whether an
old ``config.json`` is present::

    try:
        with open(self.legacy_config_file, ...) as f:
            test_data = json.load(f)
            if 'servers' in test_data or 'docker_name' in test_data:
                legacy_file = self.legacy_config_file
    except Exception:
        pass

    if not legacy_file:
        return  # No migration needed

If the file is **unreadable** - truncated, broken JSON, permissions gone -, it
falls into the ``except`` and is then indistinguishable from "there is no
legacy configuration". The migration is skipped, the user starts with an empty
configuration, and the log says **nothing**.

WHY THIS IS EXPENSIVE: the call hangs off ``config_service.py:322``, i.e. off
every ``get_config()``. Anyone upgrading from v1.1.x whose ``config.json`` was
damaged while copying loses containers, channel permissions and settings -
and sees a freshly set-up instance instead of an error message. After
"unnoticed strikes rarely" this is the expensive kind.

WHAT IS **NOT** REQUIRED HERE: that the migration succeeds. A broken file
cannot be migrated. What is required is that the error becomes **visible** -
a log line that makes the difference between "nothing to do" and "there was
something here that I could not read".

SCOPE: the ``except`` used to catch EVERY ``BaseException`` (bare
``except:``); that was changed project-wide on the same day. What is checked
here is not the breadth but the **swallowing**.

COUNTER-CHECK (performed 2026-09-17): 1 red, 3 green - exactly as predicted.

The failure was ``assert ''``: with a truncated ``config.json`` there was
**not a single** log record. This also refutes the three pitfalls named
beforehand - ``caplog`` works (otherwise the opposite directions would not have
distinguished cleanly), the service can be built, and the truncated string is
really unreadable.

The two opposite directions were green from the start. They are necessary:
without them one could warn unconditionally, and the test above would stay
green while every normal start produced a warning. A test with false alarms
gets ignored and is thus as worthless as a green one.

After the fix: 4 green, ``tests/unit/services/configuration`` unchanged
152 green.

WHAT THE FIX CHANGES: ``except Exception: pass`` became
``except (OSError, ValueError)`` **with a warning**. The flow stays the same -
a broken file cannot be migrated -, but the difference between "nothing to
do" and "there was something unreadable here" is now visible.

CHECKED FOR Z9: the message only names the file name, the exception type and
the exception text - **never** the content. A v1.1.x ``config.json`` carries
the bot token, and a log is disk. Proven via AST: no log call in this file
passes on a content variable. A first, hand-written guard had wrongly raised
an alarm here because it searched for the string in the whole fallback block
instead of in the arguments of the call.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict

import pytest

from services.config.config_migration_service import ConfigMigrationService


def _service(tmp_path: Path) -> ConfigMigrationService:
    """Migration service with real directories under ``tmp_path``.

    Same construction as ``TestConfigMigrationService._make`` in
    ``tests/unit/services/configuration/test_config_full.py:714``.
    """
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    return ConfigMigrationService(
        config_dir=config_dir,
        channels_dir=config_dir / "channels",
        containers_dir=config_dir / "containers",
    )


def _save_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _load_json(path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
    if not path.exists():
        return dict(default)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return dict(default)


def _nothing(_cfg):
    """Extraction function that returns nothing - it must never be called here."""
    return {}


def _migrate(svc):
    svc.migrate_legacy_v1_config_if_needed(
        _load_json, _save_json, _nothing, _nothing, _nothing, _nothing
    )


def test_the_service_can_be_built_at_all(tmp_path):
    """Safeguard against a blunt tool.

    If construction fails, the tests below would be red or green without it
    having anything to do with the guarantee.
    """
    svc = _service(tmp_path)
    assert svc.legacy_config_file.name == "config.json", (
        f"The legacy file is unexpectedly named {svc.legacy_config_file.name!r} - "
        "the tests below then target the wrong file."
    )


def test_unreadable_legacy_config_is_reported(tmp_path, caplog):
    """A broken config.json must not be treated like "none"."""
    svc = _service(tmp_path)
    svc.legacy_config_file.write_text(
        '{"servers": [{"docker_name": "nginx"}], "guild_id": ',  # truncated
        encoding="utf-8",
    )

    with caplog.at_level(logging.WARNING):
        _migrate(svc)

    messages = " ".join(record.getMessage() for record in caplog.records)
    assert messages.strip(), (
        "An unreadable config.json was silently skipped. It is thus "
        "indistinguishable from 'there is no legacy configuration': the "
        "user starts with an empty configuration and never learns why. "
        "Not a successful migration is required, only a visible message."
    )


def test_missing_legacy_config_reports_nothing(tmp_path, caplog):
    """The opposite direction - otherwise 'always report something' would be green too.

    Without this case one could emit a warning unconditionally and the test
    above would stay green while every normal start produced a warning.
    """
    svc = _service(tmp_path)
    assert not svc.legacy_config_file.exists()

    with caplog.at_level(logging.WARNING):
        _migrate(svc)

    messages = [record.getMessage() for record in caplog.records]
    assert not messages, (
        f"Without a legacy configuration nothing may be reported, got: {messages}"
    )


def test_readable_legacy_config_without_servers_reports_nothing(tmp_path, caplog):
    """A valid but unsuitable file is not an error case.

    A v2.0 ``config.json`` without ``servers``/``docker_name`` is readable and
    simply not to be migrated. If it warned too, every start would produce a
    message - and a test that produces false alarms gets ignored.
    """
    svc = _service(tmp_path)
    _save_json(svc.legacy_config_file, {"language": "de", "timezone": "UTC"})

    with caplog.at_level(logging.WARNING):
        _migrate(svc)

    messages = [record.getMessage() for record in caplog.records]
    assert not messages, (
        f"A readable file without servers is not an error, got: {messages}"
    )
