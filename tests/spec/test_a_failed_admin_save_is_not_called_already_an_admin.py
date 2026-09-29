# -*- coding: utf-8 -*-
"""/addadmin says "could not save" when the save failed - not "already an admin".

THE FINDING (stage 4 review before v3.1.0, section 06 pass 4 F2 and
section 10 pass 4 F3, the same defect, verified 2026-09-29).
AdminService.add_admin_user returned False both for "already on the list"
and for "the save failed", and AddAdminModal read every False as "⚠️ This
user is already an admin." - its own "Failed to save" branch was dead
(success = True was set unconditionally). An admin who was never added was
reported as present.

THE CONTRACT: a failed save is reported as a failure; "already an admin"
only when the id is on the list.

HOW THIS TEST CAN FAIL: the two cases share one answer again.

It goes through the real AdminService on a temp config dir with the
atomic rename failing, and the real modal callback.

COUNTER-CHECK (2026-09-29): written before the fix and red then.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

NEW_ID = "123456789012345678"


@pytest.fixture
def modal_world(tmp_path, monkeypatch):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    (tmp_path / "admins.json").write_text(json.dumps({"discord_admin_users": ["111111111111111111"]}),
                                          encoding="utf-8")
    from services.admin import admin_service as module
    monkeypatch.setattr(module, "_admin_service_instance", None)
    return tmp_path, module


def _interaction():
    interaction = MagicMock()
    interaction.user.id = 1
    interaction.user.name = "op"
    interaction.response.send_message = AsyncMock()
    interaction.response.is_done = MagicMock(return_value=False)
    return interaction


def _submit(monkeypatch):
    from cogs.donation_ui import AddAdminModal
    modal = AddAdminModal.__new__(AddAdminModal)
    modal.user_id_input = MagicMock(value=NEW_ID)
    interaction = _interaction()
    asyncio.run(AddAdminModal.callback(modal, interaction))
    return str(interaction.response.send_message.await_args)


def test_a_failed_save_is_reported_as_a_failure(modal_world, monkeypatch):
    _dir, module = modal_world
    monkeypatch.setattr(module.os, "replace", MagicMock(side_effect=OSError("disk full")))

    said = _submit(monkeypatch)

    assert "already an admin" not in said, said


def test_a_present_admin_is_still_called_present(modal_world, monkeypatch):
    """Counter-check."""
    tmp_path, _module = modal_world
    (tmp_path / "admins.json").write_text(json.dumps({"discord_admin_users": [NEW_ID]}), encoding="utf-8")

    assert "already an admin" in _submit(monkeypatch)
