# -*- coding: utf-8 -*-
"""The info admin buttons ask for the permission at the press, not only when the panel opened.

THE FINDING (stage 4 review before v3.1.0, section 09, found by both passes,
verified 2026-09-29). ContainerInfoAdminView carries four buttons and lives
for up to 890 s. Only ProtectedInfoEditButton asked, at the press, whether
the channel still has 'control' or the admin may still act on this
container (review F3). EditInfoButton (📝, opens the info editor) and
DebugLogsButton (📋, shows container logs) asked nothing: after a channel
lost its control right - or an admin's assignment was narrowed - an open
panel kept editing the info and showing the logs. SPEC Z5: a permission is
read at the press.

THE CONTRACT: all three act only when the channel has control or the admin
may act on this container at the moment of the press - one check, one place.

HOW THIS TEST CAN FAIL: a button acts on the permission of the moment the
panel was opened again.

COUNTER-CHECK (2026-09-29): written before the fix and red then.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def refused(monkeypatch):
    import cogs.control_helpers as helpers
    monkeypatch.setattr(helpers, "_channel_has_permission", lambda *a: False)
    monkeypatch.setattr(helpers, "_admin_may_control", lambda *a: False)
    spam = MagicMock()
    spam.is_enabled.return_value = False
    monkeypatch.setattr("services.infrastructure.spam_protection_service.get_spam_protection_service",
                        lambda: spam)
    monkeypatch.setattr("services.config.config_service.load_config", lambda: {})


def _interaction():
    interaction = MagicMock()
    interaction.channel_id = 5
    interaction.user.id = 7
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.response.send_modal = AsyncMock()
    interaction.response.is_done = MagicMock(return_value=False)
    interaction.followup.send = AsyncMock()
    return interaction


SERVER = {"docker_name": "valheim", "name": "Valheim"}


def test_the_info_editor_does_not_open(refused):
    from cogs.status_info_integration import EditInfoButton
    interaction = _interaction()

    asyncio.run(EditInfoButton(MagicMock(), SERVER, {}).callback(interaction))

    interaction.response.send_modal.assert_not_awaited()
    assert "not allowed" in str(interaction.response.send_message.await_args)


def test_the_logs_are_not_shown(refused):
    from cogs.status_info_integration import DebugLogsButton
    interaction = _interaction()

    asyncio.run(DebugLogsButton(MagicMock(), SERVER).callback(interaction))

    sent = [str(c) for c in interaction.followup.send.await_args_list]
    assert len(sent) == 1 and "not allowed" in sent[0], sent


def test_the_protected_editor_still_refuses(refused):
    """Counter-check: the button that already asked keeps asking."""
    from cogs.status_info_integration import ProtectedInfoEditButton
    interaction = _interaction()

    asyncio.run(ProtectedInfoEditButton(MagicMock(), SERVER, {}).callback(interaction))

    interaction.response.send_modal.assert_not_awaited()
