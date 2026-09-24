# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Everything outside groups.json that points at a group by name.

A group's name is its identity in three other files, in two spellings and
three shapes - all of them measured on the operator's own server, because the
first version of this module read shapes that only its test had:

    config/tasks.json        a LIST of tasks; the field is `container`, and
                             `target_is_group` says the name means a group
    config/auto_actions.json `auto_actions` beside `global_settings`; a rule
                             holds "group:<name>" in what it WATCHES and in
                             what it ACTS ON
    config/admins.json       `admin_containers` holds "group:<name>"

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

    AttributeError is caught with the rest on purpose: a file in a shape this
    module does not expect is what turned the first live rename into a 500.
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
    except (OSError, json.JSONDecodeError, ValueError, KeyError, TypeError,
            AttributeError, IndexError) as e:
        # Counted as zero, never raised: one unreadable file must not cost the
        # other two, and the rename itself is reported with what it did move.
        logger.error(f"References in {filename} could not be moved: {e}", exc_info=True)
        return 0


def _tasks(old: str, new: str) -> int:
    def change(document):
        # A LIST on disk. An older file that wrapped them in {"tasks": [...]}
        # is read as well rather than skipped in silence.
        tasks = document if isinstance(document, list) else (document.get("tasks") or [])
        moved = 0
        for task in tasks:
            if not isinstance(task, dict):
                continue
            # The flag is what makes it a group: a CONTAINER that happens to
            # share the name must not be renamed with it.
            if not task.get("target_is_group"):
                continue
            # `container` and nothing else: ScheduledTask.to_dict() writes
            # that one field, every time (services/scheduling/scheduler.py).
            # Reading a second spelling "to be safe" is how the invented one
            # got in - and how it would have stayed unnoticed.
            if task.get("container") == old:
                task["container"] = new
                moved += 1
        return moved

    return _rewrite("tasks.json", change)


def _rules(old: str, new: str) -> int:
    marked_old, marked_new = GROUP_PREFIX + old, GROUP_PREFIX + new

    def change(document):
        moved = 0
        # `auto_actions` and nothing else: that is the key
        # auto_action_config_service.py writes, every time. A second spelling
        # read "to be safe" is what let an invented one pass unnoticed.
        rules = document.get("auto_actions") or []
        for rule in rules:
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
