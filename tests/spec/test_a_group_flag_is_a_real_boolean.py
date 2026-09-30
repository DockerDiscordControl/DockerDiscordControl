# -*- coding: utf-8 -*-
"""The task routes take target_is_group only as a real true or false.

THE FINDING (stage 4 review before v3.1.0, section 32 pass 4): add_task
turned target_is_group into bool() of whatever arrived, so the JSON string
"false" made a GROUP task for a group named like the container - answered
201 - and at run time the intended container was not acted on. The edit
route passed it on the same way. The panel sends a real boolean; a
hand-made request hits it - the class the project already refuses for
is_active (review D29).

THE CONTRACT: anything but true or false is refused with 400 and nothing
is saved; a missing flag still means a container task.

HOW THIS TEST CAN FAIL: a string is taken for a flag again.

COUNTER-CHECK (2026-09-30): red before the change (201 for "false").
"""

from types import SimpleNamespace

import pytest

from tests.spec.panel_client import basic_auth, panel  # noqa: F401 - fixture

TASK = {"container": "nginx", "action": "stop", "cycle": "daily",
        "schedule_details": {"time": "03:00"}}


@pytest.fixture
def service(monkeypatch):
    calls = []
    answer = SimpleNamespace(success=True, message="ok", task_data={"container": "nginx"}, error=None)
    stub = SimpleNamespace(add_task=lambda r: (calls.append(r) or answer),
                           edit_task=lambda r: (calls.append(r) or answer))
    monkeypatch.setattr("services.web.task_management_service.get_task_management_service",
                        lambda: stub)
    return calls


@pytest.mark.parametrize("flag", ["false", "true", 0, 1, None])
def test_add_refuses_anything_but_a_boolean(panel, service, flag):  # noqa: F811
    answer = panel.test_client().post("/tasks/add", json={**TASK, "target_is_group": flag},
                                      headers=basic_auth())
    assert answer.status_code == 400, answer.get_json()
    assert service == [], "the task went to the service anyway"


@pytest.mark.parametrize("flag", ["false", 1])
def test_edit_refuses_anything_but_a_boolean(panel, service, flag):  # noqa: F811
    answer = panel.test_client().put("/tasks/edit/abc", json={**TASK, "target_is_group": flag},
                                     headers=basic_auth())
    assert answer.status_code == 400, answer.get_json()
    assert service == []


def test_a_real_boolean_and_a_missing_flag_go_through(panel, service):  # noqa: F811
    client = panel.test_client()
    assert client.post("/tasks/add", json={**TASK, "target_is_group": False},
                       headers=basic_auth()).status_code == 201
    assert client.post("/tasks/add", json=TASK, headers=basic_auth()).status_code == 201
    assert [request.target_is_group for request in service] == [False, False]
