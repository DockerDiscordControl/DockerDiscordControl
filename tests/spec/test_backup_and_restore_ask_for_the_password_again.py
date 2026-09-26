# -*- coding: utf-8 -*-
"""Backup and restore in the panel: the password again, a preview, then the swap.

The backup file holds the bot token, the second factor's secret and the
password hash, unencrypted (operator decision 2026-09-26). So taking it, and
replacing the configuration with one, each ask for the panel password AGAIN -
a session left open is not enough - under one brake per address. A restore is
previewed first and changes nothing until it is applied; applying replaces
the configuration and restarts DDC.

HOW THIS TEST CAN FAIL: a backup or restore without the password, a preview
that writes the configuration, an apply that does not restart, or a route
that skips CSRF.

COUNTER-CHECK (2026-09-26): _password_refused() sabotaged to always pass - the
wrong-password cases went red; restart_myself not called - the apply case went
red.
"""

import base64
import io
import json
import zipfile

import pytest
from werkzeug.security import generate_password_hash

PASSWORD = "a-long-enough-panel-password"
SECURE = "https://panel.test"


def _basic():
    return {"Authorization": "Basic " + base64.b64encode(f"admin:{PASSWORD}".encode()).decode()}


@pytest.fixture
def panel(monkeypatch, tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    (config / "config.json").write_text(json.dumps({"language": "de"}))
    (config / "tasks.json").write_text("[]")
    monkeypatch.setenv("DDC_CONFIG_DIR", str(config))
    monkeypatch.setenv("DDC_ENABLE_BACKGROUND_REFRESH", "false")
    monkeypatch.setenv("DDC_ENABLE_MECH_DECAY", "false")
    monkeypatch.delenv("DDC_TLS_MODE", raising=False)

    import app.auth as auth_module
    from app.auth import auth_limiter, clear_credential_cache, two_factor_limiter
    from app.blueprints.backup_routes import backup_limiter
    from app.web import create_app

    hashed = generate_password_hash(PASSWORD)
    monkeypatch.setattr(auth_module, "load_config",
                        lambda: {"web_ui_user": "admin", "web_ui_password_hash": hashed})
    for limiter in (auth_limiter, two_factor_limiter, backup_limiter):
        limiter.ip_dict.clear()
    clear_credential_cache()
    restarts = []
    monkeypatch.setattr("services.docker_service.self_restart.restart_myself",
                        lambda: (restarts.append(1) or True, "dockerdiscordcontrol"))
    app = create_app({"TESTING": True, "WTF_CSRF_ENABLED": False})
    yield app, config, restarts
    for limiter in (auth_limiter, two_factor_limiter, backup_limiter):
        limiter.ip_dict.clear()


def _post(app, path, **data):
    return app.test_client().post(path, data=data, headers=_basic(), base_url=SECURE,
                                  content_type="multipart/form-data")


def test_the_backup_needs_the_password_again(panel):
    app, _config, _ = panel

    assert _post(app, "/api/config/backup", password="wrong").status_code == 403
    answer = _post(app, "/api/config/backup", password=PASSWORD)

    assert answer.status_code == 200
    assert "config.json" in zipfile.ZipFile(io.BytesIO(answer.data)).namelist()


def test_guessing_is_braked(panel):
    app, _config, _ = panel
    for _ in range(5):
        _post(app, "/api/config/backup", password="wrong")

    assert _post(app, "/api/config/backup", password=PASSWORD).status_code == 429


def test_a_preview_changes_nothing_and_an_apply_swaps_and_restarts(panel):
    app, config, restarts = panel
    backup = _post(app, "/api/config/backup", password=PASSWORD).data
    (config / "config.json").write_text(json.dumps({"language": "en"}))

    preview = _post(app, "/api/config/restore/preview", password=PASSWORD,
                    backup=(io.BytesIO(backup), "ddc-backup.zip"))
    assert preview.status_code == 200, preview.get_data(as_text=True)
    assert preview.get_json()["summary"]["tasks"] == 0
    assert json.loads((config / "config.json").read_text()) == {"language": "en"}, "the preview wrote"

    assert _post(app, "/api/config/restore/apply", password="wrong").status_code == 403
    applied = _post(app, "/api/config/restore/apply", password=PASSWORD)

    assert applied.status_code == 200, applied.get_data(as_text=True)
    assert json.loads((config / "config.json").read_text()) == {"language": "de"}
    assert restarts == [1]


def test_a_hostile_upload_is_refused(panel):
    app, config, _ = panel
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("ddc-backup.json", json.dumps({"format": 1}))
        archive.writestr("../outside.json", "x")
        archive.writestr("config.json", "{}")

    answer = _post(app, "/api/config/restore/preview", password=PASSWORD,
                   backup=(io.BytesIO(buffer.getvalue()), "evil.zip"))

    assert answer.status_code == 400
    assert not (config / ".restore-pending.zip").exists()


def test_nobody_logged_in_gets_nothing(panel):
    app, _config, _ = panel

    answer = app.test_client().post("/api/config/backup", data={"password": PASSWORD}, base_url=SECURE)

    assert answer.status_code in (302, 401)


def test_the_routes_are_not_exempt_from_csrf(monkeypatch, panel):
    """With CSRF on, a request without the token is refused - the password is
    something a forged request from another site could not know, but the file
    it would download goes to the victim's browser, not to the attacker; the
    token is still required, like everywhere but the 2FA way out."""
    from app.web import create_app

    app = create_app({"TESTING": True, "WTF_CSRF_ENABLED": True})

    answer = app.test_client().post("/api/config/backup", data={"password": PASSWORD},
                                    headers=_basic(), base_url=SECURE)

    assert answer.status_code == 400


def test_what_the_panel_says_in_node():
    import shutil
    import subprocess
    from pathlib import Path

    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed here - run tests/js/backup_restore.test.js by hand")
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run([node, str(root / "tests" / "js" / "backup_restore.test.js")],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("ok   - ") == 4, result.stdout


def test_the_card_posts_nothing_with_the_settings_form():
    """The password asked here must never travel with an ordinary Save:
    saveConfigAjax collects every NAMED field of #config-form."""
    import re
    from pathlib import Path

    markup = (Path(__file__).resolve().parents[2] / "app" / "templates" / "_backup_settings.html").read_text(
        encoding="utf-8")
    fields = re.findall(r"<(?:input|select|textarea)\b[^>]*>", markup)

    assert fields and not any(re.search(r"\bname=", field) for field in fields), fields
    assert all('type="button"' in b for b in re.findall(r"<button\b[^>]*>", markup))
