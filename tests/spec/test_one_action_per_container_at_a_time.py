# -*- coding: utf-8 -*-
"""One Docker action per container at a time, whoever presses.

THE FINDING (audit 2026-09-26, spam protection F2). The spam brake is per user
and per action NAME: two users could stop and restart the same container at
the same moment, and one user could alternate stop, start and restart, three
separate buckets. ActionButton wrote pending_actions[container] and never
asked it. With spam protection switched off, nothing at all stood between a
control channel and a container hammered as fast as Discord allows.

THE CONTRACT: while an action on a container is running (its entry is younger
than PENDING_ACTION_SECONDS), another press on that container is refused with
a message and runs nothing. A stale entry (a lost interaction) does not lock
the container.

COUNTER-CHECK (2026-09-26): red before the fix - the second press went past
the check and reached the action.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import cogs.control_ui as cui
from cogs.control_ui import ActionButton


class _Reached(Exception):
    """Tripwire: the press got past every check."""


def _button(pending):
    button = ActionButton.__new__(ActionButton)
    button.cog = SimpleNamespace(pending_actions=pending)
    button.action = "restart"
    button.server_config = {"docker_name": "nginx", "display_name": "nginx",
                            "allowed_actions": ["start", "stop", "restart"]}
    button.docker_name = "nginx"
    button.display_name = "nginx"
    return button


def _interaction():
    inter = MagicMock()
    inter.response.defer = AsyncMock()
    inter.followup.send = AsyncMock()
    inter.edit_original_response = AsyncMock()
    inter.user.id = 4711
    inter.user.name = "Somebody"
    inter.channel.id = 300
    inter.message = None
    return inter


@pytest.fixture(autouse=True)
def environment(monkeypatch):
    spam = MagicMock()
    spam.is_enabled.return_value = False          # the worst case: no brake at all
    monkeypatch.setattr("services.infrastructure.spam_protection_service.get_spam_protection_service",
                        lambda: spam)
    monkeypatch.setattr(cui, "load_config", lambda: {"servers": []})
    from tests.spec import configured_as_drawn
    configured_as_drawn(monkeypatch, cui)  # asked at the press (stage 4, section 02)
    monkeypatch.setattr(cui, "_get_cached_channel_permission", lambda *a, **k: True)

    def _tripwire(*_a, **_k):
        raise _Reached()

    monkeypatch.setattr(cui, "_get_pending_embed", _tripwire)


def _entry(age_seconds):
    return {"action": "stop", "timestamp": datetime.now(timezone.utc) - timedelta(seconds=age_seconds),
            "user": "Other", "display_name": "nginx"}


@pytest.mark.asyncio
async def test_a_second_action_on_a_busy_container_is_refused():
    inter = _interaction()

    await _button({"nginx": _entry(5)}).callback(inter)       # must not raise _Reached

    text = " ".join(str(a) for call in inter.followup.send.await_args_list for a in call.args)
    assert "still running" in text, text


@pytest.mark.asyncio
async def test_a_free_container_is_acted_on():
    """Counter-case."""
    with pytest.raises(_Reached):
        await _button({}).callback(_interaction())


@pytest.mark.asyncio
async def test_a_stale_entry_does_not_lock_the_container():
    with pytest.raises(_Reached):
        await _button({"nginx": _entry(__import__("cogs.control_helpers", fromlist=["x"]).PENDING_ACTION_SECONDS + 5)}).callback(_interaction())
