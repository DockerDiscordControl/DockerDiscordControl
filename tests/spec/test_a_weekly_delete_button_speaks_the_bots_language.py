# -*- coding: utf-8 -*-
"""A weekly task's delete button names its weekday in the bot's language.

THE FINDING (stage 4 review before v3.1.0, section 41 pass 4): the delete
buttons of weekly tasks took the weekday from a hard-coded German list
('Mo', 'Di', 'Mi', ...), so an English panel showed "W:Di 17h" for a
Tuesday task.

THE CONTRACT: the abbreviation comes from the catalog (keys "Mon" to
"Sun", in every locale); German keeps "Di".

HOW THIS TEST CAN FAIL: the German list comes back, or a locale lacks a day.

COUNTER-CHECK (2026-09-30): red before the change (":Di " in English).
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import cogs.translation_manager as translation_manager
from cogs.task_ui import ContainerTaskDeleteView
from services.scheduling.scheduled_task import ScheduledTask

TUESDAY = datetime(2026, 10, 6, 17, 0, tzinfo=timezone.utc).timestamp()
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _weekly_tuesday_task():
    task = ScheduledTask(container_name="x", action="stop", cycle="weekly", weekday=1,
                         hour=17, minute=0, timezone_str="UTC")
    task.next_run_ts = TUESDAY
    return task


@pytest.mark.asyncio
@pytest.mark.parametrize("language, day", [("en", "Tue"), ("de", "Di"), ("fr", "mar")])
async def test_the_label_uses_the_language(monkeypatch, language, day):
    monkeypatch.setattr(translation_manager.translation_manager, "get_current_language",
                        lambda: language)
    view = ContainerTaskDeleteView(None, [_weekly_tuesday_task()], "x")
    label = view.children[0].label
    assert f":{day} 17h" in label, label


def test_every_locale_has_every_day():
    root = Path(__file__).resolve().parents[2] / "locales"
    missing = [f"{path.name}: {day}" for path in sorted(root.glob("*.json")) if path.name != "meta.json"
               for day in DAYS if not json.loads(path.read_text(encoding="utf-8")).get(day)]
    assert missing == []
