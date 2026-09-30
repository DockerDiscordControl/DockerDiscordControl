# -*- coding: utf-8 -*-
"""The first-time password setup lands in the action log field by field.

THE FINDING (stage 4 review before v3.1.0, section 32 pass 4): setup_save
called log_user_action("admin", "setup", "First-time password setup
completed") positionally, and the signature is (action, target, user,
source, details) - so the log read action=admin, target=setup,
user="First-time password setup completed", source=Unknown.

THE CONTRACT: action SETUP on the Web UI password, by admin, from the Web
UI, with the sentence as details.

HOW THIS TEST CAN FAIL: the sentence lands in the user field again.

COUNTER-CHECK (2026-09-30): red before the change (user holds the sentence).
"""

from unittest.mock import patch

from tests.spec.test_setup_stays_closed_when_the_config_cannot_be_read import (  # noqa: F401
    GOOD_PASSWORD, panel)


def test_the_entry_names_what_happened(panel):  # noqa: F811
    logged = []
    with patch("app.blueprints.main_routes.load_config", return_value={}), \
         patch("app.blueprints.main_routes.update_config_fields", return_value=True), \
         patch("app.blueprints.main_routes.log_user_action",
               side_effect=lambda *a, **k: logged.append((a, k))):
        answer = panel.test_client().post("/setup", data={"password": GOOD_PASSWORD,
                                                          "confirm_password": GOOD_PASSWORD})
    assert answer.get_json()["success"] is True
    assert logged == [((), {"action": "SETUP", "target": "Web UI password", "user": "admin",
                            "source": "Web UI",
                            "details": "First-time password setup completed"})]
