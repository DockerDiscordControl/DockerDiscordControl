# -*- coding: utf-8 -*-
"""One unusable cooldown value costs one command, not all of them.

THE FINDING (review C62, section 19 F2): ``get_cooldown_for_command`` does
``commands.Cooldown(1, float(cooldown_seconds), BucketType.user)`` inside a
``try`` that catches ``TypeError``, and its fallback catches
``(RuntimeError, discord.Forbidden, discord.HTTPException, discord.NotFound)``
- network exceptions a plain constructor cannot raise. What ``float()`` on a
non-numeric setting raises is ``ValueError``, and nothing here catches that.

``apply_dynamic_cooldowns`` calls the method in a loop over every command,
with no guard around the call. So a single unusable value in the
spam-protection settings ends the loop then and there: every command after it
keeps whatever ``_buckets`` it had, the startup step logs nothing about it,
and the operator's cooldowns are simply not in force.
"""

import logging
from unittest.mock import MagicMock

from discord.ext import commands

import pytest

from services.infrastructure.dynamic_cooldown_manager import DynamicCooldownManager


def _command(name):
    command = MagicMock()
    command.name = name
    command._buckets = "untouched"
    return command


@pytest.fixture
def manager():
    manager = DynamicCooldownManager()
    manager.spam_manager = MagicMock()
    manager.spam_manager.is_enabled.return_value = True
    manager.spam_manager.load_settings.return_value = MagicMock(success=True)
    return manager


def test_an_unusable_value_is_refused_not_raised(manager):
    manager.spam_manager.get_command_cooldown.return_value = "sehr lange"

    assert manager.get_cooldown_for_command("control") is None


def test_an_unusable_value_is_named_in_the_log(manager, caplog):
    manager.spam_manager.get_command_cooldown.return_value = "sehr lange"

    with caplog.at_level(logging.DEBUG):
        manager.get_cooldown_for_command("control")

    assert [r for r in caplog.records if r.levelno >= logging.ERROR], (
        "a setting that cannot be used is silently dropped"
    )


def test_the_other_commands_still_get_their_cooldown(manager):
    """THE FINDING: the loop must not end on the first unusable value."""
    def _cooldown(config_key):
        return "sehr lange" if config_key == "control" else 5

    manager.spam_manager.get_command_cooldown.side_effect = _cooldown
    control, info = _command("control"), _command("info")
    bot = MagicMock(spec=["walk_commands"])
    bot.walk_commands = MagicMock(return_value=[control, info])

    manager.apply_dynamic_cooldowns(bot)

    assert info._buckets != "untouched", (
        "one unusable value in the settings and no command after it gets a cooldown"
    )


def test_a_normal_value_still_becomes_a_cooldown(manager):
    """Counter-check: refusing everything would pass the tests above."""
    manager.spam_manager.get_command_cooldown.return_value = 7

    cooldown = manager.get_cooldown_for_command("control")

    assert cooldown is not None
    assert cooldown.per == 7.0


def test_the_loop_survives_a_lookup_that_raises(manager, monkeypatch):
    """The two layers are independent, and each has to hold on its own.

    The guard in the loop is what makes the promise "one command, not all of
    them" hold for anything the lookup may raise in future - not only for the
    one value the layer below now catches (found by mutation M2 of review
    C62).
    """
    calls = []

    def _explodes(command_name):
        calls.append(command_name)
        if command_name == "control":
            raise RuntimeError("the settings file went away mid-loop")
        return commands.Cooldown(1, 5.0)

    manager.spam_manager.get_command_cooldown.return_value = 5
    monkeypatch.setattr(manager, "get_cooldown_for_command", _explodes)
    control, info = _command("control"), _command("info")
    bot = MagicMock(spec=["walk_commands"])
    bot.walk_commands = MagicMock(return_value=[control, info])

    manager.apply_dynamic_cooldowns(bot)

    assert calls == ["control", "info"], (
        "the loop stopped at the command whose lookup raised"
    )
    assert info._buckets != "untouched"
