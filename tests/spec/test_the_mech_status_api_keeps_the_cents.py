# -*- coding: utf-8 -*-
"""The mech status API reports the donated total with its cents.

THE FINDING (stage 4 review before v3.1.0, section 32 pass 4): total_donated
is dollars as a float, and the route's _safe_int truncated it - $12.99 was
reported as 12 under success: true. Only API callers see it (no template
or script reads /api/mech/status).

THE CONTRACT: the total is a number of dollars rounded to cents.

HOW THIS TEST CAN FAIL: the cents are cut off again.

COUNTER-CHECK (2026-09-30): red before the change (12).
"""

from types import SimpleNamespace

import pytest

from tests.spec.panel_client import basic_auth, panel  # noqa: F401 - fixture


@pytest.mark.parametrize("total, shown", [(12.99, 12.99), (0.1 + 0.2, 0.3), (5, 5.0), (True, 0.0)])
def test_the_total_keeps_its_cents(panel, monkeypatch, total, shown):  # noqa: F811
    status = {"total_donated": total, "current_level": 2, "donations_count": 1}
    monkeypatch.setattr("services.mech.mech_reset_service.get_mech_reset_service",
                        lambda: SimpleNamespace(get_current_status=lambda: status))

    answer = panel.test_client().get("/api/mech/status", headers=basic_auth())

    assert answer.status_code == 200
    assert answer.get_json()["status"]["total_donated"] == shown
