# -*- coding: utf-8 -*-
"""The repository is English - code, comments, docstrings, tests and docs.

DDC is international open-source software (operator decision, 2026-09-19).
German text had crept in: comments and docstrings, hard-wired German texts
shown to users, German catalog source strings, the tests/spec suite and the
quality-programme documents.

A RATCHET, NOT A BAN IN ONE STEP: the translation runs area by area, one
change per area. Until it is done, ``STILL_GERMAN`` lists the German lines per
file. The contract fails when a file gets MORE German lines than listed - and
when a file has FEWER, so the list can only shrink and never lies.

WHAT IS SCANNED: every text file below ``ROOTS`` plus ``ROOT_FILES``. Excluded
are language DATA (``locales/``, the shipped German story in
``services/mech/defaults/``) and three private documents that are not part of
the repository at all - each exclusion is checked against ``.gitignore``, so an
exclusion can never silently hide a published file.

LANGUAGE DATA inside code (e.g. the German text a test expects from
de.json) is exempt line by line with an explicit trailing ``# language data``
marker. The marker only counts on a line that holds a string literal - it
cannot silence German prose in a comment.

THE LIMIT OF THE DETECTOR, stated plainly: it is a heuristic. A line counts
as German when it holds at least two words from a German signal vocabulary
(ALL-CAPS words such as "MIT" or "API" do not count), or one such word plus an
umlaut. A German line made only of rarer words slips through. Measured on the
English documentation and on the English code of ``main``, it raised no false
alarm apart from "MIT License" - which is why all-caps words are ignored.
"""

import re
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[2]
ROOTS = ("app", "cogs", "services", "utils", "scripts", "tools", "tests", "docs", ".github")
ROOT_FILES = ("README.md", "SPEC.md", "AUDIT.md", "Dockerfile", "docker-compose.yml",
              "bot.py", "run.py", "wsgi.py")
SUFFIXES = {".py", ".sh", ".js", ".html", ".css", ".yml", ".yaml", ".toml", ".ini", ".cfg",
            ".md", ".txt"}
DATA_PREFIXES = ("locales/", "services/mech/defaults/")
# Private documents, gitignored - checked below against .gitignore.
PRIVATE = ("AUDIT_2026-09.md", "ROADMAP_2026-09_perf_mech.md", "docs/DMC_PROJECT_PLAN.md")
# This file itself: its German lines are the detector's test examples.
SELF = "tests/spec/test_codebase_is_english.py"

SIGNAL = frozenset("""
der das und nicht ist wird wurde werden ein eine einen einem einer eines auch nur
noch schon weil wenn dass ueber fuer über für mit von zum zur bei nach vor aus hier
dort jetzt heute vorher bisher sonst bleibt steht liegt gibt keine kein keinen ohne
diese dieser dieses jede jeder jedes wie wo warum soll muss kann darf sind waren
hatte haben oder aber denn damit dabei seit sich wir ihr gegen unter zwischen weiter
selbst beim vom ins im dem siehe gemessen entschieden befund befunde waechter wächter
abgrenzung datei dateien verzeichnis knopf knoepfe knöpfe dienst vorgabe vorgaben
regler betreiber zusicherung eigene eigenen eigener eigenes nie immer genau ohnehin
also zuerst danach dann erst sehr ganz alle alles etwas nichts heisst heißt zeigt
gilt fehlt fehlen stand lag lagen worden sollte muesste müsste waere wäre haette
hätte koennte könnte
""".split())
UMLAUT = re.compile(r"[äöüÄÖÜß]")
WORD = re.compile(r"[A-Za-zäöüÄÖÜß]+")

# file -> number of German lines still in it. ONLY EVER SHRINK THIS.
STILL_GERMAN = {
    "AUDIT.md": 75,
    "SPEC.md": 326,
    "docs/archive/proposals/FEATURE_IDEA_WARNING_SYSTEM.md": 10,
    "docs/archive/proposals/FEATURE_PLAN_AUTO_ACTIONS.md": 49,
    "docs/archive/proposals/HOT_RELOAD_PLAN.md": 26,
    "docs/quality/STAGE0_INVENTORY.md": 396,
    "docs/quality/STAGE3_TESTS_THAT_CANNOT_FAIL.md": 195,
    "docs/quality/STAGE4_REVIEW.md": 164,
}


DATA_MARKER = "# language data"
_STRING = re.compile(r"""(['"]).*\1""")


def is_exempt(line: str) -> bool:
    """A string literal marked as language data - never a comment."""
    code, sep, _rest = line.partition(DATA_MARKER)
    return bool(sep) and bool(_STRING.search(code)) and not code.lstrip().startswith("#")


def is_german(line: str) -> bool:
    words = [w.lower() for w in WORD.findall(line) if not w.isupper()]
    hits = sum(1 for w in words if w in SIGNAL)
    return hits >= 2 or (bool(UMLAUT.search(line)) and hits >= 1)


def _files():
    candidates = [PROJECT / name for name in ROOT_FILES]
    for root in ROOTS:
        candidates.extend(p for p in (PROJECT / root).rglob("*") if p.is_file())
    for path in sorted(set(candidates)):
        if not path.is_file():
            continue
        rel = path.relative_to(PROJECT).as_posix()
        if rel.startswith(DATA_PREFIXES) or rel in PRIVATE or rel == SELF or "__pycache__" in rel:
            continue
        if path.suffix not in SUFFIXES and path.name != "Dockerfile":
            continue
        yield rel, path


def german_lines() -> dict:
    found = {}
    for rel, path in _files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        count = sum(1 for line in text.splitlines() if is_german(line) and not is_exempt(line))
        if count:
            found[rel] = count
    return found


@pytest.mark.parametrize("line", [
    "# Nicht self.custom_id (read_story_<stufe>) - siehe EpilogueButton.",
    "Der Knopf fragt den Dienst nicht.",
    '"""Cache für statische Container-Daten die sich nie ändern."""',
    'title = "🚨 Container-Überwachung nicht verfügbar"',
])
def test_the_detector_finds_german(line):
    """Guard against a blunt tool - one example per kind of hit."""
    assert is_german(line), line


@pytest.mark.parametrize("line", [
    "# The button asks the service for its cooldown before deferring.",
    "Live player counts are powered by opengsq (MIT License).",
    "die_roll = random.randint(1, 6)  # was the hat on the man?",
    'return get_config_dir() / "mech" / relative',
])
def test_the_detector_does_not_flag_english(line):
    assert not is_german(line), line


def test_the_data_marker_only_exempts_string_literals():
    assert is_exempt('    "de": "Nicht verfügbar",  # language data')
    assert not is_exempt("    # Der Knopf ist nicht da  # language data")
    assert not is_exempt("x = 1  # Der Knopf ist nicht da - language data")


def test_private_exclusions_are_really_gitignored():
    """An exclusion must never hide a published file."""
    ignore = (PROJECT / ".gitignore").read_text(encoding="utf-8").splitlines()
    for name in PRIVATE:
        assert name in ignore, f"{name} is excluded from the scan but not listed in .gitignore"


def test_no_new_german_and_the_list_does_not_lie():
    found = german_lines()
    new = {k: v for k, v in found.items() if v > STILL_GERMAN.get(k, 0)}
    done = {k: (v, found.get(k, 0)) for k, v in STILL_GERMAN.items() if found.get(k, 0) < v}
    assert not new, f"German text added (write English - DDC is international): {new}"
    assert not done, f"Fewer German lines than STILL_GERMAN says - shrink the list (listed, found): {done}"
