# -*- coding: utf-8 -*-
"""One unusable number in the settings does not take every command down.

THE FINDING (review C64, section 20 F2): ``SpamProtectionConfig.from_dict``
calls ``int()`` on ``max_commands_per_minute`` and
``max_buttons_per_minute``. A value that is not a number - hand-edited, half
migrated, corrupted on disk - raises ``ValueError``. ``get_config()``'s
except clause named AttributeError, IOError, KeyError, OSError,
PermissionError, RuntimeError, TypeError and json.JSONDecodeError, but not
ValueError. (JSONDecodeError IS a ValueError, but naming the subclass does
not catch the parent.)

So the exception left ``get_config()`` and every caller with it:
``is_enabled``, ``get_command_cooldown``, ``get_button_cooldown``,
``is_on_cooldown``, ``get_remaining_cooldown``, ``add_user_cooldown`` - which
is every command and every button press that asks about spam protection.

``from_dict`` stays strict: it is also the validator behind the POST route in
main_routes, which turns its ValueError into a 400 for the operator. The READ
path is what degrades now.
"""

import json
import logging

import pytest

from services.infrastructure.spam_protection_service import (
    SpamProtectionConfig, SpamProtectionService)


def _write(config_dir, max_commands):
    (config_dir / "channels_config.json").write_text(json.dumps({
        "spam_protection": {
            "command_cooldowns": {"control": 11},
            "global_settings": {"enabled": True,
                                "max_commands_per_minute": max_commands},
        }
    }), encoding="utf-8")


@pytest.fixture
def service(tmp_path):
    return SpamProtectionService(config_dir=str(tmp_path))


def test_a_value_that_is_not_a_number_is_survived(service, tmp_path):
    _write(tmp_path, "sehr viele")

    result = service.get_config()

    assert result.success, (
        f"one unusable number and the whole spam protection is gone: {result.error}"
    )
    assert result.data.max_commands_per_minute == 20


def test_the_commands_keep_answering(service, tmp_path):
    """THE FINDING in the concrete: this is what every command press asks."""
    _write(tmp_path, "sehr viele")

    assert service.is_enabled() is True
    assert service.get_command_cooldown("control") == 11


def test_the_fallback_is_named_in_the_log(service, tmp_path, caplog):
    _write(tmp_path, "sehr viele")

    with caplog.at_level(logging.DEBUG):
        service.get_config()

    assert [r for r in caplog.records if r.levelno >= logging.ERROR], (
        "the panel's values are not in force and nothing says so"
    )


def test_a_sound_file_is_read_as_written(service, tmp_path):
    """Counter-check: always falling back to the defaults would pass above."""
    _write(tmp_path, 42)

    result = service.get_config()

    assert result.data.max_commands_per_minute == 42
    assert result.data.command_cooldowns["control"] == 11


def test_the_form_validator_still_refuses_the_value():
    """Counter-check: from_dict is the POST route's validator, and a form
    value that is not a number must still be refused with a 400 instead of
    being saved as a default."""
    with pytest.raises(ValueError):
        SpamProtectionConfig.from_dict(
            {"global_settings": {"max_commands_per_minute": "sehr viele"}})
