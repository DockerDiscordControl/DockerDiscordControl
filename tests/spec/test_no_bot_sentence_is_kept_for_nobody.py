# -*- coding: utf-8 -*-
"""A bot sentence in the catalogue is used somewhere, or it goes.

THE FINDING (2026-09-27): test_no_catalogue_key_is_read_by_nobody.py checks
the dotted keys only; the bot's other style, where the English sentence IS
the key, had no such check. 240 of those sentences were used by nothing any
more - old help texts, the old mech tier names, messages of commands that no
longer exist - each one a line in 40 catalogues that was still being
translated and reviewed. They were removed; this keeps them from piling up.

WHAT COUNTS AS USED: the sentence appears in any source or data file of the
repo (code, JSON data, templates, scripts). Single words are left out: those
are also built at runtime, e.g. _(action.capitalize()) or _(task.cycle.title()),
which no text search can see.

COUNTER-CHECK (2026-09-27): red before the removal - 240 sentences; putting
one back ("Year must be between 2025 and 2030.") turns it red again.
"""

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKIP_DIRS = {".git", "locales", "tests", "docs", "node_modules", "config", "logs",
             "cached_animations", "cached_displays", "__pycache__"}
SUFFIXES = {".py", ".json", ".js", ".html", ".txt", ".yml", ".yaml", ".md", ".cfg", ".ini"}


def _source_text():
    """All source text, plus every Python string constant as the parser joins it:
    a sentence written as adjacent pieces over several lines ("...detected**\\n\\n"
    "Unable to...") is one constant there and nowhere one piece of text."""
    chunks = []
    for path in ROOT.rglob("*"):
        rel = path.relative_to(ROOT).parts
        if not path.is_file() or rel[0] in SKIP_DIRS or path.suffix not in SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        chunks.append(text)
        if path.suffix == ".py":
            try:
                chunks += [n.value for n in ast.walk(ast.parse(text))
                           if isinstance(n, ast.Constant) and isinstance(n.value, str)]
            except SyntaxError:
                pass
    return "\n".join(chunks)


def test_every_bot_sentence_is_used():
    english = json.loads((ROOT / "locales" / "en.json").read_text(encoding="utf-8"))
    text = _source_text()
    unused = []
    for key in english:
        if key.startswith(("web.", "js.", "aas.")) or " " not in key.strip():
            continue
        escaped = key.encode("unicode_escape").decode("ascii")
        if key not in text and escaped not in text:
            unused.append(key)
    assert not unused, f"{len(unused)} sentences nothing uses:\n" + "\n".join(u[:90] for u in unused[:20])
