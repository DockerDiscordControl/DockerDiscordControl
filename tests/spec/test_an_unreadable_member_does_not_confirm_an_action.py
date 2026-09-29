# -*- coding: utf-8 -*-
"""A group member whose status cannot be read does not let the action count as confirmed.

THE FINDING (stage 4 review before v3.1.0, section 01, found by both passes,
verified 2026-09-29). wait_until_the_action_took_effect left a target whose
status read failed out of `running` with a `continue`, and _has_taken_effect
judged only the members it could read: a start of a group whose other
members were up returned True - "the action showed" - with one member never
confirmed, and the panel skipped its "Not confirmed yet" notice. The
function's own docstring says it exists to prevent exactly "acts on fewer
and reports done".

THE CONTRACT: every target has to be read and show the action; a target
that cannot be read keeps the verdict open, and at the end of the ladder it
is False, not True.

HOW THIS TEST CAN FAIL: an unreadable member is skipped and the rest decide
again.

COUNTER-CHECK (2026-09-29): written before the fix and red then (True).
"""

import asyncio
from types import SimpleNamespace

from tests.spec.test_waiting_for_an_action_asks_about_the_thing_that_acted import (  # noqa: F401
    _Cog, world)


class _HalfBlindCog(_Cog):
    """beta's status can never be read."""

    async def get_status(self, config):
        name = config.get("docker_name")
        self.asked.append(name)
        if name == "beta":
            return SimpleNamespace(success=False, is_running=False, display_name=name)
        return SimpleNamespace(success=True, is_running=self.states[name], display_name=name)


def test_a_start_is_not_confirmed_with_a_member_unread(world):
    cog = _HalfBlindCog({"alpha": True, "beta": True})

    verdict = asyncio.run(world.module.wait_until_the_action_took_effect(
        cog, "group:Gameserver", "Gameserver", "start"))

    assert verdict is False, f"confirmed with beta never read: {verdict}"


def test_a_stop_is_not_confirmed_with_a_member_unread(world):
    cog = _HalfBlindCog({"alpha": False, "beta": False})

    verdict = asyncio.run(world.module.wait_until_the_action_took_effect(
        cog, "group:Gameserver", "Gameserver", "stop"))

    assert verdict is False, f"confirmed with beta never read: {verdict}"


def test_all_members_read_and_up_is_still_confirmed(world):
    """Counter-check: the ordinary case stays True."""
    cog = _Cog({"alpha": True, "beta": True})

    assert asyncio.run(world.module.wait_until_the_action_took_effect(
        cog, "group:Gameserver", "Gameserver", "start")) is True
