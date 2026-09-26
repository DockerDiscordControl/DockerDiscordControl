# -*- coding: utf-8 -*-
"""The time in a Discord status footer follows the panel's timezone.

THE FINDING (audit 2026-09-26). The panel's timezone is `timezone` in the
config. The status embed's footer read a second key, `timezone_str`, and that
key was written by exactly one thing: a hidden field of the task form, which
sits inside the settings form and is rendered with the zone the page was
LOADED with. Switching Berlin to New York and saving stored timezone=New York
and timezone_str=Berlin - the save does not reload the page - so Discord kept
showing Berlin times until a later save made after a reload.

THE CONTRACT: the footer reads `timezone`, and the settings save no longer
stores the task form's `timezone_str` at all.

HOW THIS TEST CAN FAIL: the footer reads anything but the panel's timezone, or
the stale hidden value lands in the config again.

COUNTER-CHECK (2026-09-26): red before the fix - the save stored
timezone_str='Europe/Berlin' next to timezone='America/New_York', and the
footer's source read 'timezone_str'.
"""

import re
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[2]


class _Form(dict):
    def getlist(self, key):
        value = dict.get(self, key)
        if value is None:
            return []
        return value if isinstance(value, list) else [value]


def test_the_task_form_s_timezone_is_not_stored():
    from services.config.config_form_parser_service import ConfigFormParserService

    service = MagicMock()
    service.save_config.return_value = MagicMock(success=True, message="ok")
    form = _Form({"selected_servers": [], "timezone": "America/New_York",
                  # the hidden field of tasks/form.html, rendered at page load
                  "timezone_str": "Europe/Berlin"})

    updated, ok, _message = ConfigFormParserService.process_config_form(form, {}, service)

    assert ok
    assert updated.get("timezone") == "America/New_York"
    assert "timezone_str" not in updated, updated.get("timezone_str")


def test_the_footer_reads_the_panel_timezone():
    source = (ROOT / "cogs" / "status_handlers.py").read_text(encoding="utf-8")

    reads = re.findall(r"current_config\.get\('(timezone(?:_str)?)'", source)

    assert reads and set(reads) == {"timezone"}, reads
