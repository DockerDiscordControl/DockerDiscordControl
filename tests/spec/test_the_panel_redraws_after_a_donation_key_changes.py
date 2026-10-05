# -*- coding: utf-8 -*-
"""After a save that switches the donations on or off by key, the panel is drawn again.

THE FINDING (operator's question, 2026-10-05): saving a valid donation key
switched the donations off at once in Discord, while the web panel kept
showing the donation and mech cards (config.html draws them by
donations_disabled) until the operator reloaded the page by hand.

THE CONTRACT: the save answers with donations_disabled as it now stands; the
page knows the state it was drawn with (DDC_DONATIONS_DISABLED); panel.js
reloads when the two differ, and only then.

HOW THIS TEST CAN FAIL: the answer without the state, the page without its
own, or a reload that does not compare them.

COUNTER-CHECK (2026-10-05): red before the change on all three.
"""

import re
from pathlib import Path

from tests.spec.panel_client import basic_auth, panel  # noqa: F401 - fixture

ROOT = Path(__file__).resolve().parents[2]


def test_the_save_answers_with_the_state(panel, monkeypatch):  # noqa: F811
    for state in (True, False):
        monkeypatch.setattr("services.donation.donation_utils.is_donations_disabled", lambda: state)
        answer = panel.test_client().post(
            "/save_config_api", data={"language": "en"},
            headers={**basic_auth(), "X-Requested-With": "XMLHttpRequest"}).get_json()
        assert answer["success"] is True, answer
        assert answer["donations_disabled"] is state


def test_the_page_knows_its_own_state():
    scripts = (ROOT / "app" / "templates" / "_scripts.html").read_text(encoding="utf-8")
    assert "window.DDC_DONATIONS_DISABLED = {{ (donations_disabled is defined and donations_disabled)|tojson }}" \
        in scripts


def test_the_reload_compares_the_two():
    panel_js = (ROOT / "app" / "static" / "js" / "panel.js").read_text(encoding="utf-8")
    assert re.search(r"data\.donations_disabled !== window\.DDC_DONATIONS_DISABLED\)\s*\{\s*"
                     r"setTimeout\(\(\) => window\.location\.reload\(\)", panel_js), \
        "panel.js does not reload when the donation state changed"
