# -*- coding: utf-8 -*-
"""The mech status API reports the next goal and what is missing to the cent.

THE FINDING (seen 2026-09-30 while fixing stage 4 finding 32#12; the
operator asked for the fix): mech_reset_service built next_level_threshold
and amount_needed as dollars * 100 floats, and the route cut them with
int(): a goal of $12.99 is 1298.9999... * 100 in floating point and was
reported as 1298 cents.

THE CONTRACT: both are whole cents, rounded, not truncated - built so at
the source, and read so by the route.

HOW THIS TEST CAN FAIL: a cent is lost again.

COUNTER-CHECK (2026-09-30): red before the change (1298).
"""

from types import SimpleNamespace

import pytest

from services.mech.mech_reset_service import MechResetService
from tests.spec.panel_client import basic_auth, panel  # noqa: F401 - fixture


@pytest.mark.parametrize("goal, have, needed", [(12.99, 0.0, 1299), (12.99, 4.33, 866), (0.29, 0.0, 29)])
def test_the_goal_keeps_its_cents(panel, monkeypatch, tmp_path, goal, have, needed):  # noqa: F811
    state = SimpleNamespace(total_donated=have, level=2, evo_max=goal, evo_current=have,
                            power_current=1.0, power_max=10.0)
    monkeypatch.setattr("services.mech.progress_service.get_progress_service",
                        lambda: SimpleNamespace(get_state=lambda: state))
    service = MechResetService(config_dir=str(tmp_path))
    monkeypatch.setattr("services.mech.mech_reset_service.get_mech_reset_service", lambda: service)

    status = panel.test_client().get("/api/mech/status", headers=basic_auth()).get_json()["status"]

    assert status["next_level_threshold"] == round(goal * 100)
    assert status["amount_needed"] == needed
