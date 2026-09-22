# -*- coding: utf-8 -*-
"""The Bandit scan must really exclude the directories it names.

No ``@covers`` marker: this guards a check, not a guarantee.

THE FINDING (2026-09-19, first develop push through the CI gate):
``tests/security/test_security_sast.py`` passed ``--exclude`` five times.
Bandit keeps only the LAST one (measured with bandit 1.9.4: excluding
``tests`` first and another directory second still reports files under
``tests/``). So the scan always covered ``tests/``, ``venv``, ``.git`` and
``cached_animations`` - only ``cached_displays`` was excluded - and CI failed
on two deliberate ``chmod 0o766/0o777`` calls in a test that simulates an SMB
share. Nobody saw it before: until the gate, CI ran no tests at all, and the
Unraid runtime has no bandit, so the scan skips there.

HOW IT IS CHECKED: the runtime cannot run bandit, so a test that calls it
would only skip here - it could never fail. The command is checked instead:
one ``--exclude`` with every directory in a comma-separated list, which is
the form bandit reads.
"""

from pathlib import Path

SAST = Path(__file__).resolve().parents[1] / "security" / "test_security_sast.py"


def test_the_scan_passes_exclude_only_once():
    count = SAST.read_text(encoding="utf-8").count("'--exclude'")
    assert count == 1, (
        f"test_security_sast.py passes --exclude {count} times - bandit keeps only the "
        "last one, every other directory is scanned after all"
    )


def test_the_one_list_names_every_directory():
    """Counting alone would stay green if a directory were dropped from the list."""
    import ast

    tree = ast.parse(SAST.read_text(encoding="utf-8"))
    lists = [
        {e.value for e in node.elts}
        for node in ast.walk(tree)
        if isinstance(node, ast.Tuple) and node.elts
        and all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in node.elts)
        and "cached_displays" in {e.value for e in node.elts}
    ]
    assert lists == [{"tests", "venv", ".git", "cached_animations", "cached_displays"}], lists
