# -*- coding: utf-8 -*-
"""
THE FINDING (review C21, section 35 F1): the `/api/admin-users` route catches

    except (RuntimeError) as e:

around the save, and nothing at all around the read. A full disk, a permission
problem, a corrupt admins.json - all of them raise OSError or
json.JSONDecodeError, none of them RuntimeError. So instead of the
`{"success": false, "error": ...}` the route was written to return, the request
ends as an unhandled 500 and the panel shows nothing useful.

Twenty lines further down, `health_check()` in the same file catches
IOError, OSError, PermissionError, RuntimeError, docker.errors.APIError,
docker.errors.DockerException and json.JSONDecodeError for a comparable
situation. The two handlers in one file did not agree on what can go wrong.

The counter-check (test_a_good_save_still_says_so) keeps the success path
intact.
"""

import json

import pytest
from flask import Flask

from app.web import routes as routes_module


class _AdminService:
    def __init__(self, on_get=None, on_save=None):
        self._on_get = on_get
        self._on_save = on_save

    def get_admin_data(self):
        if self._on_get:
            raise self._on_get
        return {"discord_admin_users": ["1"], "admin_notes": {}}

    # The third parameter came with the per-admin container assignment
    # (review F1/F5); the route passes it on every save.
    def save_admin_data(self, users, notes, admin_containers=None):
        if self._on_save:
            raise self._on_save
        return True


@pytest.fixture
def client(monkeypatch):
    app = Flask(__name__)
    app.config['TESTING'] = True
    monkeypatch.setattr(routes_module.auth, "login_required", lambda f: f)
    routes_module.register_routes(app)
    return app.test_client()


def _use(monkeypatch, service):
    monkeypatch.setattr(routes_module, "get_admin_service", lambda: service)


def test_a_disk_error_while_saving_gives_an_answer(client, monkeypatch):
    """THE FINDING: OSError is not RuntimeError."""
    _use(monkeypatch, _AdminService(on_save=OSError("no space left on device")))

    response = client.post("/api/admin-users",
                           json={"discord_admin_users": ["123456789012345678"]})

    assert response.status_code == 200
    assert json.loads(response.data)["success"] is False


def test_a_corrupt_file_while_reading_gives_an_answer(client, monkeypatch):
    """The GET branch had no guard at all.

    **The status changed from 200 to 500 on 2026-09-21 (review E22), and that
    is the same finding one level on.** What C21 was about is that the route
    EXPLAINS the failure instead of ending as an unhandled 500, and that is
    still exactly what it does - the body below is unchanged. What C21 pinned
    by accident was the literal 200, which is a different claim: it says the
    request succeeded.

    It had not, and ``fetch()`` does not reject on a 200, so the panel ran its
    success path over the error body and read it as "there are no admins" - and
    the next Save wrote that empty list over the file that could not be read.
    See test_a_failed_admin_read_cannot_erase_the_admins.py.
    """
    _use(monkeypatch, _AdminService(on_get=json.JSONDecodeError("bad", "{", 0)))

    response = client.get("/api/admin-users")

    assert response.status_code == 500
    assert json.loads(response.data)["success"] is False, (
        "the status code must not replace the explanation - that was C21's point"
    )


def test_a_good_save_still_says_so(client, monkeypatch):
    """COUNTER-CHECK: the working path is untouched."""
    _use(monkeypatch, _AdminService())

    response = client.post("/api/admin-users",
                           json={"discord_admin_users": ["123456789012345678"]})

    assert json.loads(response.data) == {"success": True}
    assert json.loads(client.get("/api/admin-users").data)["discord_admin_users"] == ["1"]
