# -*- coding: utf-8 -*-
"""The donation click counter is for the logged-in panel, and braked.

THE FINDING (spam audit, 2026-09-26, F3): ``POST /api/donation/click`` was
the one write route of the panel without a login. Anybody who could reach
the port could post {"type": "coffee"} in a loop, and every request wrote a
DONATION_CLICK line into the user action log - the log an operator reads to
see who restarted what. The buttons that call it exist only on the logged-in
configuration page, so the open door served nobody.

HOW THIS TEST CAN FAIL: it posts without credentials (must be refused), then
with credentials past the per-address limit (the surplus must be refused and
must not reach the action log). The first authenticated click must still be
recorded - otherwise "refuse everything" would pass.

COUNTER-CHECK (2026-09-26): red before - the anonymous post was recorded,
and all thirty clicks went into the log.
"""

import base64
import json

import pytest
from werkzeug.security import generate_password_hash

PASSWORD = "a-long-enough-panel-password"


def _basic():
    return {"Authorization": "Basic " + base64.b64encode(f"admin:{PASSWORD}".encode()).decode()}


@pytest.fixture
def panel(monkeypatch, tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    (config / "config.json").write_text(json.dumps({"language": "en"}))
    (config / "tasks.json").write_text("[]")
    monkeypatch.setenv("DDC_CONFIG_DIR", str(config))
    monkeypatch.setenv("DDC_ENABLE_BACKGROUND_REFRESH", "false")
    monkeypatch.setenv("DDC_ENABLE_MECH_DECAY", "false")
    monkeypatch.delenv("DDC_TLS_MODE", raising=False)

    import app.auth as auth_module
    from app.auth import auth_limiter, clear_credential_cache
    from app.blueprints import main_routes
    from app.web import create_app

    hashed = generate_password_hash(PASSWORD)
    monkeypatch.setattr(auth_module, "load_config",
                        lambda: {"web_ui_user": "admin", "web_ui_password_hash": hashed})
    limiters = (auth_limiter, getattr(main_routes, "donation_click_limiter", None))
    for limiter in limiters:
        if limiter is not None:
            limiter.ip_dict.clear()
    clear_credential_cache()

    logged = []
    monkeypatch.setattr("services.infrastructure.action_logger.log_user_action",
                        lambda **kwargs: logged.append(kwargs))
    app = create_app({"TESTING": True, "WTF_CSRF_ENABLED": False})
    yield app, logged
    for limiter in limiters:
        if limiter is not None:
            limiter.ip_dict.clear()


def _click(app, headers=None):
    return app.test_client().post("/api/donation/click", json={"type": "coffee"},
                                  headers=headers or {})


def test_an_anonymous_click_is_refused(panel):
    app, logged = panel
    assert _click(app).status_code == 401
    assert logged == [], "an anonymous request wrote into the action log"


def test_a_flood_does_not_reach_the_action_log(panel):
    app, logged = panel
    answers = [_click(app, _basic()).status_code for _ in range(30)]

    assert answers[0] == 200, "the ordinary click must still be recorded"
    assert 429 in answers, "thirty clicks in a row were all accepted"
    assert len(logged) <= 10, f"{len(logged)} clicks went into the action log"
