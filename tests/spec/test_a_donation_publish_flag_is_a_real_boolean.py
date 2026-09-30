# -*- coding: utf-8 -*-
"""The donation route takes publish_to_discord only as a real true or false.

THE FINDING (stage 4 review before v3.1.0, section 32 pass 4):
submit_donation passed publish_to_discord unchecked, and the service
tests its truthiness - so the string "false" announced the donation in
Discord although the caller switched that off, and an announcement cannot
be taken back. The panel sends a real boolean; a hand-made request hits
it - the class refused for is_active (review D29).

THE CONTRACT: anything but true or false is refused with 400 before the
donation is booked; a missing flag still means "announce".

HOW THIS TEST CAN FAIL: a string reaches the service again.

COUNTER-CHECK (2026-09-30): red before the change (200, booked).
"""

from types import SimpleNamespace

import pytest

from tests.spec.panel_client import basic_auth, panel  # noqa: F401 - fixture


@pytest.fixture
def booked(monkeypatch):
    calls = []
    answer = SimpleNamespace(success=True, message="ok", donation_info={}, error=None)
    stub = SimpleNamespace(process_donation=lambda r: (calls.append(r) or answer))
    monkeypatch.setattr("services.web.donation_service.get_donation_service", lambda: stub)
    return calls


@pytest.mark.parametrize("flag", ["false", "0", 0, None])
def test_anything_but_a_boolean_is_refused(panel, booked, flag):  # noqa: F811
    answer = panel.test_client().post(
        "/api/donation/submit",
        json={"amount": 5, "publish_to_discord": flag, "idempotency_key": "k1"},
        headers=basic_auth())
    assert answer.status_code == 400, answer.get_json()
    assert booked == [], "the donation was booked anyway"


def test_a_real_boolean_and_a_missing_flag_go_through(panel, booked):  # noqa: F811
    client = panel.test_client()
    for body in ({"amount": 5, "publish_to_discord": False}, {"amount": 5}):
        assert client.post("/api/donation/submit", json=body, headers=basic_auth()).status_code == 200
    assert [request.publish_to_discord for request in booked] == [False, True]
