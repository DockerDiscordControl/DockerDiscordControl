# -*- coding: utf-8 -*-
"""Buttons on messages posted before a restart keep working - through the cog split (Phase 3).

``DockerControlCog`` is 4,494 lines in one class and is being cut into pieces
(roadmap Phase 3). The one thing a user would notice is a button on an old
Discord message that no longer answers. py-cord routes a click by
``(component type, message id, custom id)``; class names do not matter, but
the routing only exists for views registered with ``bot.add_view`` - in
``_register_persistent_mech_views``, once per tracked channel. A move that
drops one ``add_view`` line, or loses where the channel loop gets its
channels, keeps every custom_id format test green and silently kills buttons.

So this ratchet runs the registration with a fake bot, catches every
``add_view`` and compares the full key set - and the slash command names -
with the lists below. Any change is red: a removal breaks old messages, an
addition must be written down on purpose.

Found while writing it: outside a running event loop the views raise
RuntimeError, which the method logs as a warning and swallows - zero
registrations and nothing but a log line. The test runs inside a loop and
also fails on that warning, so a registration that stops working cannot
pass as "nothing registered".

COUNTER-CHECK (2026-09-22): deleting the MechDetailsView add_view line turns
the key test red (two keys missing); renaming a slash command turns the
command test red.
"""

from unittest.mock import MagicMock

import pytest

CHANNEL, OVERVIEW, ADMIN_OVERVIEW = 111, 555, 666
BUTTON = 2  # discord.ComponentType.button

EXPECTED_KEYS = {
    # the overview message, bound to its tracked message id
    *((BUTTON, OVERVIEW, f"{name}_{CHANNEL}") for name in ("admin_button", "help_button", "info_button", "mech_details")),
    # the admin overview message, bound to its tracked message id
    *((BUTTON, ADMIN_OVERVIEW, f"admin_overview_{name}_{CHANNEL}")
      for name in ("admin", "donate", "restart_all", "stop_all")),
    # per-channel mech buttons, any message
    *((BUTTON, None, f"{name}_{CHANNEL}") for name in (
        "mech_expand", "mech_collapse", "mech_donate", "mech_history",
        "mech_private_donate", "mech_private_history")),
    # channel-independent mech buttons
    (BUTTON, None, "epilogue_button"),
    *((BUTTON, None, f"{kind}_{level}") for kind in ("mech_display", "read_story", "play_song")
      for level in range(1, 12)),
}

EXPECTED_SLASH_COMMANDS = {"addadmin", "control", "donate", "help", "info", "ping", "serverstatus", "ss"}


@pytest.mark.asyncio
async def test_every_persistent_button_is_registered(caplog):
    from cogs.docker_control import DockerControlCog

    seen = set()

    class FakeBot:
        def add_view(self, view, message_id=None):
            for item in view.children:
                seen.add((int(item.type.value), message_id, item.custom_id))

    cog = MagicMock()
    cog.bot = FakeBot()
    cog.channel_server_message_ids = {CHANNEL: {"overview": OVERVIEW, "admin_overview": ADMIN_OVERVIEW}}
    DockerControlCog._register_persistent_mech_views(cog)

    failures = [r.getMessage() for r in caplog.records if "Could not register persistent" in r.getMessage()]
    assert not failures, failures
    assert seen == EXPECTED_KEYS, (
        f"missing (old buttons stop answering): {sorted(EXPECTED_KEYS - seen, key=str)}\n"
        f"new (write them down on purpose): {sorted(seen - EXPECTED_KEYS, key=str)}"
    )


def test_the_slash_commands_keep_their_names():
    from cogs.docker_control import DockerControlCog

    names = {command.name for command in DockerControlCog.__cog_commands__}
    assert names == EXPECTED_SLASH_COMMANDS, sorted(names ^ EXPECTED_SLASH_COMMANDS)
