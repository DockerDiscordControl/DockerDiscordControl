# -*- coding: utf-8 -*-
"""The whole configuration can be saved as one file and restored from it.

THE REQUEST (operator, 2026-09-26): "save the complete configuration and load
it again". Going back from v3.0 to v2.4.1 is not supported, and config/ holds
everything an installation is; until now the only advice was to copy the
volume by hand.

THE CONTRACT (services/config/backup_service.py):
  * a backup holds every file of the configuration - hidden ones too - and a
    manifest; never lock files, temp files or DDC's own earlier backups;
  * a restore REPLACES the configuration (files the backup does not have are
    gone afterwards), and keeps the replaced configuration as a backup first;
  * an uploaded archive is hostile until proven otherwise: a path leaving the
    directory, a link, a foreign or unknown-format archive is refused and
    nothing on disk changes.

HOW THIS TEST CAN FAIL: a file missing after the round trip, a stray file
surviving a restore, a restore that loses the old configuration, or an archive
that writes outside the directory.

COUNTER-CHECK (2026-09-26): each property sabotaged in the service once -
hidden files skipped, the pre-restore backup not written, the ".." check
removed - and the matching case went red.
"""

import io
import json
import zipfile

import pytest

from services.config import backup_service as svc


@pytest.fixture
def config_dir(tmp_path):
    root = tmp_path / "config"
    (root / "containers").mkdir(parents=True)
    (root / "config.json").write_text(json.dumps({"language": "de"}))
    (root / "containers" / "Valheim.json").write_text("{}")
    (root / "tasks.json").write_text(json.dumps([{"id": "t1"}, {"id": "t2"}]))
    (root / "auto_actions.json").write_text(json.dumps({"auto_actions": [{"id": "r"}]}))
    (root / ".flask_secret_key").write_text("secret")
    (root / "two_factor.json").write_text("{}")
    (root / "config.json.lock").write_text("")
    (root / "state.json.tmp").write_text("half")
    return root


def _names(data):
    return sorted(zipfile.ZipFile(io.BytesIO(data)).namelist())


def test_a_backup_holds_the_configuration_and_nothing_transient(config_dir):
    names = _names(svc.create_backup(config_dir, "3.0.0"))

    assert names == sorted([svc.MANIFEST, "config.json", "containers/Valheim.json", "tasks.json",
                            "auto_actions.json", ".flask_secret_key", "two_factor.json"]), names


def test_the_manifest_says_what_is_inside(config_dir):
    inspected = svc.inspect_backup(svc.create_backup(config_dir, "3.0.0"))

    assert inspected.manifest["ddc_version"] == "3.0.0"
    assert inspected.manifest["summary"]["containers"] == 1
    assert inspected.manifest["summary"]["tasks"] == 2
    assert inspected.manifest["summary"]["rules"] == 1


def test_a_restore_replaces_and_keeps_the_old_configuration(config_dir, tmp_path):
    backup = svc.create_backup(config_dir, "3.0.0")
    (config_dir / "config.json").write_text(json.dumps({"language": "en"}))
    (config_dir / "groups.json").write_text("{}")          # made after the backup

    kept = svc.restore_backup(config_dir, backup, "3.0.0")

    assert json.loads((config_dir / "config.json").read_text()) == {"language": "de"}
    assert not (config_dir / "groups.json").exists(), "a restore merged instead of replacing"
    assert (config_dir / ".flask_secret_key").read_text() == "secret"
    old = svc.inspect_backup(kept.read_bytes())
    assert json.loads(old.files["config.json"]) == {"language": "en"}
    assert "groups.json" in old.files


def test_a_backup_does_not_carry_earlier_backups(config_dir):
    svc.restore_backup(config_dir, svc.create_backup(config_dir))

    assert not any(name.startswith(svc.BACKUP_DIR) for name in _names(svc.create_backup(config_dir)))


def _archive(entries, manifest=True):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        if manifest:
            archive.writestr(svc.MANIFEST, json.dumps({"format": svc.FORMAT}))
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


@pytest.mark.parametrize("data, why", [
    (b"not a zip at all", "not a zip"),
    (_archive({"config.json": "{}"}, manifest=False), "manifest"),
    (_archive({"../escape.json": "x", "config.json": "{}"}), "leaves"),
    (_archive({"/etc/passwd": "x", "config.json": "{}"}), "leaves"),
    (_archive({"tasks.json": "[]"}), "config.json"),
], ids=["not-a-zip", "no-manifest", "dotdot-path", "absolute-path", "no-config"])
def test_a_foreign_or_hostile_archive_is_refused_and_nothing_changes(config_dir, data, why):
    before = sorted(p.name for p in config_dir.rglob("*"))

    with pytest.raises(svc.BackupRefused) as refused:
        svc.restore_backup(config_dir, data)

    assert why in str(refused.value)
    assert sorted(p.name for p in config_dir.rglob("*")) == before


def test_a_link_in_the_archive_is_refused():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(svc.MANIFEST, json.dumps({"format": svc.FORMAT}))
        archive.writestr("config.json", "{}")
        link = zipfile.ZipInfo("tasks.json")
        link.external_attr = (0o120777 << 16)
        archive.writestr(link, "/etc/passwd")

    with pytest.raises(svc.BackupRefused, match="link"):
        svc.inspect_backup(buffer.getvalue())
