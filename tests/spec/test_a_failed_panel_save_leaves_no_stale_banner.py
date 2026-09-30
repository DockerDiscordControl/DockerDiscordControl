# -*- coding: utf-8 -*-
"""A failed save from the panel leaves no error banner behind for a later page.

THE FINDING (stage 4 review before v3.1.0, section 32 pass 4): on its three
exception paths save_config_api flashed an error although the panel's
caller (always AJAX, X-Requested-With) gets JSON. The flash stayed in the
session and showed up on the next full page render - possibly after a
later save had succeeded.

THE CONTRACT: an AJAX save answers in its JSON only; the banner is kept for
a plain form submit, which is redirected to a page that shows it.

HOW THIS TEST CAN FAIL: the banner appears on the next page again.

COUNTER-CHECK (2026-09-30): red before the change (the banner on the page).
"""

import pytest

from tests.spec.panel_client import basic_auth, panel  # noqa: F401 - fixture


def _broken_service():
    raise RuntimeError("the save service is gone")


@pytest.fixture
def failing_save(monkeypatch):
    monkeypatch.setattr("services.web.configuration_save_service.get_configuration_save_service",
                        _broken_service)


def test_an_ajax_failure_is_not_flashed(panel, failing_save):  # noqa: F811
    client = panel.test_client()
    answer = client.post("/save_config_api", data={"language": "en"},
                         headers={**basic_auth(), "X-Requested-With": "XMLHttpRequest"})
    assert answer.get_json()["success"] is False

    with client.session_transaction() as session:
        assert not session.get("_flashes"), "the failure waits in the session for the next page"


def test_a_form_submit_still_gets_its_banner(panel, failing_save):  # noqa: F811
    client = panel.test_client()
    answer = client.post("/save_config_api", data={"language": "en"}, headers=basic_auth())
    assert answer.status_code == 302
    with client.session_transaction() as session:
        assert session.get("_flashes"), "a plain submit lost its message"
