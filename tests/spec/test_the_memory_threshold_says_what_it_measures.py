# -*- coding: utf-8 -*-
"""The memory threshold says what the percentage is of.

THE FINDING: "Memory threshold (%)" in the rule editor is a percentage of the
container's memory LIMIT, which is what Docker's memory_stats.limit reports.
A container started without --memory has no limit, so Docker reports the
host's total RAM and the percentage is of that: a 90 % rule on a 64 GB host
fires at 57 GB and never at all in practice. The operator reads it as
"90 % of what this container normally uses".

The field now carries that sentence, and so does the roadmap's changelog
entry. Nothing about the measurement changes - it is the only number Docker
gives.

REVISITED 2026-09-23: the hint used to sit inside the percentage field's own
column and it now sits on a full-width line under the memory fields, because
there are two of them. The operator decision that day gave the rule a second
threshold in MB, for the containers that have no limit - so the hint no longer
describes one field, it describes which of the two applies. The sentence it
must carry changed with it: not "the percentage is of the host's RAM", but
"the percentage is for containers with a limit, the MB value for the others".
See test_a_container_without_a_memory_limit_can_be_watched.py.

COUNTER-CHECK (2026-09-22): red before - the modal had no hint next to the
memory threshold, and the CPU threshold next to it still has none (it needs
none: CPU percent is of one core-equivalent, as everywhere else).
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODAL = (ROOT / "app" / "templates" / "_auto_actions_modal.html").read_text(encoding="utf-8")
LOCALE = ROOT / "locales"


def test_the_hint_sits_with_the_memory_fields():
    """It is one line for the pair now, so it has to follow both of them and
    still come before the block's own closing hint."""
    percent = MODAL.index('id="aasRuleMemoryThreshold"')
    megabytes = MODAL.index('id="aasRuleMemoryThresholdMb"')
    hint = MODAL.index("web.aas.memory_threshold_hint")

    assert percent < megabytes < hint
    assert hint < MODAL.index("web.aas.container_state_hint")


@pytest.mark.parametrize("language", ["en", "de"])
def test_the_hint_names_the_limit_and_the_missing_limit(language):
    import json

    catalogue = json.loads((LOCALE / f"{language}.json").read_text(encoding="utf-8"))
    hint = catalogue["web.aas.memory_threshold_hint"].lower()
    assert "limit" in hint
    assert "--memory" in hint
    assert "mb" in hint, "the hint has to name the other yardstick too"


def test_the_changelog_says_it_too():
    changelog = (ROOT / "docs" / "CHANGELOG.md").read_text(encoding="utf-8")
    unreleased = changelog.split("## v2.4.1")[0]
    assert "memory_stats.limit" in unreleased or "container's memory limit" in unreleased
