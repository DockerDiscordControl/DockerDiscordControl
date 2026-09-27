# -*- coding: utf-8 -*-
"""A login link cannot send the browser to another host afterwards.

THE FINDING (CodeQL py/url-redirection, 2026-09-27, confirmed by hand): the
login and the second factor redirect to a ``next`` parameter, guarded by
"starts with / but not //, no backslash". ``/<TAB>/evil.example`` passed that
guard, Werkzeug wrote the tab into the Location header unchanged (measured in
the running image), and a browser removes tabs and line breaks from a URL
before reading it - so it followed ``//evil.example``, another host, right
after the operator typed the password.

HOW THIS TEST CAN FAIL:
* the rule lets a control character, a space, a backslash, a scheme or a host
  through, or refuses an ordinary panel path;
* the login page's own redirect (GET /login while logged in) still follows the
  tab trick - the call site, measured through the real route;
* one of the two places that redirect after a login stops using the shared
  rule and grows its own copy again (read from the source).

COUNTER-CHECK (2026-09-27): with the old rule restored in next_url.safe_next
the tab, newline and space cases and the route case went red.
"""

from pathlib import Path

import pytest
from flask import Flask

from app.web.next_url import safe_next

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("target", [
    "/\t/evil.example", "/\n/evil.example", "/\r/evil.example", "/ /evil.example",
    "//evil.example", "/\\evil.example", "https://evil.example", "evil.example",
    "javascript:alert(1)", "", "/\x00/evil.example", "/\x7f/evil.example",
])
def test_nothing_but_a_local_path_gets_through(target):
    assert safe_next(target) == "/", f"{target!r} was accepted as a place to go"


@pytest.mark.parametrize("target", ["/", "/config", "/two-factor/status?tab=system", "/logs#bot"])
def test_a_panel_path_still_works(target):
    assert safe_next(target) == target


def test_the_login_page_does_not_follow_the_tab_trick(monkeypatch):
    import app.auth as auth_module
    from app.blueprints.login_routes import login_bp

    monkeypatch.setattr(auth_module, "session_user", lambda: "admin")
    app = Flask(__name__)
    app.secret_key = "test-only"
    app.register_blueprint(login_bp)

    answer = app.test_client().get("/login", query_string={"next": "/\t/evil.example"})
    assert answer.status_code == 302
    assert answer.headers["Location"].rstrip("/") in ("", "http://localhost"), answer.headers["Location"]


def test_both_redirects_use_the_one_rule():
    for module in ("app/blueprints/login_routes.py", "app/blueprints/two_factor_routes.py"):
        source = (ROOT / module).read_text(encoding="utf-8")
        assert "from app.web.next_url import safe_next" in source, f"{module} has its own redirect rule again"
        assert 'startswith("//")' not in source, f"{module} carries a copy of the old rule"


def test_an_unreadable_group_file_names_no_host_path(monkeypatch):
    """Same audit (CodeQL py/stack-trace-exposure): the group list answered a
    read error with the raw OSError text, which names the file on the host.
    The details belong in the log; the browser gets a plain sentence.
    COUNTER-CHECK: red with `str(e)` restored in the response."""
    import app.auth as auth_module
    import app.blueprints.group_routes as group_routes

    class Unreadable:
        def get_groups(self):
            raise PermissionError(13, "Permission denied", "/app/config/groups.json")

    monkeypatch.setattr(group_routes, "get_group_service", lambda: Unreadable())
    monkeypatch.setattr(auth_module, "session_user", lambda: "admin")
    app = Flask(__name__)
    app.secret_key = "test-only"
    app.register_blueprint(group_routes.group_bp)

    answer = app.test_client().get("/api/groups")
    assert answer.status_code == 500
    assert "/app/config" not in answer.get_data(as_text=True), "a host path reached the browser"
