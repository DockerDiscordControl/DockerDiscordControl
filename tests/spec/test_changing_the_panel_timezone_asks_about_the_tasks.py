# -*- coding: utf-8 -*-
"""Changing the panel's timezone asks what should happen to existing tasks.

THE FINDING, measured on the operator's server on 2026-09-23: the panel
timezone is `timezone` in config.json (Europe/Berlin), and every scheduled
task carries its OWN `_timezone_str` (4 tasks, all Europe/Berlin). Saving a
new panel timezone clears a cache and answers:

    "Critical settings changed - caches have been invalidated.
     Changes should take effect immediately."

Existing tasks are not touched, and that sentence is not true for them. A
task that says "daily 10:00" keeps firing at 10:00 Europe/Berlin - while the
same page now renders its next run converted into the new zone, so the row
shows "10:00" next to a next run of 04:00. Nothing is logged, because from
the save's point of view nothing went wrong.

Neither answer is right by itself:

    move them along   the operator relocated; 10:00 should stay 10:00
    leave them        the schedule is tied to something real elsewhere,
                      and 10:00 Berlin has to stay 10:00 Berlin

OPERATOR DECISION (2026-09-23): ASK. The config is saved either way; only the
tasks are in question, and the panel puts that question up with both answers
spelled out in wall-clock terms.

HOW THIS TEST CAN FAIL: it saves a config with a different timezone and looks
for the question in the answer, and it calls the move and checks that the task
kept its CLOCK time rather than its moment. A save that silently moves tasks,
one that silently leaves them without saying so, and a move that shifts the
clock time instead of the zone are each red.

COUNTER-CHECK (2026-09-23): red before - there was no question in the save
answer and no way to move a task's zone at all. The tests below keep the
save's existing behaviour: the tasks are NOT moved by the save itself.
"""

import json

import pytest

from services.scheduling.scheduler import ScheduledTask


def _task(task_id, timezone_str="Europe/Berlin", time_str="10:00"):
    return ScheduledTask(task_id=task_id, container_name="alpha", action="start",
                         cycle="daily", schedule_details={"time": time_str},
                         timezone_str=timezone_str)


@pytest.fixture
def tasks(monkeypatch):
    """A stand-in tasks.json: what load_tasks reads and save_tasks writes."""
    import services.scheduling.task_timezone as module

    stored = [_task("berlin-one"), _task("berlin-two", time_str="03:30"),
              _task("already-there", timezone_str="America/New_York")]
    monkeypatch.setattr(module, "load_tasks", lambda: list(stored))

    written = []

    def save(new_tasks):
        written.clear()
        written.extend(new_tasks)
        return True

    monkeypatch.setattr(module, "save_tasks", save)
    return stored, written


def test_it_counts_only_the_tasks_that_would_change(tasks):
    """The question has to name a real number, not "your tasks"."""
    from services.scheduling.task_timezone import tasks_in_other_timezones

    to_new_york = tasks_in_other_timezones("America/New_York")
    to_berlin = tasks_in_other_timezones("Europe/Berlin")

    assert sorted(t.task_id for t in to_new_york) == ["berlin-one", "berlin-two"]
    # The other direction, which the first version of this test got wrong: the
    # one task already in New York is the one that would move to Berlin.
    assert [t.task_id for t in to_berlin] == ["already-there"]


def test_moving_them_keeps_the_clock_time_not_the_moment(tasks):
    """THE POINT: "take them along" means 10:00 stays 10:00, in the new zone.

    Keeping the MOMENT would be the other answer - and that one needs no code
    at all, because it is what leaving the task's own zone alone already does.
    """
    from datetime import datetime

    import pytz

    from services.scheduling.task_timezone import retime_tasks

    moved = retime_tasks("America/New_York")
    stored, written = tasks

    assert moved == 2
    by_id = {t.task_id: t for t in written}
    assert by_id["berlin-one"].timezone_str == "America/New_York"
    when = datetime.fromtimestamp(by_id["berlin-one"].next_run_ts,
                                  pytz.timezone("America/New_York"))
    assert (when.hour, when.minute) == (10, 0), when


def test_a_task_already_in_the_new_zone_is_left_alone(tasks):
    """Counter-check: no needless rewrite, and no needless line in the log."""
    from services.scheduling.task_timezone import retime_tasks

    before = {t.task_id: t.next_run_ts for t in tasks[0]}
    retime_tasks("America/New_York")
    _, written = tasks

    same = next(t for t in written if t.task_id == "already-there")
    assert same.timezone_str == "America/New_York"
    assert same.next_run_ts == before["already-there"]


def test_nothing_is_written_when_there_is_nothing_to_move(monkeypatch):
    """Counter-check: a save that changes nothing must not rewrite tasks.json."""
    import services.scheduling.task_timezone as module

    monkeypatch.setattr(module, "load_tasks", lambda: [_task("a"), _task("b")])
    written = []
    monkeypatch.setattr(module, "save_tasks", lambda tasks: written.append(tasks))

    assert module.retime_tasks("Europe/Berlin") == 0
    assert written == [], "tasks.json was rewritten for nothing"


# --- The save answer: the question reaches the panel ---


def _save_answer(monkeypatch, old, new, elsewhere):
    """A config save whose only change is the timezone."""
    from services.web import configuration_save_service as module

    service = module.ConfigurationSaveService.__new__(module.ConfigurationSaveService)
    service.logger = module.logging.getLogger("test")
    monkeypatch.setattr(module, "tasks_in_other_timezones", lambda zone: elsewhere)
    return service._check_critical_changes({"timezone": new, "language": "en"},
                                           {"timezone": old, "language": "en"})


