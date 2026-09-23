# -*- coding: utf-8 -*-
"""No form sits inside another form, because the browser throws the inner one away.

THE FINDING, met while checking the tab change (2026-09-23): `tasks/list.html`
carries `<form id="editTaskForm">` for its edit dialog, and that file is
included inside `<form id="config-form">`. Nested forms are invalid HTML, and
the HTML5 parser does not merely dislike them - it IGNORES the inner start
tag: "A start tag whose tag name is 'form': if the form element pointer is not
null, ignore the token." The children stay, the element does not.

So `document.getElementById('editTaskForm')` answers null in a browser, and
`tasks.js:688` reads

    document.getElementById('editTaskForm')?.reset();

The `?.` turns that into a silent no-op. resetEditModal() has never reset
anything, and nothing said so.

WHAT IT COSTS, measured in populateEditForm (tasks.js:368): the cron branch
sets only the cron string. It does NOT touch editTaskTime, editTaskDay,
editTaskWeekday, editTaskMonth or editTaskYear. With the reset working those
would be empty; without it they still hold whatever the PREVIOUS task put
there. Edit a daily task at 10:00, close the dialog, open a cron task - the
time still reads 10:00. The fields are disabled in that branch and the stale
value is not saved, so this is a lie on screen rather than lost data. It is
still a lie on screen.

WHAT CHANGES: the dialog moves out of the settings form into its own partial,
included beside the eight other modals config.html already keeps outside the
form. That is where a modal belongs, its own <form> becomes a real element
again, and reset() starts doing what its author meant.

HOW THIS TEST CAN FAIL: it renders the page and looks for a `<form` between
the settings form's opening tag and the element that follows its close. Any
form nested there is red, with no exception list - one exception is how this
one survived.

COUNTER-CHECK (2026-09-23): red before - one nested form, editTaskForm.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "app" / "templates"


def _rendered():
    from flask import Flask, render_template
    from jinja2 import ChainableUndefined

    app = Flask(__name__, template_folder=str(TEMPLATES))
    app.jinja_env.undefined = ChainableUndefined
    app.jinja_env.globals["_t"] = lambda key, **kwargs: key
    app.jinja_env.globals["csrf_token"] = lambda: "test-token"
    app.jinja_env.globals["url_for"] = lambda endpoint, **values: "/"

    with app.test_request_context("/"):
        return render_template(
            "config.html", config={}, all_containers=[], configured_servers={},
            container_info_data={}, active_container_names=[],
            DEFAULT_CONFIG={"default_channel_permissions": {}})


def test_the_page_renders_and_has_forms_to_look_at():
    """Safeguard against a blunt tool: a page with no forms passes everything."""
    html = _rendered()

    assert html.count("<form") >= 2, f"only {html.count('<form')} forms - wrong page?"
    assert html.count("<form") == html.count("</form>")


def test_no_form_is_nested_in_the_settings_form():
    """THE FINDING: editTaskForm was, so the browser dropped it and the
    dialog's reset() has been a silent no-op."""
    html = _rendered()
    opens = html.index('id="config-form"')
    # The element that follows </form> in config.html; no include can move it.
    after = html.index('id="save-notification"')

    nested = re.findall(r'<form[^>]*>', html[opens:after])

    assert nested == [], (
        f"{len(nested)} form(s) are nested inside #config-form, and a browser "
        f"throws away the inner start tag: {nested}")


def test_the_edit_dialog_is_still_on_the_page():
    """Counter-check on the move: the dialog must be somewhere, and its form
    must be a real element again."""
    html = _rendered()

    assert 'id="editTaskModal"' in html, "the edit dialog vanished with the move"
    assert 'id="editTaskForm"' in html
    assert html.index('id="save-notification"') < html.index('id="editTaskModal"'), (
        "the dialog is still inside the settings form")


def test_the_reset_has_something_to_reset():
    """The line this was all about: a form element it can actually find."""
    source = (ROOT / "app" / "static" / "js" / "tasks.js").read_text(encoding="utf-8")

    assert "getElementById('editTaskForm')" in source, (
        "the reset no longer looks for the form - re-read this test")
