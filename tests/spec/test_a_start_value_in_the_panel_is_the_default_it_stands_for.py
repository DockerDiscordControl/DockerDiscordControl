# -*- coding: utf-8 -*-
"""A number written into the markup must be the default Python brakes by.

WHERE THIS COMES FROM. test_saved_config_is_completed_from_defaults.py found
two start values in _spam_protection_modal.html that disagreed with the service
they stand for - restart showed 15 where the default was 20, live_refresh 3
where it was 5. The field is only shown when the load fails, so the operator
read a number the bot never used, and no test could have caught it, because
the number exists twice: once in Python and once in the page.

That test then guarded ONE template, and inside it only the fields whose id
starts with ``button_`` or ``cooldown_``. Measured today (2026-09-24) the panel
has 41 such numbers in THREE templates (44 before three dead cooldown
sliders left on 2026-09-25), and the guard covers 32 of them:

    _spam_protection_modal.html      32   30 guarded by the prefix rule,
                                          maxCommandsPerMinute and
                                          maxButtonsPerMinute fall through it
    _auto_actions_modal.html         10   none
    _language_timezone_settings.html  2   none

ALL 44 AGREE TODAY - this file found no defect, and says so. What it changes is
that the agreement is now held. A default moved in Python and forgotten in the
page is invisible until an operator loads a broken form and believes the number
they are shown.

THE SWEEP IS PART OF THE CHECK. The table below must name every field the sweep
finds: a new number added to a settings form with nothing to compare it to
fails here rather than being skipped, which is exactly how the two fields above
slipped past a guard that had been written for its neighbours.

HOW THIS TEST CAN FAIL: a default changed on one side only, or a new hard-coded
number in a settings form.

COUNTER-CHECK (2026-09-24): green from the start - the drift it guards is not
present, so the only proof it bites is sabotage on that green baseline. Three,
one per half of the rule: a default moved in Python (cpu_threshold_percent
90 -> 80, 1 case red), a start value moved in the markup (ctRateLimit 60 -> 55,
1 case red), and a new number field added with nothing to compare it to (1 case
red). A FOURTH ATTEMPT PROVED NOTHING and is recorded because of it: the first
markup sabotage edited a pattern that did not match the file, the file did not
change, and the suite stayed green - which reads exactly like a test that does
not bite.
"""

import dataclasses
import re
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[2]
TEMPLATES = PROJECT / "app" / "templates"

# Only number fields carry a value that means a quantity; a checkbox's
# value="1" is what it submits when ticked, not a start value.
FIELD = re.compile(r'<input\b[^>]*type="number"[^>]*>', re.S)


def _hard_coded_start_values():
    """Every number input in every template whose value is a literal.

    A value written as {{ ... }} comes from the server and is not a second
    copy of anything, so it is not in scope.
    """
    found = {}
    for path in sorted(TEMPLATES.rglob("*.html")):
        for tag in FIELD.findall(path.read_text(encoding="utf-8")):
            key = re.search(r'id="([^"{}]+)"', tag) or re.search(r'name="([^"{}]+)"', tag)
            value = re.search(r'value="([^"{}]*)"', tag)
            if not (key and value):
                continue
            text = value.group(1).strip()
            if not re.fullmatch(r"-?\d+(\.\d+)?", text):
                continue
            found[key.group(1)] = (path.name, float(text))
    return found


def _field_default(cls, name):
    """The default of one dataclass field, read from the class itself."""
    for field in dataclasses.fields(cls):
        if field.name == name:
            assert field.default is not dataclasses.MISSING, (
                f"{cls.__name__}.{name} has no default to compare against")
            return field.default
    raise AssertionError(f"{cls.__name__} has no field {name!r}")


def _spam_defaults(tmp_path):
    """An empty directory, so the defaults are the ones a fresh install has."""
    from services.infrastructure.spam_protection_service import SpamProtectionService

    return SpamProtectionService(config_dir=str(tmp_path / "empty"))._get_default_config()


def _automation_defaults():
    from services.automation.auto_action_config_service import (ActionConfig,
                                                                AutoActionRule,
                                                                TriggerConfig)

    return {
        "aasRulePriority": _field_default(AutoActionRule, "priority"),
        "aasRuleCooldown": _field_default(AutoActionRule, "cooldown_minutes"),
        "aasRuleDelay": _field_default(ActionConfig, "delay_seconds"),
        "aasRuleRestartThreshold": _field_default(TriggerConfig, "restart_threshold"),
        "aasRuleRestartWindow": _field_default(TriggerConfig, "restart_window_minutes"),
        "aasRuleCpuThreshold": _field_default(TriggerConfig, "cpu_threshold_percent"),
        "aasRuleMemoryThreshold": _field_default(TriggerConfig, "memory_threshold_percent"),
        "aasRuleMemoryThresholdMb": _field_default(TriggerConfig, "memory_threshold_mb"),
        "aasRuleResourceMinutes": _field_default(TriggerConfig, "resource_minutes"),
    }


