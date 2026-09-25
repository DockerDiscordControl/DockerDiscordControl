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
  because a second writer can always appear - another thread, or an operator
  editing the file by hand.
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

# How DDC says "this name is a group and not a container": in an auto-action
# rule's targets, in a per-admin assignment, in the name a button hands to the
# action service. ONE definition, because four copies of one word that must
# agree only look harmless until one of them changes - then every target
# written by one half stops being read by the other, silently, since an unknown
# name is simply not a group.
GROUP_PREFIX = "group:"


def is_group_target(name) -> bool:
    """Whether this name means a group rather than a container."""
    return isinstance(name, str) and name.startswith(GROUP_PREFIX)


def group_name_of(name: str) -> str:
    """The group's own name; a container name comes back unchanged."""
    return name[len(GROUP_PREFIX):] if is_group_target(name) else name


def group_target(name: str) -> str:
    """The name of that group as a target."""
    return f"{GROUP_PREFIX}{name}"

# What a group may be allowed to do. The same four a container offers, because
# they are the four buttons Discord can press - an action outside this list
# would be stored, drawn as a tick and do nothing when pressed.
KNOWN_ACTIONS = ("status", "start", "stop", "restart")


def _normalised(name: str) -> str:
    """The name in one unicode spelling, for comparing.

    "Café" typed as NFC and as NFD look identical in every menu; without this
    they are two groups, and find() on the other spelling answers "there is no
    group called Café".
    """
    return unicodedata.normalize("NFC", name or "")


@dataclass(frozen=True)
class ContainerGroup:
    """A group as the operator wrote it down.

    OPERATOR DECISION (2026-09-24): a group is NOT a shortcut for ticking boxes
    on its containers, and not a view of them either - it is a control of its
    own. ``active`` and ``allowed_actions`` are the group's, exactly as a
    container has its own, and a member's settings neither limit them nor are
    changed by them. A container switched off in DDC, or allowed only to be
    stopped, can sit in a group that may do all four.

    A group from a file written before that decision carries neither field. It
    reads as Active with the four standard actions, because that is what it
    could do yesterday: the Discord restart menu offered every group a restart
    whatever its members said. Reading it as powerless would take a working
    button away from an operator who changed nothing.
    """
    name: str
    containers: List[str] = field(default_factory=list)
    active: bool = True
    allowed_actions: List[str] = field(default_factory=lambda: list(KNOWN_ACTIONS))


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
    """Success or the reason it did not happen.

    ``moved`` is filled by a rename: how many references in each file followed
    the name. The operator gets one sentence instead of four files to check.
    """
    success: bool
    error: Optional[str] = None
    moved: dict = field(default_factory=dict)


