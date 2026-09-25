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

AND A SECOND RULE, added the same day when he said "fix everything". The
first one only catches a loop announcing ITSELF. The lines above marked
"Processing channel", "Starting adaptive bulk fetch" and "Updating Docker
cache" sit inside a branch - they are conditional, and the condition is true
every single time. What gives them away is not their position but their VERB:
they describe something that has not happened yet and may not, while the line
that closes the same cycle reports what came of it. So per-cycle code may log
a result at INFO and must log a plan at DEBUG, and "per-cycle" reaches one
level of call graph, because the loudest of them live in helpers.

WHAT NEITHER RULE CATCHES, said plainly: a line wrapped in `if True:`, and a
plan phrased without one of the verbs. Both would need a reader, not a parser.

HOW THIS TEST CAN FAIL: a new endless loop that announces itself, or per-cycle
code that says at INFO what it is about to do.

COUNTER-CHECK (2026-09-25): red before - five lines in three loops for the
first rule, and nine more across four modules for the second.
"""

import ast
import re
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


# Per-cycle code that no decorator marks: these two run on every pass of the
# background Docker-cache refresh THREAD, which is a plain `while` in a
# thread rather than a @tasks.loop, so the structural rule cannot see them.
# "Updating Docker cache with memory optimization" was the single most
# frequent line in the operator's log - 30 in 25 minutes, paired every time
# with the "Docker cache updated with 37 containers" that actually says
# something. Naming them here is a recorded decision, not a fix left
# unguarded; a scan that silently misses its loudest subject is worthless.
THREAD_LOOP_HELPERS = {"update_docker_cache", "bulk_update_status_cache"}

LABEL = re.compile(r"^\s*(\[[^\]]+\]\s*|[A-Za-z][\w ()/-]{0,45}?:\s+)")
ANNOUNCES_A_PLAN = re.compile(
    r"^(starting|attempting|processing|checking|will |about to|preparing|"
    r"updating|running|scheduling)\b", re.I)


def _per_cycle_functions():
    """Every function that runs on each tick of a loop that never ends.

    The loops themselves, plus - one level of call graph, by name - the
    helpers they call. `bulk_fetch_container_status` is not decorated and lives
    in another module, but it runs once a cycle and talked like it: four INFO
    lines per pass through the operator's log.

    NOT `while True:`. Widening it that way pulled in bot.py's start-up retry
    loop, which runs once in practice, and reported five of its lines. A scan
    that flags a decision has to know the difference.

    BY NAME, NOT BY IDENTITY. The first version tested `fn is loop` against the
    loops collected by _repeating_loops() - which parses the files a second
    time, so the nodes are different objects and the comparison was never true.
    The loop BODIES therefore fell out of the scan entirely, and the sabotage
    that put "Processing channel" back at INFO inside periodic_message_edit_loop
    passed green while the one in a helper went red. Eighth sabotage to survive
    a case of mine, and the first to do it by catching a real bug in the scan
    rather than a hole in the wording.
    """
    per_cycle = {fn.name for _path, fn in _repeating_loops()} | THREAD_LOOP_HELPERS
    for _path, loop in _repeating_loops():
        for node in ast.walk(loop):
            if isinstance(node, ast.Call):
                func = node.func
                per_cycle.add(func.attr if isinstance(func, ast.Attribute)
                              else getattr(func, "id", None))
    per_cycle.discard(None)

    for path in sorted(PROJECT.rglob("*.py")):
        if SKIP & set(path.relative_to(PROJECT).parts) or "scripts" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                    and fn.name in per_cycle:
                yield path.relative_to(PROJECT), fn


def _first_literal(call):
    for argument in call.args[:1]:
        for piece in ast.walk(argument):
            if isinstance(piece, ast.Constant) and isinstance(piece.value, str):
                return piece.value
    return None


def test_per_cycle_code_reports_results_at_info_not_plans():
    """THE SECOND HALF OF THE RULE, and the operator's "fix everything".

    The first case below stops a loop announcing ITSELF. This one stops it
    announcing each STEP - which is where the rest of his 47,700 INFO lines a
    day were coming from:

        Direct Cog Periodic Edit Loop: Processing channel <id> ...   28 / 25min
        [INTELLIGENT_BULK_FETCH] Starting adaptive bulk fetch ...    11 / 25min
        Updating Docker cache with memory optimization               30 / 25min

    Every one of those is followed, within the same cycle, by the line that
    says what came of it - "Docker cache updated with 37 containers",
    "Fast adaptive fetch completed in 80.5ms: 7/7", "Periodic message update
    finished. Total tasks: 2. Success: 2". That closing line is the one worth
    having, and it stays.

    The verb is the test because the verb is the decision: "Starting",
    "Attempting", "Processing" describe something that has not happened yet
    and may not. A label in front - "[BULK_UPDATE] " or "Direct Cog Periodic
    Edit Loop: " - is stripped first, because that is where these lines hide.
    """
    offenders = []
    for path, fn in _per_cycle_functions():
        for node in ast.walk(fn):
            if not isinstance(node, ast.Call):
                continue
            if not re.search(r"log(ger)?\.info$", ast.unparse(node.func)):
                continue
            text = _first_literal(node)
            if text and ANNOUNCES_A_PLAN.match(LABEL.sub("", text, count=1)):
                offenders.append(f"{path}:{node.lineno} in {fn.name}(): {text[:60]}")

    assert sorted(set(offenders)) == [], (
        "per-cycle code says what it is about to do, at INFO, forever - log the "
        f"result instead: {sorted(set(offenders))}")


def test_a_plan_is_told_apart_from_a_result():
    """Counter-check both ways, on the real lines.

    A pattern that matched everything would silence the closing lines this
    whole change exists to protect; one that matched nothing would prove
    nothing - the hole seven sabotages have walked through.
    """
    plans = ("Direct Cog Periodic Edit Loop: Processing channel 123",
             "[INTELLIGENT_BULK_FETCH] Starting adaptive bulk fetch for 7 containers",
             "Updating Docker cache with memory optimization",
             "Attempting to run 2 message edit tasks.")
    results = ("Docker cache updated with 37 containers",
               "[INTELLIGENT_BULK_FETCH] Fast adaptive fetch completed in 80.5ms: 7/7",
               "Direct Cog Periodic message update finished. Total tasks: 2. Success: 2",
               "✅ Channel tech-channel successfully regenerated due to inactivity")

    for plan in plans:
        assert ANNOUNCES_A_PLAN.match(LABEL.sub("", plan, count=1)), plan
    for result in results:
        assert not ANNOUNCES_A_PLAN.match(LABEL.sub("", result, count=1)), result


def test_both_the_loops_and_their_helpers_are_reached():
    """Counter-check on the scan's reach, and it has already earned its keep.

    Two ways for the case above to silently shrink to nothing: the loop bodies
    falling out (they did - `fn is loop` compared nodes from two separate
    parses and was never true), or the one level of call graph breaking, which
    would drop the loudest lines in his log because they live in helpers.
    Both are named here so neither can go quiet again.
    """
    reached = {fn.name for _path, fn in _per_cycle_functions()}

    assert "periodic_message_edit_loop" in reached, "the loop bodies are not scanned"
    assert "bulk_fetch_container_status" in reached, "the helpers are not scanned"
    assert "update_docker_cache" in reached, "the thread-loop helpers are not scanned"


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
