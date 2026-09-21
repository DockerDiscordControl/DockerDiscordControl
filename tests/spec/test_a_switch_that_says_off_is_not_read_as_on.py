# -*- coding: utf-8 -*-
"""A switch that says off is not read as on.

THE FINDING (review D29, pass 2, section 32 F5): `POST /tasks/update_status`
checked the incoming flag only for `is None` and then built

    UpdateTaskStatusRequest(task_id=task_id, is_active=bool(is_active))

`bool("false")` is True. A caller sending the STRING "false" - a script, a
curl by hand, a future front end that serialises differently - switched the
task ON, and the route answered `{'success': True}`.

These tasks start and stop containers on a schedule. A task the operator
believes is off, running, is the sharpest shape this defect can take, and the
answer said it had worked.

Today's panel sends a real boolean (`target.checked`, tasks.js:301), so
nothing is wrong in the running installation. What was wrong is that the route
guessed at the meaning of anything else instead of saying it did not
understand it - and for a switch that moves containers, guessing is exactly
what must not happen.

The choice made here is to REFUSE, not to interpret. "false" could be meant
either way by a caller we know nothing about, and there is no safe way to pick
one. A 400 with a reason costs a careless caller one error message; a wrong
guess costs the operator a container that starts when they had switched it
off.
"""

from types import SimpleNamespace

import pytest
from flask import Flask

from app.blueprints.tasks_bp import tasks_bp


@pytest.fixture
def client(monkeypatch):
    """The route, with auth stubbed and the service recording what it was asked."""
    import app.auth as auth_module
    import services.web.task_management_service as service_module

    monkeypatch.setattr(auth_module.auth, "verify_password_callback",
                        lambda username, password: "admin")
    monkeypatch.setattr(auth_module.auth, "auth_error_callback",
                        lambda status: ("denied", status))

    asked = []

    def _service():
        def _update(request_obj):
            asked.append(request_obj.is_active)
            return SimpleNamespace(success=True, message="ok", task_data={},
                                   error=None)
        return SimpleNamespace(update_task_status=_update)

    monkeypatch.setattr(service_module, "get_task_management_service", _service)

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(tasks_bp, url_prefix="/tasks")
    return app.test_client(), asked


def _post(http, value):
    return http.post("/tasks/update_status",
                     json={"task_id": "t-1", "is_active": value})


@pytest.mark.parametrize("value", ["false", "true", "0", "1", "no", "yes", 0, 1])
def test_a_flag_that_is_not_a_flag_moves_nothing(client, value):
    """Anything but a real boolean must leave the task where it is."""
    http, asked = client

    response = _post(http, value)

    assert asked == [], (
        f"is_active={value!r} was passed on as {asked} - the route decided "
        f"what the caller must have meant"
    )
    assert response.status_code == 400, (
        f"is_active={value!r} was answered {response.status_code}"
    )
    assert (response.get_json() or {}).get("error"), "refused without a reason"


@pytest.mark.parametrize("value", [True, False])
def test_a_real_flag_still_goes_through(client, value):
    """The counter-case: refusing everything would satisfy the test above."""
    http, asked = client

    response = _post(http, value)

    assert asked == [value], f"is_active={value!r} arrived as {asked}"
    assert response.status_code == 200
    assert response.get_json()["success"] is True


def test_a_missing_flag_is_still_a_missing_flag(client):
    """A pin on the check that was already there."""
    http, asked = client

    response = http.post("/tasks/update_status", json={"task_id": "t-1"})

    assert asked == []
    assert response.status_code == 400
    assert "is_active" in response.get_json()["error"]
