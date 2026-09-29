# -*- coding: utf-8 -*-
"""An admins.json that cannot be read is not answered as "no admins" - and not overwritten.

THE FINDING (stage 4 review before v3.1.0, section 10 pass 4 F1, verified
2026-09-29). AdminService.get_admin_data answered an admins.json that
exists but cannot be read - broken JSON after a hand edit, a root-owned
0600 file - exactly like a missing one: an empty document. So:

  * /addadmin (open to anyone in a control channel, B1) built a one-admin
    document on it and wrote it: every other admin, their notes and their
    container assignments (B2) gone, answered "Admin added successfully,
    Total admins: 1";
  * the panel's GET /api/admin-users answered 200 with an empty list, and its
    next Save did the same. Review E22 gave that route a 500 branch for
    exactly this - dead, because the service swallowed the error first.
    test_a_failed_admin_read_cannot_erase_the_admins.py proved the route
    with a stand-in service that raises; the real one never did.

THE CONTRACT: an existing admins.json that cannot be read makes the read
fail loudly; nothing is written over it; the route answers 500.

HOW THIS TEST CAN FAIL: the service turns an unreadable file into an empty
document again.

It goes through the REAL service and a real file.

COUNTER-CHECK (2026-09-29): written before the fix and red then.
"""

import pytest
from flask import Flask

BROKEN = '{"discord_admin_users": ["111111111111111111"], "admin_notes": '


@pytest.fixture
def broken_admins(tmp_path, monkeypatch):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    admins = tmp_path / "admins.json"
    admins.write_text(BROKEN, encoding="utf-8")
    from services.admin import admin_service as module
    monkeypatch.setattr(module, "_admin_service_instance", None, raising=False)
    return admins


def _service():
    from services.admin.admin_service import AdminService
    return AdminService()


def test_adding_an_admin_does_not_write_over_an_unreadable_list(broken_admins):
    with pytest.raises(Exception):
        _service().add_admin_user("222222222222222222", "note")

    assert broken_admins.read_text(encoding="utf-8") == BROKEN, "the admin list was overwritten"


def test_the_read_itself_fails_loudly(broken_admins):
    with pytest.raises(Exception):
        _service().get_admin_data(force_refresh=True)


def test_the_panel_route_answers_500(broken_admins, monkeypatch):
    from app.web import routes as routes_module

    app = Flask(__name__)
    app.config["TESTING"] = True
    monkeypatch.setattr(routes_module.auth, "login_required", lambda f: f)
    routes_module.register_routes(app)
    monkeypatch.setattr(routes_module, "get_admin_service", _service)

    assert app.test_client().get("/api/admin-users").status_code >= 500


def test_a_missing_file_is_still_an_empty_list(tmp_path, monkeypatch):
    """Counter-check: no file is a fresh install, not an error."""
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))

    data = _service().get_admin_data(force_refresh=True)

    assert data["discord_admin_users"] == []
