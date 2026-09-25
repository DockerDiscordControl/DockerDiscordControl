# -*- coding: utf-8 -*-
"""Nothing asks about, or reports on, a process manager DDC does not use.

MEASURED ON THE OPERATOR'S RUNNING PANEL, 2026-09-25. GET /port_diagnostics:

    "supervisord_status": {"error": "supervisorctl not available"}

and panel.js turned that into a section of its own:

    // Process Status
    html += `<span class="text-warning">${...supervisord_status.error}</span>`;

A yellow warning, under a heading, for the one state this installation can
ever be in. DDC has run as a SINGLE process since v3 - one bot plus a web UI
thread - and the image contains no supervisord at all; `command -v
supervisorctl` inside the container answers nothing. The probe shells out to a
binary that was removed on purpose and reports its absence as a problem.

THE SAME SHAPE, THREE TIMES IN ONE AFTERNOON. The Application tab served a
supervisord log from last November as today's. The port check turned "the
docker binary is not here" into "the port is not mapped" and advised a command
that would have replaced the container. This is the third and smallest: a
section that can only ever say "I cannot tell you", dressed as a warning.

AND A WARNING IS THE EXPENSIVE PART. Earlier today the only WARNING in 579
lines of his log turned out to be the normal case; the cost is that the next
warning, the real one, looks the same. A panel that greets every visit with a
yellow line teaches the same lesson faster, because it is on screen.

WHAT REPLACES IT: nothing. A diagnostic that cannot be made is not worth a
heading. Whether the web UI is alive is already answered, truthfully, by the
port check right below it.

HOW THIS TEST CAN FAIL: anything asking supervisorctl for a status, or any
page rendering one.

COUNTER-CHECK (2026-09-25): red before - the probe, its key in the report and
the panel section that drew it.
"""

import ast
import re
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
NOT_APP_CODE = {"tests", ".git", "node_modules", "htmlcov", "venv", ".venv", "docs"}


def _app_files(*suffixes):
    for path in sorted(PROJECT.rglob("*")):
        if not path.is_file() or path.suffix not in suffixes:
            continue
        if NOT_APP_CODE & set(path.relative_to(PROJECT).parts):
            continue
        yield path


def test_nothing_runs_supervisorctl():
    """THE FINDING: a probe for a program the image deliberately does not have."""
    callers = []
    for path in _app_files(".py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if "supervisorctl" in node.value:
                    callers.append(f"{path.relative_to(PROJECT)}:{node.lineno}")

    assert sorted(set(callers)) == [], (
        "DDC has been one process since v3 and the image has no supervisord - "
        f"this can only ever report its absence: {sorted(set(callers))}")


def test_the_report_carries_no_such_field():
    """The probe could go while the key stayed, answering {} forever - which
    is the shape that let the port check claim a fault from an empty answer."""
    offenders = []
    for path in _app_files(".py"):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"supervisord_status", text):
            offenders.append(f"{path.relative_to(PROJECT)}:{text[:match.start()].count(chr(10)) + 1}")

    assert sorted(set(offenders)) == [], offenders


def test_no_page_draws_a_process_status_from_it():
    """The other half. Removing the field alone would leave the panel reading
    an attribute that is never there - quiet, but still code pretending to
    have a subject.

    THE FIELD, NOT THE WORD, and this is the fourth time in one afternoon that
    a scan of mine went red on an explanatory COMMENT of my own. The line left
    in panel.js says why the section is gone - that DDC is one process and the
    image has no supervisord - which is exactly what the next person needs
    before helpfully putting it back. A comment is not a code path. Python
    lets me ask the syntax tree; for JavaScript the nearest honest question is
    whether the FIELD is referenced, which no prose ever does.
    """
    offenders = []
    for path in _app_files(".js", ".html"):
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in re.finditer(r"supervisord_status", text):
            offenders.append(f"{path.relative_to(PROJECT)}:{text[:match.start()].count(chr(10)) + 1}")

    assert sorted(set(offenders)) == [], offenders


def test_the_page_scan_would_catch_it_coming_back():
    """Counter-check on the narrowing above: the field pattern must still
    match the line that was there."""
    gone = 'if (diagnostics.host_info.supervisord_status && Object.keys(...))'

    assert re.search(r"supervisord_status", gone), "the page scan is blind"
    assert not re.search(r"supervisord_status", "// no supervisord here any more")


def test_the_port_check_still_answers_whether_the_web_ui_is_alive():
    """The opposite mistake: the section it replaces was worthless, but the
    question under it - is the web UI up - is a real one, and it is answered
    truthfully a few lines further down the same panel."""
    source = (PROJECT / "app" / "utils" / "port_diagnostics.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}

    assert "_is_port_listening" in names, "nothing checks the web UI is answering any more"
    assert "check_port_binding" in names


def test_the_scan_would_catch_it_coming_back():
    """Counter-check, the one nine sabotages have walked past: a scan that
    matches nothing passes the cases above while proving nothing."""
    text = 'result = subprocess.run(["supervisorctl", "status"])'
    found = [m.group(0) for m in re.finditer(r"supervisorctl", text)]

    assert found == ["supervisorctl"], found
