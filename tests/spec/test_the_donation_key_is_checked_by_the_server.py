# -*- coding: utf-8 -*-
""""Validate key" in the advanced settings asks the server, by the list the save uses.

THE FINDING (operator's question, 2026-10-05: "does this work 100 %?"): the
button checked a copy of the key list kept in advanced_settings_modal.js. It
held five of the server's six keys (utils/key_crypto.py): the Abyss special
edition key was called "invalid, buy a licence" by the button and accepted by
the save. The copy also printed the valid keys to the browser console, from a
file the server hands out without a login.

THE CONTRACT: POST /api/donation-key/check answers by validate_donation_key,
for every key the save accepts; no file the browser loads carries the key
list; the button shows what the route says (tests/js/donation_key_check.test.js).

HOW THIS TEST CAN FAIL: a key the save accepts and the check refuses, a key
list back in the static files, or a button that decides on its own.

COUNTER-CHECK (2026-10-05): red before the change (no route, the encrypted
list in advanced_settings_modal.js, the node cases fail on the local check).
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from tests.spec.panel_client import basic_auth, panel  # noqa: F401 - fixture
from utils.key_crypto import ENCRYPTED_DONATION_KEYS, get_valid_donation_keys

ROOT = Path(__file__).resolve().parents[2]


def _check(panel, key, auth=True):  # noqa: F811
    return panel.test_client().post("/api/donation-key/check", json={"key": key},
                                    headers=basic_auth() if auth else {})


def test_every_key_the_save_accepts_is_valid(panel):  # noqa: F811
    for key in get_valid_donation_keys():
        for spelling in (key, key.lower(), f"  {key} "):
            answer = _check(panel, spelling)
            assert answer.status_code == 200 and answer.get_json() == {"success": True, "valid": True}, \
                (key[:8], answer.get_json())


def test_a_wrong_or_missing_key(panel):  # noqa: F811
    assert _check(panel, "DDC-EXAMPLE-XXXX-XXXX-XXXX-XXXX-2025").get_json() == {"success": True, "valid": False}
    assert _check(panel, "  ").status_code == 400


def test_only_after_a_login(panel):  # noqa: F811
    assert _check(panel, get_valid_donation_keys()[0], auth=False).status_code == 401


def test_no_file_the_browser_loads_carries_the_keys():
    plain = [k.upper() for k in get_valid_donation_keys()]
    for path in list((ROOT / "app" / "static").rglob("*.js")) + list((ROOT / "app" / "templates").rglob("*.html")):
        text = path.read_text(encoding="utf-8", errors="replace")
        assert not any(e in text for e in ENCRYPTED_DONATION_KEYS), f"{path.name} carries the key list"
        assert not any(k in text.upper() for k in plain), f"{path.name} carries a key"


def test_the_button_says_what_the_server_says():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed here - run tests/js/donation_key_check.test.js by hand")
    result = subprocess.run([node, str(ROOT / "tests" / "js" / "donation_key_check.test.js")],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
