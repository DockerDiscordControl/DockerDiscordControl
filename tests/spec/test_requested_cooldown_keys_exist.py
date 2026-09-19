# -*- coding: utf-8 -*-
"""Every cooldown key that live code requests must also exist.

NO ``@covers`` marker: that would be a new guarantee, and those are the
operator's decision.

THE FINDING. Three keys are requested by live code but are in NO default
dictionary and have NO field in the panel::

    "admin"        cogs/control_ui.py            AdminButton
    "tasks"        cogs/status_info_integration.py  TaskManagementButton
    "task_delete"  cogs/control_ui.py            TaskDeleteButton

``get_button_cooldown:186`` returns the fallback rule of 5 seconds for unknown
names. So the three buttons do brake - but with a value the operator can
neither see nor change anywhere.

TWO STAGES, BOTH NECESSARY - measured, not assumed: a key in the defaults
alone is NOT enough. The panel's save block
(``_spam_protection_modal.html:229-243``) writes a complete replacement object
from a FIXED enumeration, and ``save_config:139`` stores it unchanged. A key
without a field would therefore disappear again on the first save and fall
back to the 5 seconds. That is why the tests below check defaults AND panel
AND save block separately.

NO VALUE INCREASE: the three get the default **5** - exactly what applies
today via the fallback rule. The key thus becomes visible and adjustable, the
behaviour stays unchanged. Raising it is the operator's decision in the panel.

THE LIMIT OF THIS TEST, stated explicitly so that it does not promise more
than it delivers: the scanner only finds STRING arguments. Calls with
``self.custom_id`` (the mech buttons), ``self.action`` (start/stop/restart),
``action_type`` (service-internal) and ``command_name`` (slash commands) are
invisible to it. So it checks the literal calls - not all of them.

THE CONTRACT ONLY HOLDS IN ONE DIRECTION. Keys that are in the defaults
without anyone requesting them (``auto_refresh``, ``mech_music`` and others)
do NOT turn this red. Those are separate findings with a separate decision by
the operator - this test does not pre-empt them.

``refresh`` WAS EXEMPTED from the two panel assertions as long as the
operator question from SPEC.md B10 was open. It was decided on 2026-09-19
("refresh into the panel"); the exemption has therefore been dropped.

HOW IT IS CHECKED HERE: expectation and assertion come from different
sources. The **expectation** is the source code under cogs/, services/, app/.
The **assertion** is the default dictionary and the panel template. Taking
both from the same file would make it a mirror test.
"""

import re
from pathlib import Path

import pytest

from services.infrastructure.spam_protection_service import SpamProtectionService

PROJECT = Path(__file__).resolve().parents[2]
TEMPLATE = PROJECT / "app" / "templates" / "_spam_protection_modal.html"
DIRECTORIES = ("cogs", "services", "app")

# The four call families that take a BUTTON key.
# get_command_cooldown is deliberately missing: it is only ever called with a
# variable (docker_control.py), so it has no literal to offer.
PATTERNS = (
    re.compile(r'get_button_cooldown\(\s*"([a-z_]+)"\s*\)'),
    re.compile(r'is_on_cooldown\([^,]+,\s*"([a-z_]+)"\s*\)'),
    re.compile(r'add_user_cooldown\([^,]+,\s*"([a-z_]+)"\s*\)'),
)

# See the header: SPEC.md B10, decided 2026-09-19 - no exemption any more.
WITHOUT_PANEL_FIELD_DECIDED = set()


def _requested_keys() -> dict:
    """What the source code literally requests: {key: [location, ...]}."""
    found = {}
    for directory in DIRECTORIES:
        for path in sorted((PROJECT / directory).rglob("*.py")):
            text = path.read_text(encoding="utf-8", errors="replace")
            for line_no, line in enumerate(text.splitlines(), 1):
                for pattern in PATTERNS:
                    for key in pattern.findall(line):
                        location = f"{path.relative_to(PROJECT)}:{line_no}"
                        found.setdefault(key, []).append(location)
    return found


def _defaults(tmp_path) -> dict:
    return SpamProtectionService(config_dir=str(tmp_path))._get_default_config().button_cooldowns


def _template_text() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


def _save_block() -> str:
    """Only the button_cooldowns section of the save block.

    Narrowly delimited: a name can appear elsewhere in the file (as a field, as
    a label) and still be missing when saving - exactly the measured failure
    case. The search must therefore target this section.
    """
    text = _template_text()
    start = text.index("button_cooldowns: {")
    return text[start:text.index("}", start)]


def test_the_scanner_finds_anything_at_all():
    """Safeguard against a blunt tool - must be green BEFORE and AFTER.

    If the scanner reaches into nothing - pattern changed, path wrong -, the
    tests below would be green without proving anything.
    """
    found = _requested_keys()

    assert len(found) >= 6, (
        f"Only {len(found)} literal keys found: {sorted(found)}. "
        "The call pattern has changed - then the tests below check nothing."
    )
    for known in ("info", "logs"):
        assert known in found, (
            f"The known key {known!r} is missing from the scan - the scanner is blind."
        )


def test_the_defaults_are_filled_at_all(tmp_path):
    """Second safeguard: am I really reading the button dictionary?"""
    defaults = _defaults(tmp_path)

    assert len(defaults) >= 10, (
        f"Only {len(defaults)} button defaults read: {sorted(defaults)}. "
        "Then the assertion below points at the wrong dictionary."
    )
    assert defaults.get("info") == 3


def test_every_requested_key_is_in_the_defaults(tmp_path):
    """THE FINDING, first stage: requested but not present."""
    found = _requested_keys()
    defaults = _defaults(tmp_path)

    missing = {k: v for k, v in found.items() if k not in defaults}

    assert not missing, (
        "These keys are requested by live code but are in no default "
        "dictionary. get_button_cooldown:186 silently returns 5 seconds for "
        "them, and the operator can neither see nor change the value "
        "anywhere:\n  "
        + "\n  ".join(f"{k!r} -> {', '.join(v)}" for k, v in sorted(missing.items()))
    )


def test_every_requested_key_has_a_panel_field(tmp_path):
    """THE FINDING, second stage: present but not adjustable in the panel."""
    found = set(_requested_keys()) - WITHOUT_PANEL_FIELD_DECIDED
    text = _template_text()

    without_field = sorted(k for k in found if f'id="button_{k}"' not in text)

    assert not without_field, (
        "These requested keys have no input field in the panel and "
        f"are therefore not adjustable: {without_field}"
    )


def test_every_requested_key_survives_saving(tmp_path):
    """THE FINDING, third stage - and the one nobody sees without measuring.

    The save block is a FIXED enumeration. Whatever is missing there drops out
    of the configuration on the first save, even if default and field exist.
    Without this assertion a fix would be green and still be ineffective after
    the first click on "Save".
    """
    found = set(_requested_keys()) - WITHOUT_PANEL_FIELD_DECIDED
    block = _save_block()

    lost = sorted(k for k in found if f"button_{k}" not in block)

    assert not lost, (
        "These keys are missing from the panel's save block "
        "(_spam_protection_modal.html). A value set in the panel is "
        "never saved; since 1b77428 the default applies afterwards (before, the "
        f"5-second fallback rule): {lost}"
    )
