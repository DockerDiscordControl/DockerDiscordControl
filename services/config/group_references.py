# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Everything outside groups.json that points at a group by name.

A group's name is its identity in three other files, in two spellings:

    config/tasks.json        a scheduled task holds the PLAIN name, and says
                             so with target_is_group
    config/auto_actions.json a rule holds "group:<name>", in what it watches
                             and in what it acts on
    config/admins.json       a per-admin assignment holds "group:<name>"

Renaming a group without moving these would leave all three pointing at a name
that does not exist, and every one of them fails QUIETLY: the task reports it
once a night, the rule resolves to nobody, the admin simply loses a menu
entry. Whoever adds a fourth place that stores a group name adds it here.

EACH FILE ON ITS OWN. One that cannot be read or written is logged and counted
as zero; it must not cost the operator the other two, and it must not cost him
the rename - a reference left behind is the state the rename order was chosen
for (services/config/group_service.py).
"""

from __future__ import annotations

import json
from typing import Dict

from services.config.group_service import GROUP_PREFIX
from utils.atomic_io import atomic_write_json, cross_process_lock
from utils.config_paths import get_config_dir
from utils.logging_utils import get_module_logger

logger = get_module_logger('group_references')


def _rewrite(filename: str, change) -> int:
    """Read the file, let ``change`` rework it, write it back if it said so.

    ``change(document)`` returns how many names it moved; zero means the file
    is left untouched, which keeps a rename from rewriting three files that had
    nothing to do with it.
    """
    path = get_config_dir() / filename
    if not path.exists():
        return 0
    try:
        with cross_process_lock(path):
            with open(path, "r", encoding="utf-8") as handle:
                document = json.load(handle)
            moved = change(document)
            if moved:
                atomic_write_json(path, document)
            return moved
    except (OSError, json.JSONDecodeError, ValueError, KeyError, TypeError) as e:
        # Counted as zero, never raised: one unreadable file must not cost the
        # other two, and the rename itself is reported with what it did move.
        logger.error(f"References in {filename} could not be moved: {e}", exc_info=True)
        return 0


def _tasks(old: str, new: str) -> int:
    def change(document):
        moved = 0
        for task in document.get("tasks", []) or []:
            if not isinstance(task, dict):
                continue
            # The flag is what makes it a group: a CONTAINER that happens to
            # share the name must not be renamed with it.
            if task.get("target_is_group") and task.get("container_name") == old:
                task["container_name"] = new
                moved += 1
        return moved

    return _rewrite("tasks.json", change)


def _rules(old: str, new: str) -> int:
    marked_old, marked_new = GROUP_PREFIX + old, GROUP_PREFIX + new

    def change(document):
        moved = 0
        for rule in document.get("rules", []) or []:
            if not isinstance(rule, dict):
                continue
            # Both sides: a rule names a group in what it WATCHES and in what
            # it ACTS ON, and they are set independently.
            for part in ("trigger", "action"):
                section = rule.get(part)
                if not isinstance(section, dict):
                    continue
                names = section.get("containers")
                if not isinstance(names, list):
                    continue
                for index, name in enumerate(names):
                    if name == marked_old:
                        names[index] = marked_new
                        moved += 1
        return moved

    return _rewrite("auto_actions.json", change)


def _admins(old: str, new: str) -> int:
    marked_old, marked_new = GROUP_PREFIX + old, GROUP_PREFIX + new

    def change(document):
        moved = 0
        assignments = document.get("admin_containers")
        if not isinstance(assignments, dict):
            return 0
        for names in assignments.values():
            if not isinstance(names, list):
                continue
            for index, name in enumerate(names):
                if name == marked_old:
                    names[index] = marked_new
                    moved += 1
        return moved

    return _rewrite("admins.json", change)


def move_references(old: str, new: str) -> Dict[str, int]:
    """Point every reference at the new name; how many, per file."""
    return {"tasks": _tasks(old, new),
            "rules": _rules(old, new),
            "admins": _admins(old, new)}