class GroupService:
    """Reads and writes ``config/groups.json``."""

    def __init__(self):
        self._path = get_config_dir() / "groups.json"
        self._names_cache: Optional[set] = None
        self._names_read_at = 0.0

    # ------------------------------------------------------------------ read

    def get_groups(self) -> List[ContainerGroup]:
        """Every group, in the order they were written."""
        return [ContainerGroup(name=entry["name"],
                               containers=list(entry.get("containers", [])),
                               active=entry["active"],
                               allowed_actions=list(entry["allowed_actions"]))
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

    def _refuse_name(self, name: str) -> Optional[str]:
        """Why this name may not be used, or None.

        Shared by save and rename, because a rename IS a save of the name: a
        rule that only one of them applies is a rule with a way around it.
        """
        if not name:
            return "A group needs a name."
        if len(name) > MAX_NAME_LENGTH:
            return f"A group name may be at most {MAX_NAME_LENGTH} characters."
        if [c for c in FORBIDDEN_IN_NAME if c in name]:
            return ("A group name may not contain a slash, a backslash or a "
                    "line break - the name is part of a web address when the "
                    "group is deleted.")
        return None

    def rename_group(self, old_name: str, new_name: str) -> GroupResult:
        """Rename a group and carry everything that points at it.

        A group's name is its identity in three other files - a scheduled task
        holds it plainly, a rule and an admin assignment hold it as
        "group:<name>". A rename that moved only groups.json would leave all
        three pointing at a group that does not exist, and each of them fails
        QUIETLY: the task reports it once a night, the rule resolves to nobody,
        the admin just loses a menu entry.

        THE ORDER IS THE SAFEGUARD. Four files cannot be written as one, so the
        references move FIRST and groups.json last. Interrupted in between, a
        reference points at a name that does not exist YET - which every caller
        already reports - rather than a renamed group nobody points at.
        """
        old_name = _normalised(old_name).strip()
        new_name = _normalised(new_name).strip()
        refusal = self._refuse_name(new_name)
        if refusal:
            return GroupResult(False, refusal)

        existing = self.find(old_name)
        if existing is None:
            return GroupResult(False, f"There is no group called '{old_name}'.")
        if _normalised(existing.name) == _normalised(new_name):
            return GroupResult(True, moved={})

        clash = self.find(new_name)
        if clash is not None:
            return GroupResult(False, f"A group called '{clash.name}' already exists.")

        from services.config.group_references import move_references

        moved = move_references(existing.name, new_name)
        try:
            with cross_process_lock(self._path):
                entries = self._read()
                for entry in entries:
                    if _normalised(entry["name"]).casefold() == _normalised(existing.name).casefold():
                        entry["name"] = new_name
                self._write(entries)
        except OSError as e:
            logger.error(f"Group '{existing.name}' could not be renamed: {e}", exc_info=True)
            return GroupResult(False, f"The group could not be renamed: {e}", moved=moved)
        logger.info(f"Group '{existing.name}' renamed to '{new_name}'; references moved: {moved}")
        return GroupResult(True, moved=moved)

    def save_group(self, name: str, containers: List[str],
                   active: Optional[bool] = None,
                   allowed_actions: Optional[List[str]] = None) -> GroupResult:
        """Create the group, or replace what the one with that name holds.

        ``active`` and ``allowed_actions`` are the GROUP's own permissions. Left
        out, an existing group keeps what it has and a new one gets the four
        standard actions - a caller that does not know about permissions must
        not silently take them away.
        """
        name = _normalised(name).strip()
        refusal = self._refuse_name(name)
        if refusal:
            return GroupResult(False, refusal)

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

        # Checked before the file is opened: a name the panel invented, or one
        # left over from a renamed action, would be stored, drawn as a tick and
        # do nothing when Discord pressed it.
        wanted_actions: List[str] = []
        if allowed_actions is not None:
            unknown = [a for a in allowed_actions if a not in KNOWN_ACTIONS]
            if unknown:
                return GroupResult(False, f"A group cannot be allowed to {', '.join(unknown)}.")
            for action in allowed_actions:
                if action not in wanted_actions:
                    wanted_actions.append(action)

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
                    if active is not None:
                        same_name[0]["active"] = bool(active)
                    if allowed_actions is not None:
                        same_name[0]["allowed_actions"] = wanted_actions
                else:
                    entries.append({
                        "name": name,
                        "containers": containers,
                        "active": True if active is None else bool(active),
                        "allowed_actions": (list(KNOWN_ACTIONS) if allowed_actions is None
                                            else wanted_actions),
                    })
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
        return [{"name": str(e["name"]),
                 "containers": list(e.get("containers", [])),
                 # A group from before 2026-09-24 has neither field; see
                 # ContainerGroup for why the answer is not "nothing".
                 "active": bool(e.get("active", True)),
                 "allowed_actions": [a for a in e.get("allowed_actions", KNOWN_ACTIONS)
                                     if a in KNOWN_ACTIONS]}
                for e in entries if isinstance(e, dict) and e.get("name")]

    def _write(self, entries: List[dict]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self._path, {"groups": entries})

    def _configured_container_names(self) -> set:
        """The containers DDC has a configuration for, active or not.

        ACTIVE OR NOT is the point (operator, 2026-09-24): a group is decoupled
        from the single-container control, so a container he switched off in
        DDC is still a member of its group and is still acted on through it.
        This used to ask ServerConfigService.get_all_servers(), which drops
        every inactive container by design - so a switched-off member was
        reported as one DDC "no longer has", and every caller left it out.

        The names are read from the container configuration directory itself
        for the same reason, and because it is the cheaper of the two: one
        directory listing instead of parsing every file. A file is named after
        its container by construction - container_config_save_service.py writes
        `<container_name>.json` - so the stem IS the name, not a guess (checked
        against the operator's server: 8 of 8 agree).

        WHAT IS STILL MISSING, and it is honest to say it here: a container DDC
        has never been configured for at all has no file, so a group naming it
        still reports it as gone. The panel can put such a container in a group
        - its picker lists everything on the host - and that gap is the next
        thing to close.

        For one second at a time. Resolving a group is not a rare thing: the
        watchdog does it per event per rule, and the admin overview asks on
        every redraw - measured at 20 full reads for 20 resolutions, on a config
        directory that lives on an SMB mount, from the bot's event loop. One
        second is short enough that a container added in the panel shows up in
        the next resolution, and long enough to collapse a whole watchdog cycle
        into one read.
        """
        now = time.monotonic()
        if self._names_cache is not None and now - self._names_read_at < 1.0:
            return self._names_cache

        directory = get_config_dir() / "containers"
        try:
            names = {path.stem for path in directory.glob("*.json")}
        except OSError as e:
            # Not an empty set quietly: every member of every group would be
            # reported as gone, and the callers would act on nothing.
            logger.error(f"The container configuration could not be listed: {e}")
            raise OSError(f"the container configuration could not be listed: {e}") from e
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
