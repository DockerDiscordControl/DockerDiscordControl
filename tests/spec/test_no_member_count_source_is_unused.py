# -*- coding: utf-8 -*-
"""Nothing hands out a member count that nobody asked for.

No ``@covers`` marker: a finding, not a guarantee.

THE FINDING (review C71, section 23 F5): ``MonthlyMemberCache._load_cache``
answers with the same hard-coded record -
``{"member_count": 50, "timestamp": "2025-09-12T13:56:30", "month_year":
"2025-09"}`` - for a missing file, an I/O error, a parse error and a data
error alike. ``get_cache_info()`` then reports that fabricated timestamp as
``last_updated``, so a corrupt cache is indistinguishable from a healthy one
that happens to hold 50 members, and the date makes it look measured.

It reaches nobody. The application takes its member count from
``services/member_count`` (see app/bot/startup_steps/member_count.py); this
module and its shipped ``monthly_member_cache.json`` are referenced only by
their own tests. Repairing the fallback would have been repairing something
nothing reads, while leaving a module in place that looks like the member
count's home - so both go.
"""

import ast
import re
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
SOURCE_DIRECTORIES = ("cogs", "services", "app", "utils")
GONE = ("MonthlyMemberCache", "get_monthly_member_cache")


def _names_used(source: str) -> set:
    """Names the code actually reads, from the syntax tree (see review C61:
    a text search counts a name in a comment as a use)."""
    used = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Attribute):
            used.add(node.attr)
        elif isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                used.add(alias.asname or alias.name.split(".")[0])
            if isinstance(node, ast.ImportFrom) and node.module:
                used.update(node.module.split("."))
    return used


def _python_files():
    for directory in SOURCE_DIRECTORIES:
        yield from (PROJECT / directory).rglob("*.py")


def test_the_module_is_gone():
    assert not (PROJECT / "services" / "mech" / "monthly_member_cache.py").exists()
    assert not (PROJECT / "services" / "mech" / "monthly_member_cache.json").exists(), (
        "the stale 2025-09 snapshot is still shipped"
    )


def test_nothing_reaches_for_it():
    mentions = []
    for path in _python_files():
        used = _names_used(path.read_text(encoding="utf-8"))
        for name in GONE:
            if name in used:
                mentions.append(f"{path.relative_to(PROJECT)} -> {name}")

    assert mentions == [], "\n".join(mentions)


def test_the_real_source_is_still_there():
    """Counter-check: removing the decoy must not remove the real thing."""
    from services.member_count import get_member_count_service

    assert callable(get_member_count_service)


def test_the_scan_would_notice_a_return():
    """BLINDNESS GUARD: an empty result must mean "gone", not "looked for
    nothing"."""
    planted = "from services.mech.monthly_member_cache import MonthlyMemberCache\n"

    assert "MonthlyMemberCache" in _names_used(planted)
