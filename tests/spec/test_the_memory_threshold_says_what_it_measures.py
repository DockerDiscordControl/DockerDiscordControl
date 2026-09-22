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

COUNTER-CHECK (2026-09-22): red before - the modal had no hint next to the
memory threshold, and the CPU threshold next to it still has none (it needs
none: CPU percent is of one core-equivalent, as everywhere else).
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODAL = (ROOT / "app" / "templates" / "_auto_actions_modal.html").read_text(encoding="utf-8")
LOCALE = ROOT / "locales"


def _field_block(field_id):
    position = MODAL.index(f'id="{field_id}"')
    start = MODAL.rindex('<div class="col-md-4', 0, position)
    end = MODAL.index("</div>", position)
    return MODAL[start:end]


def test_the_memory_field_carries_the_hint():
    block = _field_block("aasRuleMemoryThreshold")
    assert "web.aas.memory_threshold_hint" in block, block


@pytest.mark.parametrize("language", ["en", "de"])
def test_the_hint_names_the_limit_and_the_missing_limit(language):
    import json

    catalogue = json.loads((LOCALE / f"{language}.json").read_text(encoding="utf-8"))
    hint = catalogue["web.aas.memory_threshold_hint"].lower()
    assert "limit" in hint
    assert "--memory" in hint or "ram" in hint


def test_the_changelog_says_it_too():
    changelog = (ROOT / "docs" / "CHANGELOG.md").read_text(encoding="utf-8")
    unreleased = changelog.split("## v2.4.1")[0]
    assert "memory_stats.limit" in unreleased or "container's memory limit" in unreleased
