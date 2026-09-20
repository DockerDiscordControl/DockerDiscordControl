# -*- coding: utf-8 -*-
"""Saving the plain info modal does not revert protected info changed meanwhile.

No ``@covers`` marker: a finding, not a guarantee.

THE FINDING (stage 4 review, stage B, section 07 F1, re-checked 2026-09-20):
``SimplifiedContainerInfoModal`` reads the container's info when it is
OPENED and, on submit, writes the protected fields back from that snapshot
"to preserve existing protected info". The modal lives 300 s. Anything
changed through the protected-info modal in between is silently reverted -
and the user is told the save worked.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from cogs.enhanced_info_modal_simple import SimplifiedContainerInfoModal

WHEN_OPENED = {"enabled": True, "custom_text": "old text", "custom_ip": "", "custom_port": "",
               "show_ip": False, "protected_enabled": True,
               "protected_content": "old secret", "protected_password": "old-pass"}
CHANGED_MEANWHILE = dict(WHEN_OPENED, protected_content="new secret",
                         protected_password="new-pass")


def _field(value):
    return SimpleNamespace(value=value)


def _submit(monkeypatch, current_info):
    info_service = MagicMock()
    info_service.get_container_info.return_value = SimpleNamespace(
        success=True, data=SimpleNamespace(to_dict=lambda: dict(current_info)))
    saved = {}
    info_service.save_container_info.side_effect = (
        lambda name, info: saved.update(name=name, info=info) or SimpleNamespace(success=True))
    monkeypatch.setattr(
        "services.infrastructure.container_info_service.get_container_info_service",
        lambda: info_service)
    monkeypatch.setattr("services.infrastructure.action_logger.log_user_action",
                        MagicMock(), raising=False)

    modal = SimplifiedContainerInfoModal.__new__(SimplifiedContainerInfoModal)
    modal.container_name = "vrising"
    modal.display_name = "V-Rising"
    modal.info_service = info_service
    modal.container_info = dict(WHEN_OPENED)          # the snapshot from opening time
    modal.custom_text = _field("new text")
    modal.custom_ip = _field("")
    modal.custom_port = _field("")
    modal.checkbox_enabled = _field("x")
    modal.checkbox_show_ip = _field("")
    interaction = MagicMock()
    interaction.user = SimpleNamespace(id=4711, name="tester", __str__=lambda self: "tester")
    interaction.response.send_message = AsyncMock()
    interaction.followup.send = AsyncMock()
    asyncio.run(modal.callback(interaction))
    return saved


def test_protected_info_changed_meanwhile_survives(monkeypatch):
    saved = _submit(monkeypatch, CHANGED_MEANWHILE)

    assert saved, "premise: the modal saved something"
    assert saved["info"].protected_content == "new secret", (
        "the protected content changed while the modal was open was overwritten with "
        "the snapshot taken when it opened"
    )
    assert saved["info"].protected_password == "new-pass"


def test_unchanged_protected_info_is_kept(monkeypatch):
    """Counter-check: the plain modal must not drop protected info either."""
    saved = _submit(monkeypatch, WHEN_OPENED)

    assert saved["info"].protected_content == "old secret"
    assert saved["info"].custom_text == "new text", "premise: the edited text is saved"