def test_the_save_answer_carries_the_question(monkeypatch):
    """THE FINDING: it used to say the change took effect immediately, full stop."""
    changes = _save_answer(monkeypatch, "Europe/Berlin", "America/New_York",
                           [_task("a"), _task("b")])

    assert changes.timezone_question == {"old": "Europe/Berlin",
                                         "new": "America/New_York", "tasks": 2}


def test_there_is_no_question_when_no_task_is_affected(monkeypatch):
    """Counter-check: a dialog with nothing behind it is worse than none."""
    assert _save_answer(monkeypatch, "Europe/Berlin", "America/New_York", []).timezone_question is None


def test_there_is_no_question_when_the_timezone_did_not_change(monkeypatch):
    """Counter-check: the other settings on that page must not raise it."""
    changes = _save_answer(monkeypatch, "Europe/Berlin", "Europe/Berlin", [_task("a")])

    assert changes.timezone_question is None
    assert changes.timezone_changed is False


def test_the_save_itself_moves_nothing(monkeypatch, tasks):
    """Counter-check, and the decision in one line: the config is saved either
    way, the tasks wait for the answer."""
    _save_answer(monkeypatch, "Europe/Berlin", "America/New_York", [_task("a")])

    assert tasks[1] == [], "the save moved tasks without asking"


# --- The panel: the question is put, and the answer can be given ---


def test_the_panel_asks_and_can_send_the_answer():
    """A question nobody is shown is not a question.

    THE CALL SITE, NOT A FILE THAT MENTIONS IT (audit 2026-09-26). This case
    used to grep main.js for "timezone_question" - and main.js is loaded by no
    template. The live save handler, saveConfigAjax in panel.js, ignored the
    question, so it was computed on every such save and never put. The case
    now holds the chain the browser actually runs: the page loads the helper
    before panel.js, and panel.js hands the save answer's question to it.

    COUNTER-CHECK (2026-09-26): red before - _scripts.html loaded no such
    helper and panel.js never read timezone_question.
    """
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    js = root / "app" / "static" / "js"
    scripts = (root / "app" / "templates" / "_scripts.html").read_text(encoding="utf-8")
    panel = (js / "panel.js").read_text(encoding="utf-8")

    assert "js/timezone_question.js" in scripts, "the page does not load the question"
    assert scripts.index("js/timezone_question.js") < scripts.index("js/panel.js")
    assert re.search(r"askAboutTaskTimezone\(\s*data\.timezone_question", panel), (
        "the save handler does not pass the question on")
    assert "/tasks/retime" in (js / "timezone_question.js").read_text(encoding="utf-8")
    assert not (js / "main.js").exists(), "main.js is back - no template loads it"


def test_the_question_in_node():
    import shutil
    import subprocess
    from pathlib import Path

    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed here - run tests/js/timezone_question.test.js by hand")
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run([node, str(root / "tests" / "js" / "timezone_question.test.js")],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("ok   - ") == 5, result.stdout


def test_the_endpoint_moves_the_tasks_and_says_how_many():
    """Counter-check: the answer has to reach the tasks."""
    from pathlib import Path

    blueprint = (Path(__file__).resolve().parents[2] / "app" / "blueprints"
                 / "tasks_bp.py").read_text(encoding="utf-8")

    assert "/retime" in blueprint
    assert "retime_tasks" in blueprint


def test_every_locale_carries_the_question():
    """A web string needs a key in every catalogue, not just en and de."""
    from pathlib import Path

    locales = [p for p in (Path(__file__).resolve().parents[2] / "locales").glob("*.json")
               if p.name != "meta.json"]
    keys = ("web.timezone.question_title", "web.timezone.question_body",
            "web.timezone.keep_clock", "web.timezone.keep_moment")

    assert len(locales) >= 40
    for path in locales:
        catalogue = json.loads(path.read_text(encoding="utf-8"))
        missing = [k for k in keys if k not in catalogue]
        assert missing == [], (path.name, missing)


def test_the_question_names_both_answers_in_clock_terms():
    """The operator has to be able to tell the two apart without guessing."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    for language in ("en", "de"):
        catalogue = json.loads((root / "locales" / f"{language}.json").read_text(encoding="utf-8"))
        assert "{count}" in catalogue["web.timezone.question_body"]
        assert "{old}" in catalogue["web.timezone.question_body"]
        assert "{new}" in catalogue["web.timezone.question_body"]
        assert catalogue["web.timezone.keep_clock"] != catalogue["web.timezone.keep_moment"]


def test_the_move_holds_the_tasks_lock_for_its_whole_cycle(monkeypatch):
    """It reads every task, rewrites some and writes them all back. Without the
    lock a task added in that window is replaced by a list that never saw it -
    the same read-modify-write gap that admins.json and auto_actions.json were
    fixed for. tasks.json has a lock for exactly this, reentrant in-process and
    taken across processes, and every other writer in scheduler.py holds it.

    Checked by holding the lock elsewhere and seeing the move wait for it.
    """
    import threading

    import services.scheduling.task_timezone as module
    from services.scheduling.runtime import TASKS_LOCK

    monkeypatch.setattr(module, "load_tasks", lambda: [_task("a")])
    monkeypatch.setattr(module, "save_tasks", lambda tasks: True)
    finished = threading.Event()

    with TASKS_LOCK:
        mover = threading.Thread(target=lambda: (module.retime_tasks("America/New_York"),
                                                 finished.set()))
        mover.start()
        got_through = finished.wait(1.0)

    mover.join(10)
    assert not got_through, "the move ran while another writer held the tasks lock"
