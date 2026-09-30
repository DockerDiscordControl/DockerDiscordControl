# -*- coding: utf-8 -*-
"""A stored cooldown or minute limit that is unusable does not break a button.

THE FINDING (stage 4 review before v3.1.0, section 20, pass 3 F2 and pass 4
F4): the read path repaired only a global limit that was not a number. A
per-button or per-command cooldown that is not one ("abc" from a
hand-edited channels_config.json, or a request sent before the 2026-09-26
validation) went through, and is_on_cooldown raised TypeError on every
press of that button - the callers catch no TypeError, so Discord said
"This interaction failed". And a stored per-minute limit of 0, which the
panel could save before 2689eade, stayed in force: every press after the
first in a minute was refused.

THE CONTRACT: on read, a cooldown that is not a whole number of seconds in
COOLDOWN_RANGE and a minute limit outside PER_MINUTE_RANGE are dropped
with an error in the log; the default applies for that key. The other
stored values stay.

HOW THIS TEST CAN FAIL: the press raises again, the 0 limit refuses again,
or a good neighbouring value is thrown away with the bad one.

COUNTER-CHECK (2026-09-30): red before the change (TypeError; refused press).
"""

import json
import time

import pytest

from services.infrastructure.spam_protection_service import SpamProtectionService

USER = 4411


@pytest.fixture
def stored(tmp_path, monkeypatch):
    monkeypatch.setattr(time, "monotonic", lambda: 50_000.0)

    def write(spam):
        (tmp_path / "channels_config.json").write_text(json.dumps({"spam_protection": spam}),
                                                       encoding="utf-8")
        return SpamProtectionService(config_dir=str(tmp_path))
    return write


@pytest.mark.parametrize("bad", ["abc", True, -5, 10 ** 9, 2.5, None])
def test_a_bad_button_cooldown_reads_as_the_default(stored, bad):
    service = stored({"button_cooldowns": {"info": bad, "logs": 42}})
    assert service.is_on_cooldown(USER, "info") is False
    assert service.get_button_cooldown("info") == 3, "the default for info"
    assert service.get_button_cooldown("logs") == 42, "the good neighbour was thrown away"


def test_a_bad_command_cooldown_reads_as_the_default(stored):
    service = stored({"command_cooldowns": {"ping": "abc", "help": 7}})
    assert service.is_on_cooldown(USER, "ping", kind="command") is False
    assert service.get_command_cooldown("ping") == 3
    assert service.get_command_cooldown("help") == 7


@pytest.mark.parametrize("bad", [0, -1, 101, "abc"])
def test_a_minute_limit_outside_the_range_reads_as_the_default(stored, bad):
    service = stored({"global_settings": {"max_buttons_per_minute": bad, "max_commands_per_minute": 12}})
    service.add_user_cooldown(USER, "start")
    assert service.is_on_cooldown(USER, "stop") is False, "the second press in the minute was refused"
    config = service.get_config().data
    assert (config.max_buttons_per_minute, config.max_commands_per_minute) == (30, 12)
