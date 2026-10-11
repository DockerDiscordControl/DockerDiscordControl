# -*- coding: utf-8 -*-
"""The monthly donation appeal is calm: no emoji, the Mech explained, nothing urgent.

THE FINDING (operator, 2026-10-11): "very icon-heavy ... it should briefly
explain the system, but not like the community mech now, I think that is a
bit pushy". It read "The community Mech needs your help to keep evolving!"
over nine emoji, in green or warning orange.

THE CONTRACT: the appeal's texts carry no emoji, say that nothing in DDC
depends on the Mech, and are in every language's catalogue; the embed uses
one calm colour and the Mech in one line.

HOW THIS TEST CAN FAIL: the old wording or its emoji back.

COUNTER-CHECK (2026-10-11): red on the code before the change.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / "services" / "scheduling" / "donation_message_service.py").read_text(encoding="utf-8")
EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿]")


def _appeal_texts():
    start = SOURCE.index("message_title = _(")
    end = SOURCE.index("# Send message to all status channels")
    return re.findall(r'_\(\s*((?:"[^"]*"\s*)+)\)', SOURCE[start:end])


def test_no_emoji_and_the_mech_explained():
    texts = ["".join(re.findall(r'"([^"]*)"', t)) for t in _appeal_texts()]
    assert texts, "premise: the appeal texts are found"
    assert not [t for t in texts if EMOJI.search(t)], "the appeal carries emoji again"
    body = max(texts, key=len)
    assert "Nothing in DDC depends on it." in body
    assert "needs your help" not in SOURCE


def test_every_language_has_the_appeal():
    body = max(("".join(re.findall(r'"([^"]*)"', t)).encode().decode("unicode_escape")
                for t in _appeal_texts()), key=len)
    for path in sorted((ROOT / "locales").glob("*.json")):
        if path.stem == "meta":
            continue
        assert body in json.loads(path.read_text(encoding="utf-8")), f"{path.stem} lacks the appeal"


def test_one_calm_colour():
    assert "message_color = 0x5865F2" in SOURCE
    assert "0xFFA500" not in SOURCE and "0x00ff41" not in SOURCE
