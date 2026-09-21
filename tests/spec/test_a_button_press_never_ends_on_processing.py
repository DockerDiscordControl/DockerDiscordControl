# -*- coding: utf-8 -*-
"""A button press never leaves the message on "Processing...".

THE FINDING (review D31, pass 2, section 02 F2): pressing Start, Stop or
Restart walks the message through three states - the pending embed, then
"⏳ Processing... Please wait ~15 seconds" with `view=None` (so the buttons
are gone), and finally, fifteen seconds later, the refreshed status with its
buttons back.

The last step runs in a background task, and both handlers on the way there
list only some exception types:

    except (discord.errors.DiscordException, RuntimeError)   # update_all_views
    except (RuntimeError, OSError, asyncio.TimeoutError)     # run_docker_action

An AttributeError, KeyError or TypeError from the status lookup or from
`_generate_status_embed_and_view` is caught by neither. The task dies, the
done-callback writes a line in the log - and the message in Discord stays on
"⏳ Processing..." with no buttons, for good. Nothing ever edits it again.

The container itself is fine and `pending_actions` is cleared, so the
container is controllable from a freshly rendered panel. It is THIS message
that is dead, and it is the one the operator is looking at.

That is the sharpest kind of defect for this programme: the failure is
visible, permanent, and says "please wait".

What the message says now depends on how far the press got, because the two
cases are not the same thing:

  the action ran, only the refresh failed  ->  say so, and say the panel is stale
  the action did not get that far          ->  say the action failed

Guessing one message for both would put "the action was carried out" under a
press that never reached Docker.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import cogs.control_ui as cui
from cogs.control_ui import ActionButton


def _interaction():
    inter = MagicMock()
    inter.response.send_message = AsyncMock()
    inter.response.defer = AsyncMock()
    inter.followup.send = AsyncMock()
    inter.edit_original_response = AsyncMock()
    inter.user.id = 4711
    inter.user.name = "Somebody"
    inter.channel.id = 300
    inter.message = None
    return inter


def _button():
    button = ActionButton.__new__(ActionButton)
    button.cog = SimpleNamespace(
        pending_actions={},
        status_cache_service=SimpleNamespace(get=lambda name: None,
                                             remove=lambda name: None,
                                             set=lambda *a, **k: None),
        expanded_states={},
        channel_server_message_ids={},
        get_status=AsyncMock(),
        # Returns the triple the caller unpacks - the counter-case below found
        # this stub returning a MagicMock and reported a healthy press as a
        # failure, which is exactly what it is there for.
        _generate_status_embed_and_view=AsyncMock(
            return_value=(SimpleNamespace(title="nginx"), None, None)),
        _update_overview_message=AsyncMock(),
    )
    button.action = "stop"
    button.server_config = {"docker_name": "nginx", "display_name": "nginx",
                            "allowed_actions": ["start", "stop", "restart"]}
    button.docker_name = "nginx"
    button.display_name = "nginx"
    return button


@pytest.fixture
def environment(monkeypatch):
    """Everything around the press stubbed; only the failure is real."""
    spam = MagicMock()
    spam.is_enabled.return_value = False
    monkeypatch.setattr(
        "services.infrastructure.spam_protection_service.get_spam_protection_service",
        lambda: spam)
    monkeypatch.setattr(cui, "load_config", lambda: {"servers": []})
    monkeypatch.setattr(cui, "_get_cached_channel_permission",
                        lambda channel_id, key, config=None: True)
    monkeypatch.setattr(cui, "log_user_action", lambda **kwargs: None)
    monkeypatch.setattr(cui, "_get_pending_embed",
                        lambda name: SimpleNamespace(title="⏳ Pending", description=""))
    monkeypatch.setattr(cui, "get_server_config_service",
                        lambda: SimpleNamespace(get_all_servers=lambda: [
                            {"docker_name": "nginx", "display_name": "nginx"}]))
    monkeypatch.setattr(
        "services.infrastructure.container_status_service.get_container_status_service",
        lambda: SimpleNamespace(invalidate_container=lambda name: None))
    # The press waits ~26 s while polling and another 15 s before refreshing.
    async def _no_wait(_seconds):
        return None
    monkeypatch.setattr(asyncio, "sleep", _no_wait)
    return monkeypatch


def _titles(interaction):
    return [str(call.kwargs.get("embed").title)
            for call in interaction.edit_original_response.await_args_list
            if call.kwargs.get("embed") is not None]


async def _press_and_settle(button, interaction):
    await button.callback(interaction)
    # The refresh is a background task; let it finish before looking.
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


async def test_a_refresh_that_falls_over_says_so(environment, monkeypatch):
    """update_all_views dies with a type nobody listed."""
    monkeypatch.setattr(
        "services.docker_service.docker_action_service.docker_action_service_first",
        AsyncMock(return_value=True))
    button = _button()
    # The polling loop succeeds, the later refresh does not.
    calls = {"n": 0}

    async def _get_status(server_config):
        calls["n"] += 1
        if calls["n"] > 1:
            raise AttributeError("'NoneType' object has no attribute 'id'")
        return SimpleNamespace(success=True, is_running=False)

    button.cog.get_status = _get_status
    interaction = _interaction()

    await _press_and_settle(button, interaction)

    titles = _titles(interaction)
    assert titles, "the message was never edited at all"
    assert "Processing" not in titles[-1], (
        f"the message was left on {titles[-1]!r} - no buttons, and it says "
        f"'please wait' about something that already stopped"
    )


async def test_a_press_that_never_got_to_docker_says_that_instead(environment, monkeypatch):
    """The other case: the failure happens before the action ran."""
    monkeypatch.setattr(
        "services.docker_service.docker_action_service.docker_action_service_first",
        AsyncMock(side_effect=AttributeError("service exploded")))
    button = _button()
    interaction = _interaction()

    await _press_and_settle(button, interaction)

    titles = _titles(interaction)
    assert titles, "the message was never edited at all"
    assert "Pending" not in titles[-1], (
        f"the message was left on {titles[-1]!r} - the press died before "
        f"Docker was ever asked and the panel still shows it as pending"
    )
    # Which of the two messages matters as much as that there is one. This
    # assertion was missing on the first run and a probe found the gap: with
    # action_done hard-wired to True the test stayed green while the panel
    # told the operator that an action which never reached Docker had been
    # carried out.
    assert "Failed" in titles[-1], (
        f"the press never reached Docker and the panel says {titles[-1]!r}, "
        f"which claims the action was carried out"
    )


async def test_a_press_that_works_still_ends_on_a_status(environment, monkeypatch):
    """The counter-case: a healthy press must not be told anything failed."""
    monkeypatch.setattr(
        "services.docker_service.docker_action_service.docker_action_service_first",
        AsyncMock(return_value=True))
    button = _button()
    button.cog.get_status = AsyncMock(
        return_value=SimpleNamespace(success=True, is_running=False))
    interaction = _interaction()

    await _press_and_settle(button, interaction)

    titles = _titles(interaction)
    assert not any("could not" in t.lower() or "failed" in t.lower() for t in titles), (
        f"a press that worked was reported as a failure: {titles}"
    )
