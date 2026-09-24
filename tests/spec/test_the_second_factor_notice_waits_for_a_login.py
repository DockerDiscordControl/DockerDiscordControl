# -*- coding: utf-8 -*-
"""The second-factor notice is for somebody who is logged in.

THE OPERATOR (2026-09-25), with a screenshot of the login page carrying the
banner: "shouldn't the 2FA banner come only after the login? you have to be
logged in to set it up."

HE IS RIGHT TWICE OVER.

IT ASKS FOR SOMETHING THAT CANNOT BE DONE THERE. "Set up now" goes to
/security/2fa, which is @auth.login_required, so it answers 302 to /login -
back to the page the button was on. The one control the banner offers is a
loop, and "Later" posts a dismissal for a visitor who has no session to
remember it in.

AND IT TELLS A STRANGER SOMETHING. The banner is on the door: anybody who can
reach the port learns that this panel has no second factor, without typing a
password. That is a small thing next to knowing the password - but it is a
thing nobody needs to be told, and it is told before anyone has proved
anything.

WHY IT HAPPENED. The notice is a context processor, so it runs for every
template this app renders. It asked only whether the second factor is off -
never whether there is anybody there to ask. A context processor sees every
page, including the ones in front of the login.

HOW THIS TEST CAN FAIL: the notice appearing without a session, or
disappearing for a session that has one.

COUNTER-CHECK (2026-09-25): red before - the notice was on the login page, and
the case that asks an anonymous client for it found the banner in the markup.
"""

from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[2]


@pytest.fixture
def app(tmp_path, monkeypatch):
    """A Flask app with the notice installed, and nothing else in the way."""
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    # A session is only valid against a CONFIGURED password: password_binding()
    # answers None on a fresh install, so without this the "logged in" case
    # would be testing a login that cannot happen (app/auth.py).
    import app.auth as auth_module

    monkeypatch.setattr(auth_module, "load_config",
                        lambda: {"web_ui_password_hash": "pbkdf2:sha256:test",
                                 "web_ui_user": "admin"})
    from flask import Flask, render_template_string, session

    from app.blueprints.two_factor_routes import _notice_state

    application = Flask(__name__, template_folder=str(PROJECT / "app" / "templates"))
    application.config.update(TESTING=True, SECRET_KEY="notice")
    application.context_processor(_notice_state)

    @application.route("/anywhere")
    def anywhere():
        return render_template_string(
            "{% if two_factor is defined and two_factor.show %}BANNER{% else %}NONE{% endif %}")

    @application.route("/pretend-login")
    def pretend_login():
        # Logged in the way login_routes does it: the marker is checked
        # against the password binding, so setting any old key would be a
        # stand-in that does not resemble a login.
        from app.auth import SESSION_AUTH_KEY, password_binding

        session[SESSION_AUTH_KEY] = password_binding()
        return "ok"

    return application


def test_a_visitor_who_is_not_logged_in_sees_nothing(app):
    """THE FINDING, the half a stranger sees."""
    answer = app.test_client().get("/anywhere")

    assert answer.get_data(as_text=True) == "NONE", (
        "the panel tells anybody who can reach the port that it has no second factor")


def test_somebody_logged_in_is_asked(app):
    """Counter-check: switching it off for everyone would pass the case above.
    The notice has a job, and it does it once there is somebody to ask."""
    client = app.test_client()
    client.get("/pretend-login")
    answer = client.get("/anywhere")

    assert answer.get_data(as_text=True) == "BANNER"


def test_the_state_says_so_itself(app, monkeypatch):
    """The flag, not the markup: a template that stopped reading it would pass
    the cases above while the state was still wrong."""
    from app.blueprints.two_factor_routes import _notice_state

    with app.test_request_context("/anywhere"):

        assert _notice_state()["two_factor"]["show"] is False

    with app.test_client() as client:
        client.get("/pretend-login")
        client.get("/anywhere")

        assert _notice_state()["two_factor"]["show"] is True


def test_the_login_page_itself_carries_no_banner(app):
    """The page the operator photographed, rendered."""
    from flask import render_template

    with app.test_request_context("/login"):
        markup = render_template("_two_factor_notice.html")

    assert "alert" not in markup, markup.strip()[:200]


def test_the_notice_asks_who_is_there():
    """Read from the syntax tree: the state must consult the session, not just
    whether the second factor happens to be off."""
    import ast

    source = (PROJECT / "app" / "blueprints" / "two_factor_routes.py").read_text(encoding="utf-8")
    state = next(node for node in ast.walk(ast.parse(source))
                 if isinstance(node, ast.FunctionDef) and node.name == "_notice_state")

    assert "session_user" in ast.unparse(state), (
        "the notice does not ask whether anybody is logged in")


def test_the_page_it_points_at_still_needs_a_login():
    """Counter-check the other way: the loop was only a loop because that page
    is protected, and it must stay protected."""
    import ast

    source = (PROJECT / "app" / "blueprints" / "two_factor_routes.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef) and node.name == "status":
            marks = [ast.unparse(d) for d in node.decorator_list]

            assert any("login_required" in m for m in marks), marks
            return
    raise AssertionError("the page the banner points at is gone")
