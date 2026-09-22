# -*- coding: utf-8 -*-
"""The game-controller emoji appears nowhere in the product.

Operator rule: never the controller emoji in UI, docs or release notes. It
still stood in README.md (five times), docs/CHANGELOG.md, docs/UNRAID.md, and
in three code comments - and those three described a UI that does not show it:
``cogs/control_ui.py`` promised the player line reads "Players: <emoji> x/y",
while ``format_player_line`` returns "Players: x/y", and two comments named an
"<emoji> column" in the web panel whose header is plain text. A comment that
claims more than the code is worse than none.

The emoji is written as an escape here so this file does not match itself.

COUNTER-CHECK (2026-09-22): red with 13 occurrences in 7 files before the
cleanup, green after.
"""

from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
CONTROLLER = "\U0001F3AE"

# Allow-list of what users read or what renders: docs, templates, UI strings, code.
SUFFIXES = {".md", ".html", ".htm", ".xml", ".yml", ".yaml", ".txt", ".py", ".sh", ".json", ".js", ".css"}
NOT_SHIPPED = {".git", "tests", "config", "logs", "node_modules", "__pycache__", ".pytest_cache"}


def _files():
    for path in PROJECT.rglob("*"):
        relative = path.relative_to(PROJECT)
        if relative.parts[0] in NOT_SHIPPED or relative.parts[0].startswith("cached_"):
            continue
        if path.suffix.lower() in SUFFIXES and path.is_file():
            yield relative, path.read_text(encoding="utf-8", errors="replace")


def test_the_scan_reads_the_readme_and_the_catalogs():
    """Guard against a blunt tool: a scan that reads nothing finds nothing."""
    names = {str(name) for name, _ in _files()}
    assert "README.md" in names and any(n.endswith(".json") for n in names), len(names)


def test_no_file_contains_the_controller_emoji():
    findings = [
        f"{name}:{lineno}"
        for name, text in _files()
        for lineno, line in enumerate(text.splitlines(), 1)
        if CONTROLLER in line
    ]
    assert not findings, f"{len(findings)} occurrences:\n" + "\n".join(findings)
