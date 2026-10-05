# -*- coding: utf-8 -*-
"""The live-log panel shows as much of the log as Discord allows, in readable lines.

THE FINDING (2026-10-05): the panel showed the last 1800 characters of what
Docker returned. Of a typical 60-character line, 31 were Docker's stamp
(``2026-10-05T08:31:23.123456789Z``), colour codes came through as ``[32m``,
the cut fell inside a line, and a ``` in a line closed the code block. With
"Log lines to fetch" at 200, about 20 were visible.

THE CONTRACT: up to 4000 characters (Discord allows 4096 in a description);
whole lines only, newest at the bottom, "…" on top when older ones were left
out; the time as HH:MM:SS in the panel's time zone, with a date line where
the date changes or is not today; no colour codes; no ``` inside the block.

HOW THIS TEST CAN FAIL: any of the above, including at the call site:
container_logs_text must hand Docker's text through these helpers.

COUNTER-CHECK (2026-10-05): the call-site case red with the old cut put back
(1803 characters, raw stamps); the helper cases did not exist before.
"""

from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

import cogs.status_info_integration as sii

BERLIN = ZoneInfo("Europe/Berlin")


def _docker(lines, day="2026-10-05"):
    return "\n".join(f"{day}T{8 + i // 3600:02d}:{(i // 60) % 60:02d}:{i % 60:02d}.123456789Z {text}"
                     for i, text in enumerate(lines)) + "\n"


def test_a_line_reads_like_a_line():
    raw = "2026-10-05T08:31:23.123456789Z \x1b[32mINFO\x1b[0m started ```x```\n"

    (day, text), = sii.readable_log_lines(raw, BERLIN)

    assert text == "10:31:23 INFO started `​``x`​``"
    assert day == date(2026, 10, 5)


def test_whole_newest_lines_up_to_the_room():
    lines = sii.readable_log_lines(_docker([f"line {i:03d} " + "x" * 50 for i in range(200)]), BERLIN)

    text = sii.fit_log_lines(lines, today=date(2026, 10, 5))

    assert len(text) <= sii.LOG_ROOM
    assert len(text) > 3 * 1800 // 2, f"only {len(text)} characters used of {sii.LOG_ROOM}"
    shown = text.split("\n")
    assert shown[0] == "…", "older lines were left out without saying so"
    assert shown[-1].endswith("line 199 " + "x" * 50), "the newest line is not at the bottom"
    assert all(len(line) in (1, 68) for line in shown), "a line was cut inside"


def test_a_date_line_where_the_date_is_not_today_or_changes():
    raw = (_docker(["late"], day="2026-10-04").replace("T08:00:00", "T21:59:00")
           + _docker(["early"], day="2026-10-05"))

    text = sii.fit_log_lines(sii.readable_log_lines(raw, BERLIN), today=date(2026, 10, 5))

    assert text.split("\n") == ["── 2026-10-04 ──", "23:59:00 late",
                                "── 2026-10-05 ──", "10:00:00 early"]


@pytest.mark.asyncio
async def test_the_panel_text_goes_through_the_helpers(monkeypatch):
    raw = _docker([f"line {i:03d} " + "x" * 50 for i in range(200)]).encode()
    container = SimpleNamespace(logs=lambda **kw: raw)
    client = SimpleNamespace(containers=SimpleNamespace(get=lambda name: container),
                             close=lambda: None)
    monkeypatch.setattr(sii, "_panel_zone", lambda: BERLIN)
    with patch("services.docker_service.client_factory.build_docker_client", return_value=client):
        text = await sii.container_logs_text("nginx")

    assert len(text) > 3000, f"the panel still gets only {len(text)} characters"
    assert "T08:" not in text and ".123456789Z" not in text, "Docker's raw stamps reach the panel"
