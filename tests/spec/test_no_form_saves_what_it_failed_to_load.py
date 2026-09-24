# -*- coding: utf-8 -*-
"""A settings form does not write back values it never managed to read.

THE RULE, WIDENED FROM ITS SHAPE (2026-09-24).
Review E22 found it in the admin dialog: `/api/admin-users` answered a read
failure with HTTP 200, the panel's success path read that body as "there are
no admins", opened the dialog saying so, and the next Save wrote the empty
list over the real one. Both halves were repaired - the route answers 500, and
config-ui.js keeps an `adminDataLoaded` flag, refuses to open on a bad read
and refuses to save when the flag is false.

The rule is about every form that loads settings and writes them back. Asked
of the whole panel, two more do exactly what the admin dialog used to do:

    spam_protection_modal.js   loads /api/spam-protection with
                               `.then(r => r.json())` and no check. On a
                               failure the alert appears, the dialog stays open
                               showing the HTML start values, and Save posts
                               all of them - every command and button cooldown
                               reset to the template's numbers.

    auto_actions.js            loadAASGlobalSettings() the same way, and
                               saveAASGlobalSettings() writes the whole object
                               back. What is lost there is worse than a
                               number: `protected_containers` is the list a
                               rule may never touch, and an empty form saves an
                               empty list.

The server halves are already right. /api/spam-protection answers a read
failure with 500 and a reason (review D9), and it is the CLIENT that reads it
as settings - the same asymmetry E22 found, one endpoint further on.

WHAT THIS TEST READS, and what it cannot: the source of the three scripts,
with comments stripped, because the runtime image has no JavaScript engine -
the same limitation and the same honesty as test_the_page_scripts_are_parseable.py
and the E22 test itself. It cannot prove the guard runs; it proves the guard
is there, that it is set only after a successful read, and that the save asks
it.

HOW THIS TEST CAN FAIL: a settings form that reads a payload without checking
the response, or that saves without asking whether the read worked.

COUNTER-CHECK (2026-09-24): red before for both scripts; config-ui.js was
green from the start, which is the point - it is the one that was repaired.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "app" / "static" / "js"

# script -> (the function that loads, the function that saves, the flag)
FORMS = {
    "spam_protection_modal.js": ("/api/spam-protection", "saveSpamProtection",
                                 "spamSettingsLoaded"),
    "auto_actions.js": ("/api/automation/settings", "saveAASGlobalSettings",
                        "aasSettingsLoaded"),
    # The one review E22 repaired, kept here so the pattern cannot quietly
    # leave the file it was written for.
    "config-ui.js": ("/api/admin-users", "saveAdminUsers", "adminDataLoaded"),
}

COMMENT = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)


def _source(name):
    return COMMENT.sub("", (SCRIPTS / name).read_text(encoding="utf-8"))


def _function_body(source, name):
    """The text of `function name(...)` up to the next top-level function."""
    start = re.search(r"(?:async\s+)?function\s+" + re.escape(name) + r"\s*\(", source)
    assert start, f"{name} is gone"
    rest = source[start.end():]
    end = re.search(r"\n(?:async\s+)?function\s+\w+\s*\(", rest)
    return rest[:end.start()] if end else rest


def test_every_settings_form_keeps_a_loaded_flag():
    """The flag is the whole repair: without it nothing can be asked later."""
    missing = []
    for name, (_url, _save, flag) in FORMS.items():
        source = _source(name)
        if not re.search(r"\b(?:let|var|const)\s+" + re.escape(flag) + r"\s*=\s*false\b", source):
            missing.append(f"{name}: no `{flag} = false` to start from")
    assert missing == [], missing


def test_the_flag_is_set_only_after_a_checked_read():
    """Set before the check, it would say "loaded" about an error body."""
    wrong = []
    for name, (url, _save, flag) in FORMS.items():
        source = _source(name)
        fetch_at = source.find(url)
        set_at = re.search(re.escape(flag) + r"\s*=\s*true", source)
        if not set_at:
            wrong.append(f"{name}: {flag} is never set")
            continue
        between = source[fetch_at:set_at.start()]
        if ".ok" not in between and "response.status" not in between:
            wrong.append(f"{name}: {flag} is set without checking the response first")
    assert wrong == [], wrong


def test_the_save_refuses_when_the_read_failed():
    """THE POINT: this is where the data was lost - a Save over values the
    form never read."""
    unguarded = []
    for name, (_url, save, flag) in FORMS.items():
        body = _function_body(_source(name), save)
        if flag not in body:
            unguarded.append(f"{name}: {save}() never asks {flag}")
            continue
        guard = body[:body.index(flag) + 200]
        if "return" not in guard:
            unguarded.append(f"{name}: {save}() reads {flag} but does not stop for it")
    assert unguarded == [], unguarded


def test_the_reader_checks_the_response():
    """fetch() rejects on a network failure and on nothing else - not on a 500,
    and not on a 200 carrying an error body."""
    unchecked = []
    for name, (url, _save, _flag) in FORMS.items():
        source = _source(name)
        after = source[source.find(url): source.find(url) + 700]
        if ".ok" not in after and "response.status" not in after:
            unchecked.append(f"{name}: the read of {url} never looks at the response")
    assert unchecked == [], unchecked
