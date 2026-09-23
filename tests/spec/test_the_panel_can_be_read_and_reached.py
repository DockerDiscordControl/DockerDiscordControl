# -*- coding: utf-8 -*-
"""The panel's controls can be read, and its help can be reached.

TWO FINDINGS from the design pass over the panel (2026-09-23), both measured
here rather than taken on trust.

ONE - the primary button fails its own contrast. `_base.html:126` sets
`.btn-primary { background-color: #4299e1 }` and Bootstrap puts white text on
it. That is **3.05 : 1**, computed below from the sRGB luminance rather than
quoted: WCAG wants 4.5 : 1 for normal text. Black on the same blue is 6.88 : 1.
This is the Save button, the group Save, the bulk Apply - the buttons the
operator uses most. It is not a matter of taste, it is a number, and the same
number is why `btn-outline-secondary` looked washed out on the group bar
earlier today.

TWO - 47 help tooltips cannot be reached from the keyboard. (The design pass
said 23; it counted only the ones carrying the `help-icon` class. Measured
here across every template, with the tooltip attribute as the marker, it is
47.) They are written
as `<i class="bi bi-question-circle help-icon" data-bs-toggle="tooltip"
title="...">` in _discord_settings, _channel_settings, _heartbeat_section,
_server_selection and _permissions_table. An `<i>` is not focusable and none
of them carries `tabindex`, so the text is mouse-only - `_base.html:151` even
styles them `cursor: help`. Everything those tooltips explain (what "Active"
means, what a channel permission does) is unreadable without a mouse.

WHY THE ICONS ALSO GET aria-hidden: Bootstrap Icons are private-use-area
glyphs in a webfont. A screen reader reading the element announces whatever
the font's codepoint maps to, which is nothing useful. The icon is decoration;
the title is the content.

HOW THIS TEST CAN FAIL: the contrast is computed from the colour in the
stylesheet, so changing the colour without changing the text colour is red.
The tooltip check reads every template for the tooltip pattern and requires
each one to be focusable.

COUNTER-CHECK (2026-09-23): red before - white on #4299e1 is 3.05, and 47 of
47 tooltip elements had no tabindex.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "app" / "templates"
BASE = TEMPLATES / "_base.html"

TOOLTIP = re.compile(r'<i[^>]*data-bs-toggle="tooltip"[^>]*>')


def _luminance(colour):
    """Relative luminance of #rrggbb, per WCAG 2.x."""
    channels = [int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
              for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(one, two):
    a, b = sorted((_luminance(one), _luminance(two)), reverse=True)
    return (a + 0.05) / (b + 0.05)


def test_the_contrast_maths_is_right():
    """Safeguard: a formula that answers the same for everything is green.

    Black on white is 21:1, white on white is 1:1 - the two ends of the scale.
    """
    assert round(_contrast("#000000", "#ffffff"), 1) == 21.0
    assert round(_contrast("#ffffff", "#ffffff"), 1) == 1.0


def test_the_primary_button_can_be_read():
    """THE FINDING: white on #4299e1 is 3.05:1, under the 4.5:1 a normal text
    needs. These are the buttons the operator presses most."""
    base = BASE.read_text(encoding="utf-8")
    rule = re.search(r"\.btn-primary\s*\{([^}]*)\}", base)

    assert rule, ".btn-primary is no longer styled here - re-read this test"
    background = re.search(r"background-color:\s*(#[0-9a-fA-F]{6})", rule.group(1))
    assert background, rule.group(1)

    colour = background.group(1)
    # A STANDALONE color:, not background-color: or border-color:. The first
    # version of this test matched border-color and reported the button as
    # #4299e1 on #4299e1, i.e. 1.00:1 - a wrong number, not a wrong verdict.
    text = re.search(r"(?<![-\w])color:\s*(#[0-9a-fA-F]{6})", rule.group(1))
    # No explicit colour means Bootstrap's white.
    foreground = text.group(1) if text else "#ffffff"

    ratio = _contrast(colour, foreground)
    assert ratio >= 4.5, (
        f"the primary button is {ratio:.2f}:1 ({foreground} on {colour}); "
        f"4.5:1 is the minimum for normal text")


def test_every_help_tooltip_can_be_focused():
    """THE FINDING: all 47 of them could not, so their text was mouse-only."""
    unreachable = []
    for path in sorted(TEMPLATES.rglob("*.html")):
        for tag in TOOLTIP.findall(path.read_text(encoding="utf-8")):
            if "tabindex" not in tag:
                unreachable.append(f"{path.name}: {tag[:70]}")

    assert unreachable == [], (
        f"{len(unreachable)} tooltip(s) cannot be reached from the keyboard, "
        f"so what they explain is mouse-only:\n  " + "\n  ".join(unreachable[:8]))


def test_the_scan_sees_the_tooltips():
    """Safeguard against a blunt tool: a scanner finding nothing is green."""
    found = sum(len(TOOLTIP.findall(p.read_text(encoding="utf-8")))
                for p in TEMPLATES.rglob("*.html"))

    assert found > 15, f"only {found} tooltips found - the pattern changed?"
