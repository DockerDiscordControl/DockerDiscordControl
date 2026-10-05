# -*- coding: utf-8 -*-
"""The live-log switch in the web panel names the button that opens the logs.

THE FINDING (2026-10-05): under "Enable Live Logs" the panel said "Enable
/logs command in Discord", in all 40 languages. DDC has no /logs command; the
logs open with the 📋 button in a container's info panel in a control channel.

THE CONTRACT: in every language the hint names the 📋 button and no /logs.

HOW THIS TEST CAN FAIL: a language that still speaks of a /logs command.

COUNTER-CHECK (2026-10-05): red in all 40 languages before the change.
"""

import json
from pathlib import Path

LOCALES = Path(__file__).resolve().parents[2] / "locales"
KEY = "web.advanced.enable_live_logs_hint"


def test_every_language_names_the_button():
    wrong = {}
    for path in sorted(LOCALES.glob("*.json")):
        if path.stem == "meta":
            continue
        text = json.loads(path.read_text(encoding="utf-8")).get(KEY, "")
        if "📋" not in text or "/logs" in text:
            wrong[path.stem] = text
    assert not wrong, f"the hint does not name the 📋 button: {wrong}"
