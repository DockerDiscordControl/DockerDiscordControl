# -*- coding: utf-8 -*-
# @covers Z5
"""Z5 - No action on a container without channel permission and an allowed action.

Start, stop and restart only happen if the channel carries the permission.
This guarantee requires NO user check - authorization via the channel is
intended (SPEC.md B1). It requires the channel check to be without gaps.

The finding: ``control_ui.py:304`` reads

    channel_has_control = is_admin_control or _get_cached_channel_permission(...)

where ``is_admin_control`` only means that the embed title contains the string
"Admin Control" (:297-301). A permission is thus stored in a **message**, not
in the configuration. As long as the panel sits in a control channel this is
redundant - ``/control`` already checks the permission
(``docker_control.py:1947``). It becomes a gap when the message outlives the
permission: panel posted, control permission revoked afterwards, panel still
usable.

Decided by the operator (2026-09-16): old panels become **ineffective
immediately**. A permission must not be stored in a message that can be months
old.

Not affected are the three purely presentational uses of the same heuristic
(:429, :1019-1025, :1072-1079) - they grant no permission but control the
display. This was specifically re-checked before this fix.

Why ``pending_actions`` is checked and not the Docker call: the latter runs in
a background task (``create_task``), and checking for it would be brittle. The
entry in ``pending_actions``, by contrast, is set synchronously at :329, before
anything starts in the background - if the action is refused, it stays absent.

That holds for the REFUSED direction and only for it. Since review D17 a press
that falls over takes its own mark back again, so a surviving entry is no
longer evidence that the gate was passed - the tripwire firing is. The allowed
case below checks that and the absence of a refusal instead.

COUNTER-CHECK (performed 2026-09-16):

Before the fix, ``test_admin_title_does_not_replace_the_revoked_channel_permission``
failed - and **more strongly than predicted**. I had expected a failure at
``pending_actions == {}``; in fact the tripwire at :332 already fired::

    cogs/control_ui.py:332: pending_embed = _get_pending_embed(...)
    E   _GatePassed

The log also showed ``[ACTION_BTN] STOP action for 'nginx' triggered by
Somebody``: without channel permission, purely because of the title, the
action was not merely queued but already in full swing.

After the fix 21 green, ``tests/unit/cogs`` unchanged 267 green.

Important here: a test that tripped over the tripwire before could be green
afterwards *because the wire no longer fires* - and not because the guarantee
holds. That is why ``_refusal_checked`` pins down the refusal text. Without it,
``followup.send.assert_awaited()`` would also have been satisfied by the path
at :294 (no channel).
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import cogs.control_ui as cui
from cogs.control_ui import ActionButton


class _GatePassed(Exception):
    """Tripwire: raised as soon as the channel check has been passed."""


def _interaction(*, embed_title: str | None):
    """Interaction whose message optionally carries an 'Admin Control' title."""
    inter = MagicMock()
    inter.response.send_message = AsyncMock()
    inter.response.defer = AsyncMock()
    inter.followup.send = AsyncMock()
    inter.edit_original_response = AsyncMock()
    inter.user.id = 4711
    inter.user.name = "Somebody"
    inter.channel.id = 300

    if embed_title is None:
        inter.message = None
    else:
        embed = SimpleNamespace(title=embed_title)
        inter.message = SimpleNamespace(embeds=[embed])
    return inter


def _button(action_name: str = "stop"):
    """ActionButton without the py-cord constructor.

    The real ``__init__`` pulls in ``discord.ui.Button`` and the static data
    cache. What should be checked is ``callback``, not the scaffolding.
    """
    b = ActionButton.__new__(ActionButton)
    b.cog = SimpleNamespace(pending_actions={})
    b.action = action_name
    b.server_config = {"docker_name": "nginx", "display_name": "nginx",
                       "allowed_actions": ["start", "stop", "restart"]}
    b.docker_name = "nginx"
    b.display_name = "nginx"
    return b


@pytest.fixture
def environment(monkeypatch):
    """Spam protection off, configuration present, tripwire behind the gate."""
    spam = MagicMock()
    spam.is_enabled.return_value = False
    monkeypatch.setattr(
        "services.infrastructure.spam_protection_service.get_spam_protection_service",
        lambda: spam,
    )
    monkeypatch.setattr(cui, "load_config", lambda: {"servers": []})

    def _tripwire(*_a, **_k):
        raise _GatePassed()

    monkeypatch.setattr(cui, "_get_pending_embed", _tripwire)
    return spam


def _refusal_checked(inter):
    """Prove that the refusal path really ran - not just any followup.

    ``followup.send`` is also used at :294 (no channel determinable). A mere
    ``assert_awaited()`` does not distinguish the two and would be green
    without the channel check ever having kicked in.
    """
    inter.followup.send.assert_awaited()
    texts = " ".join(str(a) for call in inter.followup.send.await_args_list
                     for a in call.args)
    assert "not allowed in this channel" in texts, (
        f"Something was sent, but not the refusal: {texts!r}"
    )


def _channel_permission(monkeypatch, *, allowed: bool):
    monkeypatch.setattr(
        cui, "_get_cached_channel_permission",
        lambda channel_id, key, config=None: allowed,
    )


async def test_admin_title_does_not_replace_the_revoked_channel_permission(environment, monkeypatch):
    """No channel permission, but 'Admin Control' in the title: the button must refuse.

    This is the case "panel outlives the permission": the message still sits in
    the channel, the permission is revoked - and the buttons must no longer work.
    """
    _channel_permission(monkeypatch, allowed=False)
    button = _button()
    inter = _interaction(embed_title="🛠️ Admin Control: nginx")

    await button.callback(inter)

    assert button.cog.pending_actions == {}, (
        "The container action was queued although the channel no longer has "
        "the control permission - the title of an old message replaced the "
        "permission"
    )
    _refusal_checked(inter)


async def test_without_channel_permission_and_without_admin_title_it_is_refused(environment, monkeypatch):
    """The base case - already holds today and is pinned down here."""
    _channel_permission(monkeypatch, allowed=False)
    button = _button()
    inter = _interaction(embed_title=None)

    await button.callback(inter)

    assert button.cog.pending_actions == {}
    _refusal_checked(inter)


async def test_with_channel_permission_it_proceeds(environment, monkeypatch):
    """The allowed side: with channel permission the button passes the gate.

    Without this case one could tighten the check to "always refuse" and the
    two tests above would stay green.
    """
    _channel_permission(monkeypatch, allowed=True)
    button = _button()
    inter = _interaction(embed_title=None)

    with pytest.raises(_GatePassed):
        await button.callback(inter)

    # The tripwire firing IS the evidence that the gate was passed. This used
    # to also assert that the entry in pending_actions survived - it does not
    # any more, and must not: since review D17 a press that falls over takes
    # its own mark back, or the container would show "Pending" for an action
    # that never ran. What is checked instead is that no refusal was sent,
    # which is the other half of "the gate let it through".
    sent = " ".join(str(argument) for call in inter.followup.send.await_args_list
                    for argument in call.args)
    assert "not allowed in this channel" not in sent, sent
