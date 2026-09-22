# -*- coding: utf-8 -*-
"""The first-time setup page shows its messages as text, not as markup.

CodeQL #57 (js/xss-through-dom): `showAlert` built the alert with

    alert.innerHTML = `${message}<button ...>`;

and some of its messages come from the server (`result.error`) or from the
browser (`error.message`). Whatever they contain was parsed as HTML. The page
is reachable before any password exists, so it is the last place to parse
foreign text as markup.

The fix inserts the message with `textContent`. That has a consequence the
second test guards: a translated text written into a JavaScript string as
`'{{ _t(...) }}'` is HTML-escaped by Jinja (an apostrophe becomes `&#39;`).
innerHTML used to decode that again; textContent shows it literally. So every
translated text handed to showAlert must come through `|tojson`, which yields
a proper JavaScript string.
"""

import re
from pathlib import Path

SETUP = Path(__file__).resolve().parents[2] / "app" / "templates" / "setup.html"


def _source():
    return SETUP.read_text(encoding="utf-8")


def _show_alert_body(source):
    start = source.index("function showAlert(")
    depth, i = 0, source.index("{", start)
    for j in range(i, len(source)):
        if source[j] == "{":
            depth += 1
        elif source[j] == "}":
            depth -= 1
            if depth == 0:
                return source[i:j + 1]
    raise AssertionError("showAlert has no closing brace")


def test_the_message_is_not_parsed_as_html():
    body = _show_alert_body(_source())

    assert "innerHTML" not in body, body
    assert "insertAdjacentHTML" not in body, body
    assert re.search(r"\.textContent\s*=\s*message|createTextNode\(\s*message", body), body


def test_translated_messages_reach_showalert_as_javascript_strings():
    calls = [line.strip() for line in _source().splitlines()
             if "showAlert(" in line and "function showAlert" not in line]
    assert calls, "no showAlert calls found - the test would prove nothing"

    for call in calls:
        for translated in re.findall(r"\{\{[^}]*_t\([^}]*\}\}", call):
            assert "|tojson" in translated, (
                f"{call}\n  {translated} is HTML-escaped by Jinja and would be shown "
                f"with its entities once the message is inserted as text"
            )
