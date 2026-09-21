# -*- coding: utf-8 -*-
"""A message shown to a user must go through ``_()``, or 40 languages are a lie.

THE FINDING (review E34): DDC ships forty locale files and a test,
``test_bot_strings_exist_in_the_catalog``, that checks every string passed to
``_()`` has a key in them. That test cannot see the failure that actually
happens, which is a message never passed to ``_()`` at all:

    await interaction.response.send_message(
        "❌ Error processing donation request. Please try again later.",
        ephemeral=True)

Measured when this was written: **42 such messages**, 39 of them in
``cogs/control_ui.py``. A German, French or Japanese operator gets those in
English, and nothing anywhere says so - the guard that exists asks the
opposite question.

A RATCHET, NOT A BAN IN ONE STEP, following the pattern
``test_codebase_is_english`` already sets: ``KNOWN`` lists how many plain
literals each file still sends. The contract fails when a file has MORE - and
when it has FEWER, so the list can only shrink and never lies. Translating
forty-two messages into forty languages is 1,680 entries; doing it in one
commit would be a worse change than the defect.

THE LIMIT OF THE DETECTOR, stated plainly: it looks for a bare string literal
passed as the first argument (or as ``content=``) to ``send_message``,
``send``, ``respond`` or ``edit_original_response``, and only counts text
longer than fifteen characters containing a space - so ``"​"`` or ``"ok"`` do
not register. An f-string that interpolates a translated part is not caught,
and neither is a message built in a variable first. It finds the shape that
actually occurs.
"""

import ast
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[2]
SENDERS = {"send_message", "send", "respond", "edit_original_response", "edit_message"}

# Plain literals still sent per file. ONLY EVER SHRINKS.
#
# It reached zero on 2026-09-21, in the same change that added the ratchet: of
# the 42 messages, 14 that the user cannot act on differently became the
# generic answer that was already translated (the same rule as reviews E14 and
# E24, and four of them gained the log line they never had), and 14 distinct
# messages got their own key in all forty catalogues.
#
# The dict stays, and so does the ratchet. Zero is a number that can grow.
KNOWN: dict = {}


def _plain_literals(path: Path):
    """Messages this file sends to Discord without going through _()."""
    found = []
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "attr", None) not in SENDERS:
            continue
        candidates = list(node.args[:1])
        candidates += [kw.value for kw in node.keywords if kw.arg == "content"]
        for arg in candidates:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                text = arg.value.strip()
                if len(text) > 15 and " " in text:
                    found.append((node.lineno, text))
    return found


def _all_counts():
    counts = {}
    for path in sorted(PROJECT.glob("cogs/**/*.py")):
        hits = _plain_literals(path)
        if hits:
            counts[str(path.relative_to(PROJECT))] = len(hits)
    return counts


def test_no_file_sends_more_untranslated_messages_than_it_did():
    counts = _all_counts()

    grown = {f: (n, KNOWN.get(f, 0)) for f, n in counts.items() if n > KNOWN.get(f, 0)}

    assert not grown, (
        "these files now send MORE messages that never reach the locale "
        "catalogue - wrap them in _() and add the key to locales/*.json:\n  " +
        "\n  ".join(f"{f}: {now} (was {was})" for f, (now, was) in grown.items())
    )


def test_the_list_does_not_lie():
    """A file that improved must say so, or the number stops meaning anything."""
    counts = _all_counts()

    shrunk = {f: (counts.get(f, 0), n) for f, n in KNOWN.items() if counts.get(f, 0) < n}

    assert not shrunk, (
        "these files send FEWER untranslated messages than KNOWN claims - good "
        "news, but lower the numbers so the list keeps telling the truth:\n  " +
        "\n  ".join(f"{f}: {now} (listed {was})" for f, (now, was) in shrunk.items())
    )


def test_a_file_outside_the_list_sends_none():
    counts = _all_counts()
    unexpected = {f: n for f, n in counts.items() if f not in KNOWN}

    assert not unexpected, (
        f"untranslated messages in a file the list does not cover: {unexpected}"
    )


def test_the_detector_still_sees_a_planted_one(tmp_path):
    """Guard against a blunt tool, now that the repo itself is clean.

    While KNOWN was non-empty, "it still finds something" was guard enough.
    At zero that check would pass just as happily on a detector that had gone
    blind, so it is given something to find.
    """
    planted = tmp_path / "planted.py"
    planted.write_text(
        "async def handler(interaction):\n"
        "    await interaction.response.send_message('This never reaches the catalogue.')\n",
        encoding="utf-8")

    assert _plain_literals(planted), (
        "the detector no longer notices a plain literal sent to Discord; the "
        "empty KNOWN above would then mean nothing at all"
    )


def test_the_detector_ignores_a_translated_one(tmp_path):
    """The other direction: _() must not be reported as a violation."""
    clean = tmp_path / "clean.py"
    clean.write_text(
        "async def handler(interaction):\n"
        "    await interaction.response.send_message(_('This one goes through the catalogue.'))\n",
        encoding="utf-8")

    assert not _plain_literals(clean), (
        "a properly translated message was reported as untranslated"
    )
