# -*- coding: utf-8 -*-
"""The diagnostics dialog puts what the server reports on the page as text.

THE FINDING (audit 2026-09-26): panel.js built the diagnostics report as one
HTML string for innerHTML and interpolated the container name, platform,
sizes, port mappings, issues, solutions and recommendations raw. None of it
comes from a user today - the host and Docker supply it - so this is
hardening, not a live hole. But a container name is chosen by whoever creates
the container, and the report's sentences are free text; one "<" would be
markup. Every other list in the panel escapes; this one did not.

THE CONTRACT: inside the report builder, every ${...} is either escaped with
ddcEscapeHtml or a choice between fixed strings (a ternary).

HOW THIS TEST CAN FAIL: a raw interpolation comes back into the builder.

COUNTER-CHECK (2026-09-26): red before the fix - fourteen raw interpolations,
container name to recommendation.
"""

import re
from pathlib import Path

PANEL = (Path(__file__).resolve().parents[2] / "app" / "static" / "js" / "panel.js").read_text(
    encoding="utf-8")


def _builder():
    start = PANEL.index("// Build diagnostic report HTML")
    end = PANEL.index("diagnosticsModalContent.innerHTML = html;", start)
    return PANEL[start:end]


def _interpolations(text):
    """Top-level ${...} of the builder, nested braces followed."""
    found, i = [], 0
    while True:
        i = text.find("${", i)
        if i == -1:
            return found
        depth, j = 1, i + 2
        while depth:
            depth += {"{": 1, "}": -1}.get(text[j], 0)
            j += 1
        found.append(text[i + 2:j - 1].strip())
        i = j


def test_every_value_is_escaped_or_fixed():
    raw = [expression for expression in _interpolations(_builder())
           if not expression.startswith("ddcEscapeHtml(") and "?" not in expression]

    assert raw == [], f"raw values go into innerHTML: {raw}"


def test_the_builder_is_where_it_was_looked_for():
    """Counter-case: a builder that moved would make the scan above vacuous."""
    assert len(_interpolations(_builder())) >= 10
