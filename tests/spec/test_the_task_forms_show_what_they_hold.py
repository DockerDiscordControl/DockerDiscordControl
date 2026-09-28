# -*- coding: utf-8 -*-
"""The task forms show what they hold: the task's container, and only the rows that apply.

SEEN ON THE OPERATOR'S SCREEN (2026-09-28):

1. THE EDIT DIALOG SHOWED NO CONTAINER - for every task. The dialog moved out
   of tasks/list.html into its own partial on 2026-09-23 (a form inside a form
   is thrown away by the browser). list.html is included inside
   `{% with active_containers=active_container_names %}`; the new include in
   config.html had no such block, so the dialog's container select had no
   options, a task's container could not be selected, and "required" would not
   let the dialog save. Editing a task in the panel was broken for five days.
2. THE CRON ROW WAS ALWAYS THERE. Both forms hide it with style="display: none"
   and show it for the cron cycle - but the row also carried Bootstrap's
   d-flex, which is display:flex !important and beats any style.display.
3. THE DATE FIELDS STOOD HIGHER than cycle and time beside them: their help text
   sat below the fields, the neighbours' above. And the player options block
   (v3.0.2) sat in the middle of that row - appearing for restart or stop, it
   pushed the date fields onto a line of their own.

COUNTER-CHECK (2026-09-28): without the with-block around the dialog's
include, the dialog case went red; with d-flex back on a cron row, the
hidden-row case did; with the player block back between time and date, the
order case did. The first fix dropped d-flex from the cron rows - and broke
tests/spec/test_a_wrapping_label_does_not_move_its_field.py, which wants that
column laid out as a column; the rows keep d-flex and are hidden !important.
"""

import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, nodes

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "app" / "templates"
ENV = Environment(loader=FileSystemLoader(str(TEMPLATES)))


def _includes_with(template, target):
    """For each include of `target`: the names a surrounding {% with %} provides."""
    found = []

    def walk(node, provided):
        if isinstance(node, nodes.With):
            provided = provided | {t.name for t in node.targets if isinstance(t, nodes.Name)}
        if isinstance(node, nodes.Include) and isinstance(node.template, nodes.Const) \
                and node.template.value == target:
            found.append(provided)
        for child in node.iter_child_nodes():
            walk(child, provided)
    walk(ENV.parse(ENV.loader.get_source(ENV, template)[0]), frozenset())
    return found


def test_the_edit_dialog_is_given_the_containers():
    for include in ("tasks/_edit_modal.html", "tasks/form.html", "tasks/list.html"):
        found = _includes_with("config.html", include)
        assert found, f"config.html no longer includes {include}"
        assert all("active_containers" in provided for provided in found), \
            f"{include} is included without the container list"


def test_the_dialog_offers_the_tasks_container_when_it_is_given_one():
    html = ENV.get_template("tasks/_edit_modal.html").render(
        active_containers=["Icarus", "Icarus2"], _t=lambda key: key)
    select = re.search(r'<select[^>]*id="editTaskContainer".*?</select>', html, re.S).group(0)
    assert '<option value="Icarus">Icarus</option>' in select


def _elements_with_inline_hide(html):
    return re.findall(r'<[a-z]+\b[^>]*style="[^"]*display:\s*none[^"]*"[^>]*>', html)


def test_a_hidden_row_can_stay_hidden():
    """Bootstrap's d-* display classes are !important: an element they lay out and
    that starts hidden with style="display: none" needs the inline hide to be
    !important too, or it never hides. (The row keeps its d-flex: it lines its
    field up with the others, tests/spec/test_a_wrapping_label_does_not_move_its_field.py.)
    force-hide (theme.css) is the panel's own !important hide and is fine."""
    offenders = []
    for path in sorted(TEMPLATES.rglob("*.html")):
        for tag in _elements_with_inline_hide(path.read_text(encoding="utf-8")):
            classes = re.search(r'class="([^"]*)"', tag)
            names = set(classes.group(1).split()) if classes else set()
            if names & {"d-flex", "d-block", "d-inline", "d-inline-block", "d-grid", "d-table"} \
                    and "force-hide" not in names and "!important" not in tag:
                offenders.append(f"{path.relative_to(ROOT)}: {tag[:90]}")
    assert offenders == [], offenders


def test_the_scripts_show_and_hide_it_with_the_same_weight():
    """A row hidden with !important is shown only by a property set !important."""
    form_js = (ROOT / "app" / "static" / "js" / "task_form.js").read_text(encoding="utf-8")
    tasks_js = (ROOT / "app" / "static" / "js" / "tasks.js").read_text(encoding="utf-8")
    assert "taskCronStringRow').style.display" not in form_js and "cronRow.style.display" not in form_js
    helpers = tasks_js[tasks_js.index("showElement(elementId) {"):tasks_js.index("hideElement(elementId) {") + 200]
    assert helpers.count("'important'") == 2, "the edit dialog's show/hide can still lose against d-flex"


def test_the_date_help_stands_above_its_fields_like_its_neighbours():
    form = (TEMPLATES / "tasks" / "form.html").read_text(encoding="utf-8")
    date = form[form.index('id="dateFieldsContainer"'):form.index('id="taskCronStringRow"')]
    assert date.index("web.tasks.date_help") < date.index('id="taskDay"')


def test_the_player_options_do_not_split_the_schedule_row():
    form = (TEMPLATES / "tasks" / "form.html").read_text(encoding="utf-8")
    assert form.index('id="dateFieldsContainer"') < form.index('id="taskPlayerGate"'), \
        "the player options sit between time and date and push the date fields down"
