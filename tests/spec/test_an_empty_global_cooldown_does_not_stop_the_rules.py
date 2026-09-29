# -*- coding: utf-8 -*-
"""An empty "Global cooldown" field neither saves nor stops the message rules.

THE FINDING (stage 4 review before v3.1.0, section 10 pass 4 F14, verified
2026-09-29 in a corrected form). Clearing the panel's "Global cooldown"
number field sends parseInt('') = NaN, i.e. JSON null.
update_global_settings merged it unchecked and answered success. From then
on every matching message rule with target containers raised TypeError in
acquire_execution_locks ('<' between float and None) - logged and
swallowed by the caller: message automation stopped while the panel had
said "saved". A string "30" from the API did the same.

THE CONTRACT: a global cooldown that is not a whole number of seconds >= 0
is refused at saving time; and one already stored (a file written before
this check) does not stop a rule - the default applies.

HOW THIS TEST CAN FAIL: the value is stored unchecked again, or the
execution path reads it raw.

COUNTER-CHECK (2026-09-29): written before the fix and red then.
"""

import pytest

VALID = {"enabled": True, "protected_containers": [], "alert_webhook_url": "",
         "alert_webhook_mode": "fallback"}


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    from services.automation import auto_action_config_service as module
    monkeypatch.setattr(module, "_config_service_instance", None, raising=False)
    return module.AutoActionConfigService()


@pytest.mark.parametrize("value", [None, "30", -5, 2.5, True])
def test_a_bad_cooldown_is_refused(service, value):
    result = service.update_global_settings({**VALID, "global_cooldown_seconds": value})

    assert not result.success, f"{value!r} was saved as the global cooldown"
    assert service.get_global_settings().get("global_cooldown_seconds") == 30


def test_a_whole_number_is_saved(service):
    """Counter-check: an ordinary value still goes through."""
    result = service.update_global_settings({**VALID, "global_cooldown_seconds": 45})

    assert result.success
    assert service.get_global_settings()["global_cooldown_seconds"] == 45


def test_a_stored_null_does_not_stop_a_rule():
    """A file written before the check: the rule still gets a number."""
    from services.automation.automation_service import global_cooldown_of

    assert global_cooldown_of({"global_cooldown_seconds": None}) == 30
    assert global_cooldown_of({"global_cooldown_seconds": "x"}) == 30
    assert global_cooldown_of({"global_cooldown_seconds": 12}) == 12
    assert global_cooldown_of({}) == 30
