# -*- coding: utf-8 -*-
"""A label that wraps does not push its input field out of line.

THE FINDING (operator, 2026-09-22, screenshot of the German panel): in the
web-UI authentication row the middle label - "new password (leave empty to
keep the current one)" - needs two lines, and its input field sat a line lower
than the two beside it. Columns align their content at the top, so the longest
label decides where its own field lands. It happens in any language whose
label is longer than the column, so shortening one translation would not fix
it: the longest of the forty renderings is 70 characters in a column that
holds about 40.

The fix is a layout one. The column lays its content out as a column and the
input is held at the bottom with mt-auto, so every field in the row sits on one
line whatever the labels do.

WHY THIS FILE NOW SWEEPS (2026-09-24). It named that one row and those three
field ids, which is the guard matching the shape of its finding rather than
the rule it states - the vein that has paid out nine times in this codebase.
The rule is about a SHAPE: two or more columns side by side, each holding one
label and one control, where the control is the last thing in the column. It
now finds every such column in every template and requires the protection.

WHAT THE SWEEP MEASURED, so nobody has to measure it again:

  * 29 rows in the panel hold two or more label-and-control columns.
  * 18 columns of this exact shape can wrap - their longest rendering across
    the 40 catalogues is longer than the column holds. One of them is the
    operator's, and it is the protected one.
  * THE OTHER 17 ARE ALL IN _advanced_settings_modal.html AND THIS FIX DOES
    NOT APPLY TO THEM. Every one of its 24 such columns carries a hint line
    UNDER the input. Holding the input at the bottom would push the input and
    its hint down together, which is not the same as aligning the inputs;
    lining up a three-part column is a layout decision for the operator, not
    something to invent here. Measured and left alone on purpose - it is a
    finding, not an oversight.

So this sweep deliberately skips a column whose control is not its last
element. A guard that claimed those too would be red on a file nobody has
agreed to change, and a red that cannot be fixed is a red everybody learns to
ignore.

COUNTER-CHECK (2026-09-22): red before - no column carried the flex class and
no input the mt-auto that holds it at the bottom. (2026-09-24): green after the
sweep replaced the named row, and sabotaged three ways to prove it still bites.
"""

import json
import re
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[2]
TEMPLATES = PROJECT / "app" / "templates"
TAG = re.compile(r"<(/?)(\w+)([^>]*?)(/?)>", re.S)
CONTROL = re.compile(r"<(input|select|textarea)\b", re.I)
LABEL = re.compile(r"<label\b", re.I)


def _divs(markup):
    """Every <div> as (classes, inner markup), by counting depth.

    An HTML parser is not used because these are Jinja templates: a tag can be
    opened in one branch of an {% if %} and closed in another, which a strict
    parser rejects outright.
    """
    out, stack = [], []
    for match in TAG.finditer(markup):
        closing, name, attrs, selfclose = match.groups()
        if name != "div":
            continue
        if closing:
            if stack:
                start, classes = stack.pop()
                out.append((classes, markup[start:match.start()]))
        elif not selfclose:
            found = re.search(r'class="([^"]*)"', attrs)
            stack.append((match.end(), found.group(1) if found else ""))
    return out


def _is_column(classes):
    return any(name == "col" or name.startswith("col-") for name in classes.split())


def _control_is_last(inner):
    """Whether the control is the last thing in the column.

    A hint line under the field changes the shape: holding the input at the
    bottom would take the hint down with it.
    """
    control = list(CONTROL.finditer(inner))[-1]
    after = inner[control.end():]
    after = re.sub(r"<(/?)(input|br|hr|img)\b[^>]*>", "", after, flags=re.I)
    return not re.search(r"<\w+", after)


def _takes_part_in_the_alignment(inner):
    """Whether this column is a label above a field, which is the thing being
    lined up.

    A SWITCH IS NOT. Its control sits BEFORE its label, on the same line, and
    holding it at the bottom of a tall column would tear the two apart. It has
    no field edge to line up with anything, so it neither gets the fix nor
    stops its neighbours from getting it.

    Requiring every column of a row to qualify - which the first version of
    this did - meant one switch kept four number fields in the operator's
    screenshot ragged, which is the row he reported (2026-09-24).
    """
    if len(LABEL.findall(inner)) != 1 or len(CONTROL.findall(inner)) != 1:
        return False
    return LABEL.search(inner).start() < CONTROL.search(inner).start() \
        and _control_is_last(inner)


