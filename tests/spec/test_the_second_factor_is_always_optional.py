# -*- coding: utf-8 -*-
"""The second factor can always be declined, and always be switched off again.

THE OPERATOR (2026-09-25), looking at the setup page: "2FA must always be
optional." It is the decision he made on 2026-09-22 - offered and strongly
recommended, never forced - and measured today it holds everywhere: setup only
begins when it is asked for, a begun setup leaves the panel open until a code
confirms it, and switching it off is offered on the page and works.

SO WHY THIS FILE. Nothing in the suite held the RULE. Twelve cases pin how the
second factor behaves when it is on and when it is off; not one of them fails
if it quietly becomes mandatory. The promise lived in a decision record and in
the shape of the code, which is exactly the kind of promise that gets refactored
away by somebody who never read the record.

THE WAYS IT COULD BECOME MANDATORY, each with a case below:

  * the panel could redirect to setup while it is off;
  * a setup begun and abandoned could lock the panel - it does not, because
    `begin_setup` only stores a PENDING secret and `enabled` stays false until
    a code matches it;
  * the way out could disappear from the page, leaving an operator who no
    longer has the app with a panel he cannot open;
  * switching it off could require HTTPS. It deliberately does not: whoever
    turns TLS off later must not be locked into a factor he can no longer
    confirm. That one line is the difference between a recoverable panel and a
    reinstall.

WHAT IS NOT A CASE OF BEING FORCED: an unreadable state file closes the panel
(503). That is refusing to guess whether the factor is on, not making it
mandatory, and the message says the file can be removed. It is pinned as
deliberate in test_the_panel_asks_for_the_second_factor.py.

HOW THIS TEST CAN FAIL: a panel that pushes an operator into the second
factor, or one he cannot get back out of.

COUNTER-CHECK (2026-09-25): green from the start - the promise is kept today.
Sabotaged on that green baseline: setup forced on an operator who has not asked
(1 case red), the way out taken off the page (1 red), and switching it off made
to need HTTPS (1 red).
"""

import base64
from pathlib import Path

import pytest
from werkzeug.security import generate_password_hash

PROJECT = Path(__file__).resolve().parents[2]
PASSWORD = "a-long-enough-panel-password"
SECURE = "https://panel.test"
PLAIN = "http://panel.test"


