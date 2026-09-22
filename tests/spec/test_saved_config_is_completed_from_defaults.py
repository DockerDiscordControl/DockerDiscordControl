# -*- coding: utf-8 -*-
"""A saved spam protection configuration must fill missing keys from the
defaults - not silently fall back to 5 seconds.

NO ``@covers`` marker: that would be a new guarantee, and those are the
operator's decision. The BEHAVIOUR CHANGE has been decided:
"fill in the defaults".

THE FINDING. As soon as ``config/channels_config.json`` exists - in every real
installation -, ``get_config`` reads ONLY the saved keys (``from_dict`` takes
them over without completion). The default dictionaries
(``_get_default_config``) are then never read. Every missing key falls back in
``get_button_cooldown``/``get_command_cooldown`` to the fallback rule of
5 seconds. If the whole section is missing, EVERYTHING brakes with 5.

THE PANEL LIES MEANWHILE: GET /api/spam-protection returns only the saved
keys; for missing ones the fields keep their HTML start values. The operator
reads "Restart 15", "Logs 10" - the bot brakes with 5 until they save once.

MY OWN SHARE: since commit e87b170 the three info buttons ask for
``edit_info``/``protected_info``/``protected_info_edit`` instead of ``info``.
A configuration saved before that lacks these keys - there they have braked
with 5 instead of 3 ever since. The commit message said "unchanged"; that only
held for fresh installations.

TWO START VALUES IN THE PANEL also differed from the defaults (restart 15
instead of 20, live_refresh 3 instead of 5). With the completion, the panel
shows the default for missing keys; the start values only appear when loading
fails - they should then still show the same number.

SCOPE: saved values always win, unknown keys are kept as well. ``from_dict``
stays unchanged - it also builds the payload of the POST route, and nothing
should be made up there.
"""

import json
import re
from pathlib import Path

import pytest

from services.infrastructure.spam_protection_service import SpamProtectionService

TEMPLATE = Path(__file__).resolve().parents[2] / "app" / "templates" / "_spam_protection_modal.html"

SAVED = {
    "spam_protection": {
        "command_cooldowns": {"ping": 9},
        "button_cooldowns": {"restart": 7, "info": 3, "custom_button": 12},
        "global_settings": {"enabled": True},
    }
}


def _service(tmp_path, content=SAVED):
    service = SpamProtectionService(config_dir=str(tmp_path))
    service.config_file.write_text(json.dumps(content), encoding="utf-8")
    return service


def _defaults(tmp_path):
    return SpamProtectionService(config_dir=str(tmp_path / "empty"))._get_default_config()


def test_the_defaults_differ_from_the_fallback_rule(tmp_path):
    """Safeguard: only keys whose default is NOT 5 can show the finding. If one
    of them changes to 5, the test below would be hollow."""
    defaults = _defaults(tmp_path)
    assert defaults.button_cooldowns["edit_info"] == 3
    assert defaults.button_cooldowns["logs"] == 10
    assert defaults.button_cooldowns["mech_donate"] == 10
    assert defaults.command_cooldowns["serverstatus"] == 30


def test_saved_values_win(tmp_path):
    """Scope: the completion must not overwrite anything saved -
    not even when the default differs (restart: 20)."""
    service = _service(tmp_path)
    assert service.get_button_cooldown("restart") == 7
    assert service.get_command_cooldown("ping") == 9
    assert service.get_config().data.button_cooldowns["custom_button"] == 12


@pytest.mark.parametrize("name,expected", [
    ("edit_info", 3),            # my regression from e87b170
    ("protected_info", 3),
    ("protected_info_edit", 3),
    ("logs", 10),
    ("mech_donate_4711", 10),    # via the prefix logic
])
def test_missing_button_keys_come_from_the_defaults(tmp_path, name, expected):
    """THE FINDING: missing key -> fallback rule 5 instead of the default."""
    service = _service(tmp_path)
    assert service.get_button_cooldown(name) == expected, (
        f"{name!r} is missing from the saved configuration and brakes with "
        f"{service.get_button_cooldown(name)} instead of the default {expected}."
    )


def test_missing_command_keys_come_from_the_defaults(tmp_path):
    """THE FINDING, command side."""
    assert _service(tmp_path).get_command_cooldown("serverstatus") == 30


def test_without_the_section_the_defaults_apply(tmp_path):
    """THE FINDING, sharpest form: file present, section missing - today every
    button and every command then brakes with 5."""
    service = _service(tmp_path, {"channels": {}})
    assert service.get_button_cooldown("logs") == 10
    assert service.get_command_cooldown("serverstatus") == 30


def test_the_panel_gets_the_completed_values(tmp_path):
    """THE FINDING, display: get_config is the source of the GET route. If the
    key is missing there, the panel shows its HTML start value instead of the
    number it brakes by."""
    shown = _service(tmp_path).get_config().data.to_dict()["button_cooldowns"]
    assert shown.get("edit_info") == 3, sorted(shown)


def test_the_completion_does_not_change_the_defaults(tmp_path):
    """Scope: saved values must not leak back into the defaults."""
    service = _service(tmp_path)
    service.get_config()
    assert service._get_default_config().button_cooldowns["restart"] == 20


def test_panel_start_values_match_the_defaults(tmp_path):
    """The start values only appear when loading fails - then they should show
    the same number that is used for braking without a saved value."""
    fields = dict(re.findall(r'id="((?:button|cooldown)_[a-z_]+)" value="(\d+)"',
                             TEMPLATE.read_text(encoding="utf-8")))
    assert len(fields) >= 25, f"Only {len(fields)} fields found - pattern blind?"
    defaults = _defaults(tmp_path)
    differing = []
    for prefix, dictionary in (("button_", defaults.button_cooldowns),
                               ("cooldown_", defaults.command_cooldowns)):
        for field, value in fields.items():
            if field.startswith(prefix) and field[len(prefix):] in dictionary:
                if int(value) != dictionary[field[len(prefix):]]:
                    differing.append(f"{field}: Panel {value}, default {dictionary[field[len(prefix):]]}")
    assert not differing, differing
