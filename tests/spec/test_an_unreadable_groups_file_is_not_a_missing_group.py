# -*- coding: utf-8 -*-
"""An unreadable groups.json is not reported as a group that no longer exists.

THE FINDING (stage 4 review before v3.1.0, section 38 pass 4): when
groups.json could not be read while a group's admin panel was redrawn
after a press, the panel said "This group does not exist any more." in
red - false: the file is unreadable, the group may well be there. The
operator is sent to recreate a group that exists.

THE CONTRACT: a read failure says so, in gold, and asks to try again;
"does not exist" is kept for a group that is really gone.

HOW THIS TEST CAN FAIL: the read failure is called a missing group again.

COUNTER-CHECK (2026-09-30): red before the change (the missing-group text,
red).
"""

from types import SimpleNamespace

import discord

import cogs.group_control as group_control


def _service(find):
    return SimpleNamespace(find=find, members_of=lambda name: None)


def test_a_read_failure_says_so(monkeypatch):
    def unreadable(name):
        raise OSError("groups.json could not be read: permission denied")
    monkeypatch.setattr("services.config.group_service.get_group_service", lambda: _service(unreadable))

    embed = group_control.group_panel_embed("G", None)

    assert embed.description != group_control._("This group does not exist any more.")
    assert embed.description == group_control._("The groups file could not be read - try again.")
    assert embed.color == discord.Color.gold()


def test_a_group_that_is_gone_is_still_called_gone(monkeypatch):
    monkeypatch.setattr("services.config.group_service.get_group_service",
                        lambda: _service(lambda name: None))
    embed = group_control.group_panel_embed("G", None)
    assert embed.description == group_control._("This group does not exist any more.")
    assert embed.color == discord.Color.red()
