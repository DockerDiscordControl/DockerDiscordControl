# -*- coding: utf-8 -*-
"""The debug switch saves itself, and the unsaved-changes box speaks German.

THE OPERATOR, 2026-09-24: "can we make the debug level save directly?" He had
just flipped it and got the warning box - "You have unsaved changes!" - for a
switch that has one bit of state and takes effect the moment it is stored.

IT IS NOT A SETTINGS FIELD, IT IS A CONTROL. Everything else on that form
belongs to one save: a token, a channel list and a language are changed
together and written together, and the Save button is what makes that one act.
The debug level belongs to the log view beside it. Turning it on while reading
a log is not editing a form, and asking the operator to find the Save button at
the bottom of a different tab for it is asking him to do the page's work.

So it posts itself, the way the container group rows already do, and applies at
once - since this morning it can, because `refresh_debug_status()` lowers the
handlers as well as the loggers.

THE TOAST IT USED TO POP UP WAS ALSO WRONG, twice over. "Debug Level enabled.
Save configuration to activate detailed logging." was hard-coded English in a
panel that speaks forty languages, and the instruction in it was false even
before today: the switch was wired to a key nothing read, so saving the
configuration activated nothing at all.

AND THE BOX HE SAW WAS HARD-CODED TOO. "Warning:", "You have unsaved changes!",
"Save", "Discard" - four English strings in the same box family as the restart
notice, which had the same defect and was fixed an hour earlier. Found by
looking at his screenshot rather than by a scan, which is why the scan is here
now: every one of those fixed boxes is checked, not just the one that was
reported.

HOW THIS TEST CAN FAIL: the switch going back to needing the Save button, or a
notice box carrying English text.

COUNTER-CHECK (2026-09-24): red before - the toggle called
showUnsavedChangesAlert and no route existed, and the box held four English
strings.
"""

import ast
import json
import re
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[2]
BASE = PROJECT / "app" / "templates" / "_base.html"
PANEL_JS = PROJECT / "app" / "static" / "js" / "panel.js"

# The boxes that float over the page and tell the operator something. Each was
# hard-coded English once; each is checked now, not only the one reported.
NOTICE_BOXES = ("unsaved-changes-alert", "restart-required-alert")


def _element(markup, element_id):
    at = markup.index(f'id="{element_id}"')
    start = markup.rindex("<div", 0, at)
    depth, i = 0, start
    while i < len(markup):
        if markup.startswith("<div", i):
            depth += 1
        elif markup.startswith("</div>", i):
            depth -= 1
            if depth == 0:
                return markup[start:i + len("</div>")]
        i += 1
    raise AssertionError(f"{element_id} is not closed")


@pytest.mark.parametrize("box", NOTICE_BOXES)
def test_no_notice_box_is_hard_coded_english(box):
    """THE FINDING, the half he saw: four English strings in a panel with forty
    catalogues."""
    text = re.sub(r"<[^>]*>|{{.*?}}|{%.*?%}", " ", _element(BASE.read_text(encoding="utf-8"), box))

    assert not re.search(r"[A-Za-z]{3,}", text), f"{box} shows untranslated text: {text.strip()!r}"


def test_the_switch_no_longer_waits_for_the_save_button():
    """THE REQUEST: it has one bit of state and applies the moment it is
    stored; it does not belong to the form's one save."""
    source = PANEL_JS.read_text(encoding="utf-8")
    at = source.index("debugLevelToggle")
    handler = source[at:at + 2000]

    assert "showUnsavedChangesAlert" not in handler, (
        "flipping the debug level still raises the unsaved-changes warning")
    assert "/api/debug-level" in handler, "the switch does not save itself"


def test_the_switch_no_longer_tells_him_to_save():
    """The toast said "Save configuration to activate detailed logging" - in
    English, and untrue: the switch was wired to a key nothing read."""
    source = PANEL_JS.read_text(encoding="utf-8")

    assert "Save configuration to activate" not in source
    assert "Debug Level disabled." not in source


def test_the_route_exists_and_needs_a_login():
    source = (PROJECT / "app" / "blueprints" / "system_routes.py").read_text(encoding="utf-8")
    marks = None
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef):
            decorators = [ast.unparse(d) for d in node.decorator_list]
            if any("debug-level" in d for d in decorators):
                marks = decorators

    assert marks, "no route sets the debug level"
    assert any("login_required" in m for m in marks)
    assert any("POST" in m for m in marks), "a change must not be a GET"


@pytest.mark.parametrize("wanted", [True, False])
def test_the_route_stores_and_applies(wanted, tmp_path, monkeypatch):
    """Stored AND applied: storing without applying is what the restart note
    used to cover for."""
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    from flask import Flask

    from app import auth as auth_module
    from app.blueprints.system_routes import system_bp

    applied = []
    import app.blueprints.system_routes as routes
    monkeypatch.setattr(routes, "_apply_debug_level",
                        lambda enabled: applied.append(enabled), raising=False)

    saved = {}

    class _Service:
        def get_config(self, force_reload=False):
            return dict(saved)

        def save_config(self, data):
            saved.update(data)
            return type("R", (), {"success": True, "message": "ok"})()

    monkeypatch.setattr(routes, "_config_service", lambda: _Service(), raising=False)
    monkeypatch.setattr(auth_module.auth, "verify_password_callback",
                        lambda user, password: "admin" if user and password else None)

    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="debug", WTF_CSRF_ENABLED=False)
    app.register_blueprint(system_bp)
    answer = app.test_client().post("/api/debug-level",
                                    headers={"Authorization": "Basic YWRtaW46YWRtaW4="},
                                    json={"enabled": wanted})

    assert answer.status_code == 200, answer.get_data(as_text=True)
    assert answer.get_json()["enabled"] is wanted
    assert saved.get("debug_level_enabled") is wanted, saved
    assert applied == [wanted], "stored but never applied"


def test_a_missing_answer_is_refused(tmp_path, monkeypatch):
    """A body without the field is not "switch it off"."""
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    from flask import Flask

    from app import auth as auth_module
    from app.blueprints.system_routes import system_bp

    monkeypatch.setattr(auth_module.auth, "verify_password_callback",
                        lambda user, password: "admin" if user and password else None)
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="debug", WTF_CSRF_ENABLED=False)
    app.register_blueprint(system_bp)
    answer = app.test_client().post("/api/debug-level",
                                    headers={"Authorization": "Basic YWRtaW46YWRtaW4="},
                                    json={})

    assert answer.status_code == 400


@pytest.mark.parametrize("key", ["web.common.unsaved_changes", "web.common.save",
                                 "web.common.discard", "web.logs.debug_level_saved",
                                 "web.logs.debug_level_failed"])
def test_every_new_text_is_in_every_catalogue(key):
    missing = [p.name for p in sorted((PROJECT / "locales").glob("*.json"))
               if p.name != "meta.json"
               and not json.loads(p.read_text(encoding="utf-8")).get(key)]

    assert missing == [], f"{key} missing from {len(missing)}: {missing[:5]}"
