# -*- coding: utf-8 -*-
"""A channel's update interval and inactivity timeout are whole minutes, at least one.

THE FINDING (stage 4 review before v3.1.0, section 12 pass 4 F10): both
fields were parsed with a bare int(). The panel's number fields allow
"1.5", "0" and "-5" and post them unchecked: "1.5" aborted the WHOLE save
with Python's raw "invalid literal for int() with base 10", and 0 or a
negative value was stored as it came - and used raw in places.

THE CONTRACT: a decimal is rounded down, anything below one becomes one,
anything unreadable falls back to the default; the save goes through.

HOW THIS TEST CAN FAIL: "1.5" aborts the save again, or 0 is stored.

COUNTER-CHECK (2026-09-30): red before the change.
"""

from services.config.config_form_parser_service import ConfigFormParserService

CHANNEL = "123456789012345678"


def test_odd_minutes_are_made_whole_and_positive():
    form = {"channel_tables_submitted": "1", "status_channel_id_1": CHANNEL,
            "status_channel_name_1": "s", "status_update_interval_minutes_1": "1.5",
            "status_inactivity_timeout_1": "0"}
    channels = ConfigFormParserService.parse_channel_permissions_from_form(form)
    assert channels[CHANNEL]["update_interval_minutes"] == 1
    assert channels[CHANNEL]["inactivity_timeout_minutes"] == 1


def test_a_negative_value_is_not_stored():
    form = {"channel_tables_submitted": "1", "status_channel_id_1": CHANNEL,
            "status_channel_name_1": "s", "status_update_interval_minutes_1": "-5",
            "status_inactivity_timeout_1": "30"}
    channel = ConfigFormParserService.parse_channel_permissions_from_form(form)[CHANNEL]
    assert channel["update_interval_minutes"] == 1 and channel["inactivity_timeout_minutes"] == 30
