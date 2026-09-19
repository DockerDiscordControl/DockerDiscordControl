# -*- coding: utf-8 -*-
"""The default values of the spam brake must not contradict each other.

NO ``@covers`` marker: that would be a new guarantee, and those are the
operator's decision.

THE FINDING (stage 4, follow-up to the spam brake).

For the per-minute button limit there are THREE places that name a default
value, and they do not agree::

    SpamProtectionConfig.from_dict          :41   -> 30
    SpamProtectionService._get_default_config :315 -> 35
    app/templates/_spam_protection_modal.html :51  -> 30

For the COMMAND limit the same three places agree on 20 (:40, :314, template
:46). So the contradiction affects exactly one field - measured, not assumed.

WHAT THE OPERATOR SEES OF IT: which number applies depends on whether
``config/channels_config.json`` exists. If the file is missing,
``get_config:103-106`` goes via ``_get_default_config`` -> 35. If it exists, it
goes via ``from_dict`` -> 30. Meanwhile the panel dialog shows 30 (``:51``)
until the values are overwritten by the fetch (``:185-186``). The operator
reads a number in the panel that is not the one used for braking.

SCOPE - what this test EXPLICITLY DOES NOT do: it raises nothing. The operator
has decided that the panel determines what applies; here only the
contradiction is removed. The majority of the places (2 to 1) and the panel
say 30, so 30 applies. Anyone who wants to change the value keeps doing so in
the panel.

NOT PART OF THIS FINDING, but checked during the measurement and recorded here
so nobody has to investigate it twice:

* ``from_dict({})`` returns EMPTY cooldown dictionaries, while
  ``_get_default_config`` returns 14 command and 15 button entries. That is
  NOT a loss of protection: ``get_button_cooldown:186`` and
  ``get_command_cooldown:166`` have a fallback rule of 5 seconds. Only the
  gradation is lost.
* This empty path is NOT reachable in production. ``channels_config.json``
  does not exist on the production instance (measured 2026-09-18); the only
  writer is ``save_config:139``, and it always writes the section too.
  The migration does create the file at ``config_migration_service.py:381``,
  but deletes it again at ``:394`` via
  ``cleanup_legacy_files_after_migration:141-149``. The loader
  (``config_loader_service.py:419``) provides ``config['spam_protection']``,
  but nobody builds a ``SpamProtectionConfig`` from it - the only readers are
  ``config_validation_service.py:145,198``.

HOW IT IS CHECKED HERE: via the three sources themselves. The service is built
with ``tmp_path`` - ``__init__:87`` creates its directory, and that must never
be the real ``config/``. ``_get_default_config`` reads no file, so the access
is pure.
"""

import re
from pathlib import Path

import pytest

from services.infrastructure.spam_protection_service import (
    SpamProtectionConfig,
    SpamProtectionService,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = PROJECT_ROOT / "app" / "templates" / "_spam_protection_modal.html"


def _value_from_template(field_id: str) -> int:
    """Reads the ``value`` attribute of the input field with this id.

    Deliberately narrow: it looks for the line WITH the id, and takes the
    ``value`` from it. A pattern over the whole file could catch the
    neighbouring field - exactly the way a red for the wrong reason would
    arise.
    """
    text = TEMPLATE.read_text(encoding="utf-8")
    for line in text.splitlines():
        if f'id="{field_id}"' in line:
            match = re.search(r'value="(\d+)"', line)
            if match:
                return int(match.group(1))
            raise AssertionError(
                f"Field {field_id} found, but without a numeric value: {line.strip()!r}"
            )
    raise AssertionError(f"Field {field_id} not found in {TEMPLATE.name}.")


def test_the_template_is_readable_and_names_both_fields():
    """Guard against a blunt tool.

    Must be green BEFORE and AFTER the fix. If it were red, the test below
    would not check the contradiction but only its own file search - a
    worthless red.
    """
    assert TEMPLATE.is_file(), (
        f"{TEMPLATE} is missing - then the test below does not measure the template at all."
    )
    assert _value_from_template("maxCommandsPerMinute") > 0
    assert _value_from_template("maxButtonsPerMinute") > 0


def test_command_limit_is_equal_in_all_three_places():
    """Scope: this already agrees, and it must stay that way.

    Without this test, a fix to the button limit could drag the command limit
    along without anything firing.
    """
    value_from_dict = SpamProtectionConfig.from_dict({}).max_commands_per_minute
    value_from_template = _value_from_template("maxCommandsPerMinute")

    assert value_from_dict == 20
    assert value_from_template == 20


def test_command_limit_also_equal_in_the_service(tmp_path):
    """The same scope check for the third path, the service."""
    service = SpamProtectionService(config_dir=str(tmp_path))

    assert service._get_default_config().max_commands_per_minute == 20


def test_button_limit_is_equal_in_all_three_places(tmp_path):
    """THE FINDING: three defaults for one field, and one deviates.

    The numbers are EXPLICITLY pinned, not just checked for equality.
    Otherwise the test would also be green if someone set all three places to
    35 - and that would be a value increase which the operator explicitly
    reserved for the panel.
    """
    service = SpamProtectionService(config_dir=str(tmp_path))

    value_from_dict = SpamProtectionConfig.from_dict({}).max_buttons_per_minute
    value_from_service = service._get_default_config().max_buttons_per_minute
    value_from_template = _value_from_template("maxButtonsPerMinute")

    assert value_from_dict == 30, "from_dict (:41) no longer says 30."
    assert value_from_template == 30, "The template (:51) no longer says 30."
    assert value_from_service == 30, (
        "_get_default_config (:315) says "
        f"{value_from_service} instead of 30. So the effective button limit depends "
        "on whether config/channels_config.json exists: if it is missing, the "
        "service brakes by this number (get_config:103-106); if it exists, by "
        "the one from from_dict. Meanwhile the panel shows 30. The operator reads "
        "a different number than the one used for braking."
    )
