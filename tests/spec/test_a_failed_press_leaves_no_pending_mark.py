# -*- coding: utf-8 -*-
"""A button press that fell over leaves no container marked as pending.

THE FINDING (review D17, pass 2, section 02 F1): `ActionButton.callback`
writes `pending_actions[docker_name]` and only then does the work. Every path
it knows about removes the entry again - the expired interaction, the failed
Docker action, the outer handler. That outer handler names
`(discord.errors.DiscordException, RuntimeError, OSError)`, so anything else
raised in between - a KeyError or TypeError from `_get_pending_embed`, a
failure inside `log_user_action` - leaves the mark behind.

THE REPORTED CONSEQUENCE IS WRONG, and the correction matters: the reviewer
said the container's buttons stay hidden "until a bot restart". They do not.
`docker_control.py` sweeps a pending entry older than 120 seconds on the next
status render. What is left is up to two minutes in which DDC shows
"Pending" for an action that never ran and never will, with the container's
control buttons gone - rated medium, not critical.
"""

from types import SimpleNamespace

import pytest

from cogs import control_ui

CONTAINER = "web"


class _Response:
    def __init__(self):
        self.done = False

    def is_done(self):
        return self.done

    async def defer(self, **kwargs):
        self.done = True

    async def send_message(self, *args, **kwargs):
        self.done = True


class _Followup:
    async def send(self, *args, **kwargs):
        return None


class _Interaction:
    def __init__(self):
        self.response = _Response()
        self.followup = _Followup()
        self.user = SimpleNamespace(id=7, name="max")
        self.channel = SimpleNamespace(id=2)

    async def edit_original_response(self, **kwargs):
        return None


@pytest.fixture
def button(monkeypatch):
    """An action button whose channel permits control."""
    # The callback opens with the spam check and reads the configuration. Both
    # have to answer, or it returns before it ever reaches the part under test -
    # which is exactly what happened to the first version of this file: three
    # "green" cases that never got past the cooldown.
    import services.infrastructure.spam_protection_service as spam_module
    monkeypatch.setattr(spam_module, "get_spam_protection_service",
                        lambda: SimpleNamespace(is_enabled=lambda: False))
    monkeypatch.setattr(control_ui, "load_config", lambda: {"servers": [], "language": "en"})
    monkeypatch.setattr(control_ui, "_get_cached_channel_permission",
                        lambda channel_id, key, config: True)
    monkeypatch.setattr(control_ui, "_is_registered_admin", lambda user_id: False)

    instance = object.__new__(control_ui.ActionButton)
    instance.action = "restart"
    instance.docker_name = CONTAINER
    instance.display_name = CONTAINER
    instance.server_config = {"docker_name": CONTAINER, "allowed_actions": ["restart"]}
    instance.cog = SimpleNamespace(pending_actions={})
    return instance


@pytest.mark.parametrize("failure", [KeyError("embed"), TypeError("bad shape"),
                                     ValueError("nonsense")])
@pytest.mark.asyncio
async def test_the_mark_is_gone_after_a_failed_press(button, monkeypatch, failure):
    def _explode(display_name):
        raise failure

    monkeypatch.setattr(control_ui, "_get_pending_embed", _explode)

    with pytest.raises(type(failure)):
        await button.callback(_Interaction())

    assert CONTAINER not in button.cog.pending_actions, (
        "the press fell over and the container is still marked as pending - "
        "its buttons are gone until the 120 s sweep"
    )


@pytest.mark.asyncio
async def test_an_error_the_handler_knew_is_still_cleaned_up(button, monkeypatch):
    """Counter-check: what the clause already caught must keep working."""
    def _explode(display_name):
        raise RuntimeError("as before")

    monkeypatch.setattr(control_ui, "_get_pending_embed", _explode)

    await button.callback(_Interaction())

    assert CONTAINER not in button.cog.pending_actions


@pytest.mark.asyncio
async def test_a_press_that_works_still_marks_it(button, monkeypatch):
    """Counter-check: the mark is the point - a running action must show it."""
    import discord

    monkeypatch.setattr(control_ui, "_get_pending_embed",
                        lambda display_name: discord.Embed(description="pending"))
    monkeypatch.setattr(control_ui, "log_user_action",
                        lambda **kwargs: None, raising=False)

    started = {}

    def _create_task(coro, *args, **kwargs):
        started["task"] = True
        coro.close()
        return SimpleNamespace(add_done_callback=lambda callback: None)

    monkeypatch.setattr(control_ui.asyncio, "create_task", _create_task)

    await button.callback(_Interaction())

    assert started.get("task")
    assert CONTAINER in button.cog.pending_actions
