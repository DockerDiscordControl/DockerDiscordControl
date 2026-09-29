# -*- coding: utf-8 -*-
"""A stack restart names every member it left out, with the right reason.

THE FINDING (stage 4 review before v3.1.0, section 01 pass 4 F5): the
"Not touched" line of a stack/group restart said "not in DDC, or switched
off" for two different lists - members DDC no longer has, and members an
assigned admin may not control - and switched-off members are in fact
restarted through the group. It also showed only the first 20 names, with no
"… and N more". (Reachable from overview messages posted before 2026-09-24,
whose stack button still works.)

THE CONTRACT: two lines, each with its own reason; a long list ends in
"… and N more"; "switched off" is not claimed.

HOW THIS TEST CAN FAIL: the reasons merge again, or names vanish without a
count.

COUNTER-CHECK (2026-09-29): red before the change.
"""

from types import SimpleNamespace

import cogs.admin_overview as ao
from tests.spec.test_a_stack_can_be_restarted_from_discord import (ADMIN_ID, CHANNEL, _cog,
                                                                     _interaction, world)  # noqa: F401


async def test_the_left_out_members_are_named_with_their_reason(world, monkeypatch):  # noqa: F811
    import cogs.stack_restart as sr
    members = [{"docker_name": f"m{n}", "active": True, "allowed_actions": ["restart"]}
               for n in range(25)]
    monkeypatch.setattr(sr, "_servers_of", lambda stack: (members, ["gone"]))
    monkeypatch.setattr(ao, "get_admin_service", lambda: SimpleNamespace(
        is_user_admin_async=lambda uid: _true(),
        controllable=lambda uid, servers: [s for s in servers if s["docker_name"] == "m0"]))

    inter = _interaction(ADMIN_ID)
    await sr.ConfirmRestartStackButton(_cog(), CHANNEL, "G").callback(inter)
    text = inter.followup.send.await_args.kwargs["embed"].description

    assert "switched off" not in text, text
    assert "gone" in text and "Not in DDC" in text, text
    assert "Not assigned to you" in text, text
    named = sum(f"`m{n}`" in text for n in range(1, 25))
    assert named == 24 or "more" in text, f"{24 - named} names vanished without a count: {text}"


async def _true():
    return True
