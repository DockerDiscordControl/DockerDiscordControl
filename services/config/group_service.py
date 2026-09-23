# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Container groups the operator defines by hand.

DDC could only group containers by their Docker compose project, and on a
typical Unraid server that label does not exist at all (measured: 0 of 37
containers). A group here is what the operator says it is - a name and a list
of containers - and it is meant to be choosable wherever a single container is
choosable today: the admin button, scheduled tasks, auto-actions.

Two rules everything built on top depends on:

* resolving a group REPORTS the members DDC no longer has instead of dropping
  them. A group of seven that quietly became six would act on six and still
  say "done";
* the file is written like every shared file in DDC: the read-modify-write
  under ``cross_process_lock`` and the write through ``atomic_write_json``,
  because the bot and the web panel are two processes.
"""

from __future__ import annotations

import json
import time
import unicodedata
from dataclasses import dataclass, field
from typing import List, Optional

from utils.atomic_io import atomic_write_json, cross_process_lock
from utils.config_paths import get_config_dir
from utils.logging_utils import get_module_logger

logger = get_module_logger('group_service')

MAX_NAME_LENGTH = 80  # Discord shows a select option's label up to 100 characters

# Characters a name may not contain. "/" is the one that matters: the delete
# route takes the name as a path segment, Flask's converter does not match a
# slash, and %2F is decoded before routing - so a group called "Media/TV" could
# be created and never deleted again (verified against Flask: 404, with an HTML
# body the panel shows as a bare "Error"). The rest would break a menu line or
# a log line the same way.
FORBIDDEN_IN_NAME = ("/", "\\", "\n", "\r", "\t")


def _normalised(name: str) -> str:
    """The name in one unicode spelling, for comparing.

    "Café" typed as NFC and as NFD look identical in every menu; without this
    they are two groups, and find() on the other spelling answers "there is no
    group called Café".
    """
    return unicodedata.normalize("NFC", name or "")


@dataclass(frozen=True)
class ContainerGroup:
    """A group as the operator wrote it down."""
    name: str
    containers: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class GroupMembers:
    """What a group resolves to right now.

    ``missing`` are names in the group that DDC has no container for any more -
    a renamed or deleted container. Callers say so instead of acting on fewer
    containers than the operator asked for.
    """
    exists: bool
    containers: List[str] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class GroupResult:
    """Success or the reason it did not happen."""
    success: bool
    error: Optional[str] = None


class GroupService:
    """Reads and writes ``config/groups.json``."""

    def __init__(self):
        self._path = get_config_dir() / "groups.json"
        self._names_cache: Optional[set] = None
        self._names_read_at = 0.0

    # ------------------------------------------------------------------ read

    def get_groups(self) -> List[ContainerGroup]:
        """Every group, in the order they were written."""
        return [ContainerGroup(name=entry["name"], containers=list(entry.get("containers", [])))
                for entry in self._read()]

    def find(self, name: str) -> Optional[ContainerGroup]:
        """The group of that name, ignoring case, or None."""
        wanted = _normalised(name).strip().casefold()
        return next((g for g in self.get_groups()
                     if _normalised(g.name).casefold() == wanted), None)

    def members_of(self, name: str) -> GroupMembers:
        """The containers of the group that DDC still has, and the ones it does not."""
        group = self.find(name)
        if group is None:
            return GroupMembers(exists=False)

        known = self._configured_container_names()
        containers = [c for c in group.containers if c in known]
        missing = [c for c in group.containers if c not in known]
        if missing:
            logger.warning(f"Group '{group.name}' names {len(missing)} container(s) DDC does not "
                           f"have: {', '.join(missing)}")
        return GroupMembers(exists=True, containers=containers, missing=missing)

    # ----------------------------------------------------------------- write

    def save_group(self, name: str, containers: List[str]) -> GroupResult:
        """Create the group, or replace the containers of the one with that name."""
        name = _normalised(name).strip()
        if not name:
            return GroupResult(False, "A group needs a name.")
        if len(name) > MAX_NAME_LENGTH:
            return GroupResult(False, f"A group name may be at most {MAX_NAME_LENGTH} characters.")
        bad = [c for c in FORBIDDEN_IN_NAME if c in name]
        if bad:
            return GroupResult(False, "A group name may not contain a slash, a backslash or a "
                                      "line break - the name is part of a web address when the "
                                      "group is deleted.")

        # Stripped as they are stored, and each one once: a padded name never
        # matches a container, and a doubled one would be acted on twice.
        cleaned = []
        for container in containers or []:
            if not isinstance(container, str) or not container.strip():
                continue
            container = container.strip()
            if container not in cleaned:
                cleaned.append(container)
        containers = cleaned
        try:
            with cross_process_lock(self._path):
                entries = self._read()
                same_name = [e for e in entries
                             if _normalised(e["name"]).casefold() == _normalised(name).casefold()]
                if same_name and same_name[0]["name"] != name:
                    # Two groups whose names differ only in case make every later
                    # choice ambiguous - in a select menu, in a task, in a rule.
                    return GroupResult(
                        False, f"A group called '{same_name[0]['name']}' already exists.")
                if same_name:
                    same_name[0]["containers"] = containers
                else:
                    entries.append({"name": name, "containers": containers})
                self._write(entries)
        except OSError as e:
            logger.error(f"Could not save group '{name}': {e}", exc_info=True)
            return GroupResult(False, f"The group could not be saved: {e}")
        return GroupResult(True)

    def delete_group(self, name: str) -> GroupResult:
        """Remove the group. The containers themselves are not touched."""
        wanted = _normalised(name).strip().casefold()
        try:
            with cross_process_lock(self._path):
                entries = self._read()
                remaining = [e for e in entries
                             if _normalised(e["name"]).casefold() != wanted]
                if len(remaining) == len(entries):
                    return GroupResult(False, f"There is no group called '{name}'.")
                self._write(remaining)
        except OSError as e:
            logger.error(f"Could not delete group '{name}': {e}", exc_info=True)
            return GroupResult(False, f"The group could not be deleted: {e}")
        return GroupResult(True)

    # ---------------------------------------------------------------- helpers

    def _read(self) -> List[dict]:
        """The file's groups, or an empty list. A broken file is said out loud."""
        if not self._path.exists():
            return []
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError, ValueError) as e:
            # Not an empty list quietly: every caller would then act as if the
            # operator had defined no groups at all.
            logger.error(f"Groups file {self._path} could not be read: {e}")
            raise OSError(f"groups.json could not be read: {e}") from e
        entries = data.get("groups") if isinstance(data, dict) else None
        if not isinstance(entries, list):
            return []
        return [{"name": str(e["name"]), "containers": list(e.get("containers", []))}
                for e in entries if isinstance(e, dict) and e.get("name")]

    def _write(self, entries: List[dict]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self._path, {"groups": entries})

    def _configured_container_names(self) -> set:
        """The containers DDC has, for one second at a time.

        ServerConfigService.get_all_servers() reloads every file under
        config/containers/ on every call, on purpose. Resolving a group is not
        a rare thing: the watchdog does it per event per rule, and the admin
        overview asks on every redraw - measured at 20 full reads for 20
        resolutions, on a config directory that lives on an SMB mount, from the
        bot's event loop.

        One second is short enough that a container added in the panel shows up
        in the next group resolution, and long enough to collapse a whole
        watchdog cycle into one read.
        """
        now = time.monotonic()
        if self._names_cache is not None and now - self._names_read_at < 1.0:
            return self._names_cache

        from services.config.server_config_service import get_server_config_service

        names = {s.get("docker_name") for s in get_server_config_service().get_all_servers()
                 if s.get("docker_name")}
        self._names_cache = names
        self._names_read_at = now
        return names


_service: Optional[GroupService] = None


def get_group_service() -> GroupService:
    global _service
    if _service is None:
        _service = GroupService()
    return _service


def reset_group_service() -> None:
    """Drop the cached service (tests, and a changed config directory)."""
    global _service
    _service = None
