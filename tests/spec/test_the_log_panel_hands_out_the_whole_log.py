# -*- coding: utf-8 -*-
"""The live-log panel's 📥 sends the last 5000 log lines as a file, to the presser only.

NEW (operator, 2026-10-05: "mach das perfekt" on the proposal of a file
button): the panel shows what fits into one embed, at most 4000 characters.
To read further back, search, or pass a log on, 📥 sends the last
DOWNLOAD_LINES lines as ``<container>-<time>.log``: Docker's full stamps kept,
colour codes removed, at most DOWNLOAD_BYTES, cut at a line.

THE CONTRACT: a private message with the file (never the channel), the panel
itself untouched, Docker's problem said in words when there is no log, and
the spam brake in front.

HOW THIS TEST CAN FAIL: a public file, a file with colour codes or cut inside
a line, an edited panel, or a press that the brake did not hold back.

COUNTER-CHECK (2026-10-05): red with the button's callback emptied (no file
sent) and with the ANSI strip removed.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import cogs.status_info_integration as sii

SPAM = "services.infrastructure.spam_protection_service.get_spam_protection_service"
RAW = "".join(f"2026-10-05T08:00:{i % 60:02d}.000000001Z \x1b[33mline {i}\x1b[0m\n" for i in range(300))


def _press():
    interaction = MagicMock()
    interaction.user.id = 5
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.followup.send = AsyncMock()
    interaction.edit_original_response = AsyncMock()
    return interaction


def _no_brake():
    return patch(SPAM, return_value=SimpleNamespace(is_enabled=lambda: False))


@pytest.mark.asyncio
async def test_the_file_goes_to_the_presser_only(monkeypatch):
    monkeypatch.setattr(sii, "read_container_logs", AsyncMock(return_value=(RAW, None)))
    view = sii.LiveLogView("valheim", display_name="Valheim Server")
    view.message_ref = SimpleNamespace(edit=AsyncMock(), id=1)
    press = _press()
    with _no_brake():
        await view.download_log(press)

    sent = press.followup.send.await_args
    assert sent.kwargs.get("ephemeral") is True, "the log file went to the whole channel"
    file = sent.kwargs["file"]
    assert file.filename.startswith("valheim-") and file.filename.endswith(".log")
    content = file.fp.read().decode()
    assert "\x1b[" not in content, "colour codes reached the file"
    assert content.splitlines()[0] == "2026-10-05T08:00:00.000000001Z line 0"
    assert content.endswith("line 299\n")
    assert "300" in sent.args[0] and "Valheim Server" in sent.args[0]
    view.message_ref.edit.assert_not_awaited()
    press.edit_original_response.assert_not_awaited()
    assert press.response.defer.await_args.kwargs.get("ephemeral") is None, (
        "answered with a new 'thinking' message: the press's token cannot delete the panel")
    assert view._painter is press


@pytest.mark.asyncio
async def test_a_big_log_is_cut_at_a_line(monkeypatch):
    monkeypatch.setattr(sii, "DOWNLOAD_BYTES", 1000)
    monkeypatch.setattr(sii, "read_container_logs", AsyncMock(return_value=(RAW, None)))

    file, lines = await sii.container_log_file("valheim")

    content = file.fp.read().decode()
    assert len(content.encode()) <= 1000
    assert content.startswith("2026-10-05T08:"), f"cut inside a line: {content[:40]!r}"
    assert content.endswith("line 299\n") and lines == content.count("\n")


@pytest.mark.asyncio
async def test_no_log_is_said_in_words(monkeypatch):
    monkeypatch.setattr(sii, "read_container_logs",
                        AsyncMock(return_value=(None, "Container 'valheim' not found.")))
    view = sii.LiveLogView("valheim")
    press = _press()
    with _no_brake():
        await view.download_log(press)

    sent = press.followup.send.await_args
    assert "not found" in sent.args[0] and "file" not in sent.kwargs
    assert sent.kwargs.get("ephemeral") is True


@pytest.mark.asyncio
async def test_the_brake_comes_first(monkeypatch):
    reader = AsyncMock(return_value=(RAW, None))
    monkeypatch.setattr(sii, "read_container_logs", reader)
    view = sii.LiveLogView("valheim")
    press = _press()
    with patch.object(sii.LiveLogView, "_braked", AsyncMock(return_value=True)):
        await view.download_log(press)

    reader.assert_not_awaited()
    press.followup.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_the_panel_carries_the_button():
    view = sii.LiveLogView("valheim")

    assert [str(item.emoji) for item in view.children if getattr(item, "emoji", None)][:3] == \
        ["🔄", "▶️", "📥"]
