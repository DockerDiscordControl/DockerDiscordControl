# -*- coding: utf-8 -*-
"""Text that did not come from this page is shown as text, never as markup.

THE RULE, WIDENED FROM ITS SHAPE (2026-09-24).
test_setup_alerts_show_text_not_markup.py pins exactly this for one page:
CodeQL #57 found `alert.innerHTML = \\`${message}<button …>\\`` in setup.html,
where the message comes from the server or from the browser, and the repair
was to insert it with textContent. The rule is about foreign text; the test
reads one file, because that is where the finding was.

channel_translation.js had already answered the same question the other way
round and correctly - it runs every message through ctEscapeHtml() before
building the markup. So the project holds the rule in two places and states it
in one.

Asked of every script, eleven places in four files did neither:

    panel.js       six times: three `${data.message}`, two error texts and
                   one HTTP status line, plus a list of file paths whose
                   elements are escaped one by one
    mech_panel.js  three times, twice `+ error.message`
    auto_actions.js and token_security_modal.js  once each

WHAT CAN ACTUALLY BE IN THERE: a server message echoing a value the operator
typed - a display name, a group name, the 250 characters of custom info text -
and a browser error text carrying a URL. None of it is markup, and all of it
was parsed as markup.

WHAT IS ALLOWED: a text this page owns. `t('…')` reads DDC's own catalogue, so
it is not foreign; a constant string is not foreign either. Everything else
goes through ddcEscapeHtml() (app/static/js/escape.js) or into textContent.

HOW THIS TEST CAN FAIL: writing a server or browser string into innerHTML
without escaping it.

COUNTER-CHECK (2026-09-24): red before, naming all eleven.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "app" / "static" / "js"

# An expression is FOREIGN when its text came from outside this page.
FOREIGN = re.compile(r"""
    (?:error|err|e)\.message              # a browser exception
  | \.statusText                          # an HTTP status line
  | \b(?:data|result|response|body)\.[\w.]*(?:message|error|text|name|files)
""", re.VERBOSE)

# An escaper call, with what it escapes. Removing these from the text first is
# the whole check: whatever foreign expression is LEFT is one nothing escapes.
# A window around the match is not enough - `data.config_files.map(file =>
# `<code>${ddcEscapeHtml(file)}</code>`)` escapes correctly and reads as raw
# forty characters earlier, which is exactly how this scan first lied to me.
ESCAPER = re.compile(r"\b(?:ddcEscapeHtml|escapeHtml|ctEscapeHtml|escapeAttribute)\([^()]*\)")

# A foreign value that is TRAVERSED is not the text being written: in
# `data.config_files.map(file => `<code>${ddcEscapeHtml(file)}</code>`)` the
# array is not what lands in the page, each escaped element is. Only these
# four, so that `${data.message.trim()}` stays a finding.
TRAVERSED = re.compile(r"\.(?:map|join|filter|forEach|length)\b")

ASSIGNMENT = re.compile(r"\.innerHTML\s*\+?=\s*([^;]{0,400});", re.S)
TRANSLATION = re.compile(r"t\(\s*['\"][^'\"]+['\"]\s*\)")


def _scripts():
    for path in sorted(SCRIPTS.rglob("*.js")):
        yield path, path.read_text(encoding="utf-8", errors="replace")


def _unescaped_markup():
    found = []
    for path, source in _scripts():
        for match in ASSIGNMENT.finditer(source):
            value = TRANSLATION.sub("", match.group(1))   # our own catalogue
            value = ESCAPER.sub("", value)                # already made safe
            for piece in FOREIGN.finditer(value):
                if TRAVERSED.match(value, piece.end()):
                    continue
                line = source[:match.start()].count("\n") + 1
                found.append(f"{path.name}:{line} {piece.group(0)}")
    return found


def test_the_scan_sees_the_scripts():
    """Safeguard against a blunt tool: a scan reading nothing is green."""
    scripts = list(_scripts())
    assignments = sum(len(ASSIGNMENT.findall(source)) for _path, source in scripts)

    assert len(scripts) > 15, f"only {len(scripts)} scripts found - wrong path?"
    assert assignments > 40, f"only {assignments} innerHTML assignments - shape changed?"


def test_no_foreign_text_is_written_as_markup():
    """THE FINDING: eleven places wrote a server or browser string into the
    page as HTML."""
    raw = _unescaped_markup()

    assert raw == [], (
        f"{len(raw)} place(s) write foreign text into innerHTML unescaped - "
        f"use ddcEscapeHtml() or textContent:\n  " + "\n  ".join(raw))


def test_the_escaper_exists_and_is_loaded_first():
    """A helper the page loads after its users is a helper that is not there
    when they run."""
    scripts = (ROOT / "app" / "templates" / "_scripts.html").read_text(encoding="utf-8")

    assert (SCRIPTS / "escape.js").exists(), "there is no shared escaper"
    assert "js/escape.js" in scripts, "the escaper is never loaded"
    for user in ("js/panel.js", "js/auto_actions.js", "js/mech_panel.js"):
        if user in scripts:
            assert scripts.index("js/escape.js") < scripts.index(user), (
                f"{user} is loaded before the escaper it uses")


def test_the_escaper_really_escapes():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed here - run tests/js/escape.test.js by hand")
    result = subprocess.run([node, str(ROOT / "tests" / "js" / "escape.test.js")],
                            capture_output=True, text=True, timeout=60)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("ok   - ") == 5, result.stdout