def _translation_defaults():
    from services.translation.translation_config_service import TranslationSettings

    return {
        "ctRateLimit": _field_default(TranslationSettings, "rate_limit_per_minute"),
        "ctMaxTextLength": _field_default(TranslationSettings, "max_text_length"),
    }


def _global_cooldown_default(tmp_path, monkeypatch):
    """Not a dataclass: the service writes a default document when it finds no
    file, and falls back to a literal dictionary when the document has no
    section. Both spell the number, so it is read the way the bot reads it -
    from a service pointed at an empty directory, via DDC_CONFIG_DIR, which is
    the only way this one can be told where to look."""
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    from services.automation.auto_action_config_service import AutoActionConfigService

    return AutoActionConfigService().get_global_settings()["global_cooldown_seconds"]


def _expected(tmp_path, monkeypatch):
    """Field id -> the number Python uses when nothing is saved."""
    spam = _spam_defaults(tmp_path)
    pairs = {"maxCommandsPerMinute": spam.max_commands_per_minute,
             "maxButtonsPerMinute": spam.max_buttons_per_minute,
             "aasGlobalCooldown": _global_cooldown_default(tmp_path, monkeypatch)}
    pairs.update(_automation_defaults())
    pairs.update(_translation_defaults())
    for field, value in spam.command_cooldowns.items():
        pairs[f"cooldown_{field}"] = value
    for field, value in spam.button_cooldowns.items():
        pairs[f"button_{field}"] = value
    return pairs


def test_the_sweep_still_finds_the_fields():
    """Safeguard: a pattern that matches nothing would make every case below
    pass without comparing anything - which is how the first scan for this
    missed 32 fields, by insisting on a name= these inputs do not have."""
    found = _hard_coded_start_values()

    # 44 until 2026-09-25, when three cooldown sliders whose buttons no
    # longer exist were removed from the panel
    # (tests/spec/test_no_cooldown_slider_steers_nothing.py).
    assert len(found) >= 41, f"only {len(found)} start values found - pattern blind?"
    by_template = {}
    for template, _value in found.values():
        by_template[template] = by_template.get(template, 0) + 1

    assert len(by_template) >= 3, by_template


def test_every_start_value_has_something_to_be_compared_with(tmp_path, monkeypatch):
    """THE PART THAT GROWS WITH THE CODE. A number added to a settings form
    with no entry here is not silently skipped."""
    unmapped = sorted(set(_hard_coded_start_values()) - set(_expected(tmp_path, monkeypatch)))

    assert unmapped == [], (
        "these start values are guarded by nothing - add the default they "
        f"stand for to _expected(): {unmapped}")


def test_no_table_entry_points_at_a_field_that_is_gone(tmp_path, monkeypatch):
    """The other direction: an entry left behind after a field was removed
    guards nothing and reads as if it did."""
    found = _hard_coded_start_values()
    # The spam defaults carry keys the panel has no field for on purpose -
    # a cooldown can apply to a button that is built at runtime. Only the
    # explicitly listed ids must still exist.
    explicit = set(_automation_defaults()) | set(_translation_defaults()) | {
        "maxCommandsPerMinute", "maxButtonsPerMinute", "aasGlobalCooldown"}
    gone = sorted(explicit - set(found))

    assert gone == [], f"these entries name a field the panel no longer has: {gone}"


def test_each_start_value_is_its_default(tmp_path, monkeypatch):
    """THE RULE: the number the operator reads in a form that failed to load
    is the number the bot would have used."""
    expected = _expected(tmp_path, monkeypatch)
    differing = []
    for field, (template, shown) in sorted(_hard_coded_start_values().items()):
        if field not in expected:
            continue
        if float(shown) != float(expected[field]):
            differing.append(f"{template}#{field}: panel {shown:g}, "
                             f"default {expected[field]}")

    assert differing == [], (
        "these numbers exist twice and disagree:\n  " + "\n  ".join(differing))


@pytest.mark.parametrize("template", ["_spam_protection_modal.html",
                                      "_auto_actions_modal.html",
                                      "_language_timezone_settings.html"])
def test_each_known_template_is_still_covered(template):
    """Named rather than swept, so a template losing all of its start values -
    or being renamed - is noticed instead of quietly dropping out of the
    check."""
    templates = {name for name, _ in _hard_coded_start_values().values()}

    assert template in templates, f"{template} no longer has a start value"
