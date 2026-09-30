# -*- coding: utf-8 -*-
"""The difficulty route refuses a text override and a missing multiplier cleanly.

THE FINDING (stage 4 review before v3.1.0, section 32 pass 4): the route
used manual_override by truthiness, so the string "false" selected STATIC
mode at the given multiplier instead of resetting to dynamic (the panel
sends a real boolean; the D29 class). And difficulty_multiplier: null
raised TypeError, which no handler listed, so a JSON client got an HTML
500 page. (The range itself was already checked by the service.)

THE CONTRACT: a present manual_override that is not true or false is
refused with 400 before anything changes; a multiplier that is not a
number is a JSON 400.

HOW THIS TEST CAN FAIL: "false" switches to static mode again, or null
answers with a 500 page.

COUNTER-CHECK (2026-09-30): red before the change (static mode set; 500).
"""

from types import SimpleNamespace

import pytest

from tests.spec.panel_client import basic_auth, panel  # noqa: F401 - fixture


@pytest.fixture
def difficulty(monkeypatch):
    calls = []
    answer = SimpleNamespace(success=True, data={"success": True}, error=None)
    stub = SimpleNamespace(manage_difficulty=lambda r: (calls.append(r) or answer))
    monkeypatch.setattr("services.web.mech_web_service.get_mech_web_service", lambda: stub)
    return calls


def _post(panel, body):  # noqa: F811
    return panel.test_client().post("/api/mech/difficulty", json=body, headers=basic_auth())


@pytest.mark.parametrize("override", ["false", "true", 0, None])
def test_a_text_override_is_refused(panel, difficulty, override):  # noqa: F811
    answer = _post(panel, {"difficulty_multiplier": 1.5, "manual_override": override})
    assert answer.status_code == 400, answer.get_data(as_text=True)[:200]
    assert difficulty == [], "the difficulty was changed anyway"


@pytest.mark.parametrize("multiplier", [None, [], {}, "abc"])
def test_a_multiplier_that_is_no_number_is_a_json_400(panel, difficulty, multiplier):  # noqa: F811
    answer = _post(panel, {"difficulty_multiplier": multiplier, "manual_override": True})
    assert answer.status_code == 400
    assert answer.get_json()["success"] is False
    assert difficulty == []


def test_real_values_still_go_through(panel, difficulty):  # noqa: F811
    assert _post(panel, {"difficulty_multiplier": 1.5, "manual_override": True}).status_code == 200
    assert _post(panel, {"difficulty_multiplier": 1.0}).status_code == 200
    assert [request.operation for request in difficulty] == ["set", "reset"]