def _basic():
    token = base64.b64encode(f"admin:{PASSWORD}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.fixture
def panel(monkeypatch, tmp_path):
    """(app, store), the same shape the other second-factor file uses."""
    monkeypatch.setenv("DDC_ENABLE_BACKGROUND_REFRESH", "false")
    monkeypatch.setenv("DDC_ENABLE_MECH_DECAY", "false")
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("DDC_TLS_MODE", raising=False)

    import app.auth as auth_module
    from app.auth import auth_limiter, clear_credential_cache, setup_limiter, two_factor_limiter
    from app.web import create_app
    from services.web.two_factor_service import TwoFactorStore

    hashed = generate_password_hash(PASSWORD)
    monkeypatch.setattr(auth_module, "load_config",
                        lambda: {"web_ui_user": "admin", "web_ui_password_hash": hashed})
    for limiter in (auth_limiter, setup_limiter, two_factor_limiter):
        limiter.ip_dict.clear()
    clear_credential_cache()

    app = create_app({"TESTING": True, "WTF_CSRF_ENABLED": False})

    @app.route("/__panel")
    @auth_module.auth.login_required
    def _panel():
        return "panel"

    yield app, TwoFactorStore(tmp_path / "two_factor.json")
    for limiter in (auth_limiter, setup_limiter, two_factor_limiter):
        limiter.ip_dict.clear()


def _enable(store):
    import time

    from services.web.two_factor_service import secret_bytes, totp

    store.begin_setup()
    now = time.time()
    return store.confirm_setup(
        totp(secret_bytes(store.pending_or_active_secret()), now - 30), now=now)


def _current_code(store):
    import time

    from services.web.two_factor_service import secret_bytes, totp

    return totp(secret_bytes(store.pending_or_active_secret()), time.time())


# --- it is never pushed on anybody --------------------------------------------

def test_the_panel_opens_without_it(panel):
    """THE PROMISE: offered, never required."""
    app, _store = panel

    assert app.test_client().get("/__panel", headers=_basic(),
                                 base_url=SECURE).status_code == 200


def test_nothing_sends_the_operator_to_the_setup(panel):
    """A redirect into the setup would be forcing it by another name."""
    app, _store = panel
    answer = app.test_client().get("/__panel", headers=_basic(), base_url=SECURE)

    assert answer.status_code == 200
    assert "2fa" not in answer.headers.get("Location", "")


def test_a_setup_begun_and_abandoned_leaves_the_panel_open(panel):
    """Somebody presses "set up now", sees the QR code, thinks better of it and
    closes the tab. `begin_setup` only stores a PENDING secret, so the factor
    is still off and the panel still opens with the password."""
    app, store = panel
    store.begin_setup()

    assert store.enabled is False
    assert app.test_client().get("/__panel", headers=_basic(),
                                 base_url=SECURE).status_code == 200


def test_only_a_matching_code_ever_switches_it_on(panel):
    """Counter-check on the case above: the pending secret must be what turns
    it on, or "abandoned" and "confirmed" would be the same state."""
    app, store = panel
    store.begin_setup()
    store.confirm_setup("000000")

    assert store.enabled is False
    _enable(store)

    assert store.enabled is True


# --- and it can always be left again ------------------------------------------

def test_the_page_offers_the_way_out_while_it_is_on(panel):
    """An operator who has lost the authenticator reads this page. If the way
    out is not on it, his panel is gone."""
    app, store = panel
    _enable(store)
    client = app.test_client()
    client.post("/security/2fa/verify", data={"code": _current_code(store)},
                headers=_basic(), base_url=SECURE)
    page = client.get("/security/2fa", headers=_basic(), base_url=SECURE)

    assert page.status_code == 200
    assert "/security/2fa/disable" in page.get_data(as_text=True)


def test_a_code_switches_it_off_again(panel):
    """No verified session first: the way out is reachable even to somebody who
    cannot get INTO the panel, which is the whole situation it exists for. A
    code is only good once, so using one to log in and the same one to switch
    off would fail on the replay guard rather than on the rule."""
    app, store = panel
    _enable(store)
    app.test_client().post("/security/2fa/disable", data={"code": _current_code(store)},
                           headers=_basic(), base_url=SECURE)

    assert store.enabled is False
    assert app.test_client().get("/__panel", headers=_basic(),
                                 base_url=SECURE).status_code == 200


def test_switching_it_off_does_not_need_tls(panel):
    """THE CASE THAT SAVES A PANEL. Setup needs HTTPS, and so does using the
    panel once the factor is on - but whoever switches TLS off later would
    then be locked into a factor he can no longer confirm. The way out is
    deliberately reachable over plain HTTP."""
    app, store = panel
    _enable(store)
    answer = app.test_client().post("/security/2fa/disable",
                                    data={"code": _current_code(store)},
                                    headers=_basic(), base_url=PLAIN)

    assert answer.status_code != 403, answer.get_data(as_text=True)[:200]
    assert store.enabled is False


def test_the_route_says_why_it_allows_plain_http():
    """A later tidy-up would otherwise "fix" the inconsistency by requiring
    HTTPS here too, and take the way out with it."""
    import ast

    source = (PROJECT / "app" / "blueprints" / "two_factor_routes.py").read_text(encoding="utf-8")
    disable = next(node for node in ast.walk(ast.parse(source))
                   if isinstance(node, ast.FunctionDef) and node.name == "disable")
    lines = source.splitlines()
    body = "\n".join(lines[disable.lineno - 1:disable.end_lineno])

    # A GATE, not a mention. The route hands request.is_secure to its own
    # error template, which is not the same as refusing a plain request - and
    # a case that searched for the characters would fail on that.
    gates = [node for node in ast.walk(disable)
             if isinstance(node, ast.If) and "is_secure" in ast.unparse(node.test)
             and any(isinstance(inner, ast.Return) for inner in ast.walk(node))]

    assert gates == [], "switching it off now needs TLS - that locks operators in"
    assert "#" in body, "the reason it allows plain HTTP is not written down"


def test_nothing_turns_it_on_by_configuration():
    """A setting that forced it would make the promise untrue for whoever
    flips it, which is the same as not having the promise."""
    import re

    offenders = []
    for root in ("app", "services", "utils"):
        for path in sorted((PROJECT / root).rglob("*.py")):
            text = path.read_text(encoding="utf-8", errors="replace")
            for match in re.finditer(r"DDC_(FORCE|REQUIRE)_?2?FA|force_two_factor|require_2fa",
                                     text, re.I):
                line = text[:match.start()].count("\n") + 1

                offenders.append(f"{path.relative_to(PROJECT)}:{line}")

    assert offenders == [], (
        f"these can make the second factor mandatory: {offenders}")