def _shaped_columns():
    """Every column of the finding's shape, in a row where the fix applies.

    THE WHOLE ROW HAS TO BE OF THE SHAPE, and the first version of this did not
    check that - it gated on "two or more label-and-control columns" and then
    demanded the protection only of the ones whose control is last. That asked
    for half a row to be bottom-aligned while its neighbour stayed top-aligned,
    which does not line the fields up, it just moves them differently. Four
    columns were reported that way, each sitting beside one with a hint line
    under its field.

    So a row counts only when every one of its label-and-control columns can
    take the fix. A mixed row is the _advanced_settings_modal.html case and
    belongs to the operator, not to a sweep.
    """
    for path in sorted(TEMPLATES.rglob("*.html")):
        markup = path.read_text(encoding="utf-8")
        for classes, inner in _divs(markup):
            if "row" not in classes.split():
                continue
            columns = [(c, i) for c, i in _divs(inner) if _is_column(c)]
            shaped = [(c, i) for c, i in columns if _takes_part_in_the_alignment(i)]
            if len(shaped) < 2:
                continue
            for c, i in shaped:
                yield path.name, c, i


def test_the_sweep_still_finds_the_row_it_was_written_for():
    """Safeguard: a sweep that matches nothing would make the case below pass
    without looking at anything. Two earlier versions of this measurement did
    exactly that in different ways - one glued a Bulgarian label to a French
    tooltip, the other counted several labels in one column as one."""
    found = [(name, classes) for name, classes, _ in _shaped_columns()]

    assert len(found) >= 3, f"only {len(found)} columns of this shape found"
    assert any(name == "_auth_settings.html" for name, _ in found), (
        "the row the finding was written about is not in the sweep any more")


def test_every_such_column_lays_its_content_out_as_a_column():
    """THE RULE: a column whose label can wrap must not let that move its
    field, and no language can be ruled out in advance."""
    offenders = [f"{name}: {classes}" for name, classes, _ in _shaped_columns()
                 if not ("d-flex" in classes and "flex-column" in classes)]

    assert offenders == [], (
        "these columns align their content at the top, so the longest label "
        f"decides where its own field lands:\n  " + "\n  ".join(offenders))


def test_every_such_control_is_held_at_the_bottom():
    offenders = []
    for name, _classes, inner in _shaped_columns():
        control = CONTROL.search(inner)
        tag = inner[control.start():inner.index(">", control.start())]
        if not re.search(r'class="[^"]*\bmt-auto\b', tag):
            offenders.append(f"{name}: {tag.strip()[:70]}")

    assert offenders == [], (
        "these fields are not held at the bottom of their column:\n  "
        + "\n  ".join(offenders))


def test_the_three_fields_are_still_side_by_side():
    """Counter-check on the original fix: it must not have turned the one row
    into three rows."""
    markup = (TEMPLATES / "_auth_settings.html").read_text(encoding="utf-8")

    assert markup.count('<div class="col-md-4') == 3
    assert '<div class="row"' in markup or '<div class="row">' in markup


def test_the_label_really_can_outgrow_its_column():
    """The finding rests on a measurement, so the measurement is a case: the
    longest of the forty renderings of that label does not fit a third of the
    row. If a shorter wording ever made this false, the guard above would be
    protecting against nothing."""
    markup = (TEMPLATES / "_auth_settings.html").read_text(encoding="utf-8")
    position = markup.index('id="new_web_ui_password"')
    label = re.search(r"<label\b[^>]*>(.*?)</label>",
                      markup[markup.rindex("<label", 0, position):], re.S).group(1)
    keys = re.findall(r"_t\(\s*['\"]([^'\"]+)['\"]", re.sub(r"<[^>]*>", " ", label))

    assert keys, "the label carries no catalogue key"
    longest = 0
    for path in sorted((PROJECT / "locales").glob("*.json")):
        if path.name == "meta.json":
            continue
        catalogue = json.loads(path.read_text(encoding="utf-8"))
        longest = max(longest, len(" ".join(str(catalogue.get(k, k)) for k in keys)))

    assert longest > 40, (
        f"the longest rendering is {longest} characters and a col-md-4 holds "
        "about 40 - this label no longer wraps, so the guard guards nothing")
