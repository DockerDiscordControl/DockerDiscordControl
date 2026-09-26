# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""The whole configuration as one file, and back.

WHY (operator, 2026-09-26): going back from v3.0 to v2.4.1 is not supported,
and config/ holds everything an installation is - the bot token, the second
factor, tasks, groups, rules, the donation ledger. "Keep a copy of config/
before upgrading" was the only advice, and it asked the operator to reach
into a volume by hand.

WHAT IS IN IT: every file under the configuration directory, hidden ones too
(.flask_secret_key keeps sessions valid), plus a manifest. NOT in it: lock
files, half-written temp files, and the backups this service keeps of its own
(else every backup would carry all earlier ones).

THE FILE IS NOT ENCRYPTED (operator decision 2026-09-26): taking it and
restoring it both ask for the panel password again; what happens to the file
afterwards is the operator's business, and the panel says so.

A RESTORE REPLACES, IT DOES NOT MERGE. A merge of two configurations has no
answer to "which rule wins", and a half-old half-new state is the one nobody
can reason about. The current configuration is saved as a backup first, so a
restore can itself be undone.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

FORMAT = 1
MANIFEST = "ddc-backup.json"
# Where this service keeps the configuration it replaced (inside config/).
BACKUP_DIR = "backups"
PENDING = ".restore-pending.zip"
# A real configuration is a few hundred kilobytes; the mech's snapshots and
# the ledger grow slowly. Generous, and still a bound on what an upload may be.
MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
MAX_UNPACKED_BYTES = 200 * 1024 * 1024
MAX_FILES = 5000
KEEP_OWN_BACKUPS = 5


class BackupRefused(ValueError):
    """The archive is not a DDC backup this version can restore - and why."""


def _skipped(relative: str) -> bool:
    parts = relative.split("/")
    name = parts[-1]
    return (parts[0] == BACKUP_DIR or name == PENDING or name.endswith(".lock")
            or name.endswith(".tmp") or ".json.tmp" in name)


def _files(config_dir: Path) -> List[Path]:
    found = []
    for root, dirs, names in os.walk(config_dir):
        dirs.sort()
        for name in sorted(names):
            path = Path(root) / name
            if path.is_symlink() or not path.is_file():
                continue
            if not _skipped(path.relative_to(config_dir).as_posix()):
                found.append(path)
    return found


def _summary(files: Dict[str, bytes]) -> Dict[str, int]:
    """What a person recognises a configuration by."""
    def count(prefix):
        return sum(1 for name in files if name.startswith(prefix) and name.endswith(".json"))

    def length(name, key=None):
        try:
            data = json.loads(files[name])
        except (KeyError, ValueError):
            return 0
        data = data.get(key, []) if key and isinstance(data, dict) else data
        return len(data) if isinstance(data, (list, dict)) else 0

    return {
        "containers": count("containers/"),
        "tasks": length("tasks.json"),
        "rules": length("auto_actions.json", "auto_actions"),
        "groups": length("groups.json", "groups"),
        "files": len(files),
    }


def create_backup(config_dir: Path, version: str = "", now: Optional[float] = None) -> bytes:
    """The configuration directory as a zip, with a manifest."""
    config_dir = Path(config_dir)
    contents = {path.relative_to(config_dir).as_posix(): path.read_bytes() for path in _files(config_dir)}
    manifest = {
        "format": FORMAT,
        "ddc_version": version,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now or time.time())),
        "summary": _summary(contents),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(MANIFEST, json.dumps(manifest, indent=2))
        for name, data in contents.items():
            archive.writestr(name, data)
    return buffer.getvalue()


@dataclass
class Inspected:
    manifest: Dict
    files: Dict[str, bytes] = field(repr=False)


def inspect_backup(data: bytes) -> Inspected:
    """Read an uploaded archive and refuse anything that is not a clean DDC backup.

    It is a file from outside, handled as the user DDC runs as, so it is read
    as hostile: no absolute paths, no "..", no links, bounded in size and count.
    """
    if len(data) > MAX_ARCHIVE_BYTES:
        raise BackupRefused("the file is larger than a DDC backup can be")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise BackupRefused("the file is not a zip archive")
    entries = [info for info in archive.infolist() if not info.is_dir()]
    if len(entries) > MAX_FILES:
        raise BackupRefused("the archive holds too many files")
    if sum(info.file_size for info in entries) > MAX_UNPACKED_BYTES:
        raise BackupRefused("the archive unpacks to more than a DDC backup can be")
    files: Dict[str, bytes] = {}
    for info in entries:
        name = info.filename
        if name.startswith("/") or "\\" in name or ".." in name.split("/") or ":" in name:
            raise BackupRefused(f"the archive holds a path that leaves the configuration: {name}")
        if (info.external_attr >> 16) & 0o170000 == 0o120000:
            raise BackupRefused(f"the archive holds a link: {name}")
        files[name] = archive.read(info)
    try:
        manifest = json.loads(files.pop(MANIFEST))
    except (KeyError, ValueError):
        raise BackupRefused("the archive has no DDC backup manifest - it was not made by DDC")
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
        raise BackupRefused("the backup was made in a format this DDC does not know")
    if "config.json" not in files:
        raise BackupRefused("the backup holds no config.json")
    if any(_skipped(name) for name in files):
        raise BackupRefused("the backup holds files a backup never contains")
    return Inspected(manifest=manifest, files=files)


def _keep_own_backup(config_dir: Path, version: str) -> Path:
    folder = config_dir / BACKUP_DIR
    folder.mkdir(exist_ok=True)
    target = folder / time.strftime("before-restore-%Y%m%d-%H%M%S.zip")
    target.write_bytes(create_backup(config_dir, version))
    for old in sorted(folder.glob("before-restore-*.zip"))[:-KEEP_OWN_BACKUPS]:
        old.unlink()
    return target


def restore_backup(config_dir: Path, data: bytes, version: str = "") -> Path:
    """Replace the configuration with the backup. Returns where the old one was kept.

    Written next to the old files first and swapped in only when every file is
    on disk, so a failure half-way leaves the current configuration as it was.
    """
    config_dir = Path(config_dir)
    inspected = inspect_backup(data)
    kept = _keep_own_backup(config_dir, version)
    staging = config_dir / ".restore-staging"
    if staging.exists():
        shutil.rmtree(staging)
    try:
        for name, content in inspected.files.items():
            target = staging / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            if name in (".flask_secret_key", "two_factor.json") or name.startswith("tls/"):
                target.chmod(0o600)
    except OSError:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    for entry in list(config_dir.iterdir()):
        if entry.name in (BACKUP_DIR, staging.name, PENDING):
            continue
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
        else:
            entry.unlink()
    for entry in list(staging.iterdir()):
        entry.rename(config_dir / entry.name)
    staging.rmdir()
    return kept
