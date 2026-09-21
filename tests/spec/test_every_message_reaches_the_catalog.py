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

**THIS TEST HAS BEEN WIDENED TWICE AFTER REPORTING ZERO, both times because a
hand-read found what it could not see.** First it watched only
``send_message(...)`` and missed 33 texts inside embeds (review E35). Then it
watched embeds only as CONSTRUCTOR ARGUMENTS and missed five more written as
``embed.description = "..."`` (review E38). Each time the number it printed
was zero and each time that was false.

That is worth leaving in the docstring rather than tidying away: a guard is
only ever as wide as the shapes somebody thought of, and the way the missing
shapes were found both times was reading the code by hand. Most of what DDC shows is an
embed - the title, the description, the footer, the fields - so a guard that
only watched ``send_message(...)`` gave exactly the false comfort this whole
programme exists to remove. It was found by reading
``cogs/control_ui.py`` by hand two hours after the guard was written.

THE LIMIT OF THE DETECTOR, stated plainly: it looks for a bare string literal
passed as the first argument (or as ``content=``) to ``send_message``,
``send``, ``respond``, ``edit_original_response`` or ``edit_message``, and for
``title=``, ``description=``, ``text=``, ``name=`` and ``value=`` on
``discord.Embed(...)``, ``set_footer(...)`` and ``add_field(...)``. It counts
text longer than fifteen characters containing a space and at least one
letter, so ``"​"`` or ``"ok"`` do not register. An f-string is examined for its
literal PARTS, because that is how several of these are written - and a
fragment is exactly what must not be translated on its own, which is why they
are listed rather than wrapped.

A message built in a variable first is still not caught. It finds the shapes
that actually occur.
"""

import ast
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[2]
SENDERS = {"send_message", "send", "respond", "edit_original_response", "edit_message"}
EMBED_BUILDERS = {"Embed", "set_footer", "add_field"}
EMBED_TEXT_ARGS = {"title", "description", "text", "name", "value"}

# Deliberately corrupted text, and therefore deliberately NOT language. The
# mech story shows a damaged transmission at level 11; translating
# "L3v#l 1*!$ x0r" would be translating the glitch. Listed rather than detected,
# because a heuristic for "is this broken on purpose" would be worse than the
# problem.
DELIBERATE_GLITCH = {
    "L3v#l 1*!$ x0r: ████████",
    "*[DATA_CORRUPTED] - 000x34A##%&33DL*\n*[UNAUTHORIZED_ACCESS_DETECTED]*\n*[EVOLUTION_DATA_ENCRYPTED]*",
    "💀 Epilogue: W#!sp*r of th3 [ERROR_CODE_11]",
}

# Plain literals still sent per file. ONLY EVER SHRINKS.
#
# The ``send_message(...)`` half reached zero on 2026-09-21 (review E34): of 42
# messages, 14 that the user cannot act on differently became the generic
# answer that was already translated - the rule reviews E14 and E24 set, and
# four of them gained the log line they never had - and 14 distinct messages
# got their own key in all forty catalogues.
#
# THESE 33 ARE THE EMBEDS, which the first version of this test could not see
# (review E35). They are not one job: some are whole sentences, some are
# f-string FRAGMENTS that must be turned into one key with a placeholder
# rather than translated piece by piece, and three are deliberate glitch text
# listed in DELIBERATE_GLITCH above. So they come down in batches, and the
# number here comes down with them.
KNOWN = {
}


def _literal_parts(node):
    """The plain text this expression carries, including f-string parts."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.JoinedStr):
        return [v.value for v in node.values
                if isinstance(v, ast.Constant) and isinstance(v.value, str)]
    return []


def _reads_as_a_message(text: str) -> bool:
    stripped = text.strip()
    return (len(stripped) > 15 and " " in stripped
            and any(c.isalpha() for c in stripped)
            and stripped not in DELIBERATE_GLITCH)


def _plain_literals(path: Path):
    """Text this file shows a user without going through _()."""
    found = []
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        candidates = []
        if getattr(node.func, "attr", None) in SENDERS:
            candidates += list(node.args[:1])
            candidates += [kw.value for kw in node.keywords if kw.arg == "content"]
        if (getattr(node.func, "attr", None) in EMBED_BUILDERS
                or getattr(node.func, "id", None) == "Embed"):
            candidates += [kw.value for kw in node.keywords
                           if kw.arg in EMBED_TEXT_ARGS]

        for arg in candidates:
            for text in _literal_parts(arg):
                if _reads_as_a_message(text):
                    found.append((node.lineno, text.strip()))

    # `embed.description = "..."` is the same thing said differently, and the
    # second version of this test could not see it (review E38).
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Attribute):
                continue
            if target.attr not in EMBED_TEXT_ARGS:
                continue
            for text in _literal_parts(node.value):
                if _reads_as_a_message(text):
                    found.append((node.lineno, text.strip()))
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
