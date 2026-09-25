# -*- coding: utf-8 -*-
"""A loop that runs forever logs what it DID, never what it is about to try.

THE VEIN THIS CAME OUT OF. One commit earlier the inactivity check was found
announcing "attempting regeneration" at INFO some 2,880 times a day for an
attempt it then decided against - the operator read those lines and concluded
his Discord panels were being recreated twice a minute. They were not. I
believed him, because the log said so.

FIXING THAT ONE LINE WOULD HAVE BEEN FIXING THE SYMPTOM. The same shape sits in
every repeating loop in this bot. Measured on the running container, 2026-09-25,
over ten minutes: 331 INFO lines, about 47,700 a day, and the most frequent ones
are all announcements -

    11  Inactivity check loop running
    11  Currently tracking 2 channels for activity: [...]
    10  Direct Cog Periodic Edit Loop: Processing channel <id> ...
     6  --- DIRECT COG periodic_message_edit_loop cycle --- Starting Check ---
     5  Direct Cog Periodic Edit Loop: Checking 2 channels with tracked messages.
     3  [STATUS_LOOP] Bulk updating cache for 7 containers

- while the OUTCOME of each of those cycles is already logged separately, and
is the line worth keeping: "Periodic message update finished. Total tasks: 2.
Success: 2, NotFound: 0, Errors: 0".

WHY IT MATTERS BEYOND TIDINESS. A log at this volume rotates, so noise pushes
real events out of the window before anybody reads them; and a line that fires
every thirty seconds whatever happens teaches its reader to skip the whole file.
Both cost exactly what they cost here: a wrong diagnosis.

THE RULE, and it is a structural one so it can be checked rather than argued:
a `@tasks.loop` WITHOUT `count=` repeats for the life of the process, so
nothing in it may reach INFO unconditionally. An outcome is logged inside the
branch that produced it, which is the natural place for it anyway. A
`@tasks.loop(count=1)` runs once at startup and is exempt - "starting the
animation cache warmup" is news the first time and only the first time.

WHAT THIS RULE DOES NOT CATCH, said plainly: a line wrapped in `if True:`, or
one inside a branch that is taken every cycle in practice. Several of the
counts above are of that second kind. They are a judgement about what an
operator wants to see, not something a syntax tree can decide, so they are
reported to him rather than ratcheted here.

HOW THIS TEST CAN FAIL: a new endless loop that announces itself.

COUNTER-CHECK (2026-09-25): red before - five lines in three loops.
"""

import ast
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
SKIP = {"tests", ".git", "node_modules", "htmlcov", "venv", ".venv"}


def _repeating_loops():
    """(path, function) for every @tasks.loop that never stops."""
    for path in sorted(PROJECT.rglob("*.py")):
        if SKIP & set(path.relative_to(PROJECT).parts):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                mark = ast.unparse(decorator)
                if "tasks.loop" not in mark:
                    continue
                # count= makes it finite: it runs that many times and stops.
                if any(kw.arg == "count" for kw in getattr(decorator, "keywords", [])):
                    continue
                yield path.relative_to(PROJECT), node


def _announcements(body):
    """INFO calls reached on every single tick - no `if`, no `for` above them.

    A bare `try:` is transparent here: its body runs unconditionally too, and
    every loop in this bot wraps itself in one.
    """
    for statement in body:
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
            if "logger.info" in ast.unparse(statement.value.func):
                yield statement
        elif isinstance(statement, ast.Try):
            yield from _announcements(statement.body)


def test_no_endless_loop_logs_at_info_every_tick():
    """THE FINDING: five lines, three loops, tens of thousands of entries a day."""
    offenders = []
    for path, loop in _repeating_loops():
        for said in _announcements(loop.body):
            offenders.append(f"{path}:{said.lineno} in {loop.name}(): "
                             f"{ast.unparse(said.value)[:80]}")

    assert offenders == [], (
        "these reach INFO on every tick of a loop that never ends - log what "
        f"the cycle DID, in the branch that did it: {offenders}")


def test_the_loops_are_actually_being_found():
    """Counter-check. A scanner that matches nothing passes the case above
    while proving nothing - the mistake that let four earlier sabotages
    through. The bot HAS endless loops; if this finds none, the rule above is
    unenforced."""
    found = list(_repeating_loops())

    assert len(found) >= 3, f"only found {[f'{p}:{n.name}' for p, n in found]}"


def test_a_startup_loop_is_left_alone():
    """Counter-check the other way: count=1 loops run once and their lines are
    news. Silencing them would be the opposite mistake, and a rule that cannot
    tell the two apart would cause it."""
    once = [f"{path}:{loop.name}" for path in [PROJECT / "cogs" / "background_loops.py"]
            for loop in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
            if isinstance(loop, (ast.FunctionDef, ast.AsyncFunctionDef))
            and any("count=1" in ast.unparse(d) for d in loop.decorator_list)]

    assert once, "no count=1 loop left to prove the exemption is real"
    exempt = {f"{p}:{n.name}" for p, n in _repeating_loops()}

    assert not exempt & set(once), f"a startup loop is being treated as endless: {once}"


def test_the_cycles_still_report_what_they_did():
    """The point is not a silent bot. Each of the three loops must still have
    an INFO line SOMEWHERE - inside the branch that did the work."""
    for name, source in (("inactivity_check_loop", PROJECT / "cogs" / "background_loops.py"),
                         ("status_update_loop", PROJECT / "cogs" / "background_loops.py"),
                         ("periodic_message_edit_loop", PROJECT / "cogs" / "message_updates.py")):
        loop = next(node for node in ast.walk(ast.parse(source.read_text(encoding="utf-8")))
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == name)

        assert "logger.info" in ast.unparse(loop), (
            f"{name} has gone completely silent - an operator cannot tell it ran at all")
