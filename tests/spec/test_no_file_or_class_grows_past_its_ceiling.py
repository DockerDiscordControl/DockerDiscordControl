# -*- coding: utf-8 -*-
"""No source file past 1,500 lines, no class past 1,000 - and the exceptions only shrink.

The end of Phase 3 (roadmap 2026-09-22). DockerControlCog had grown to 4,494
lines in one class and docker_control.py to 5,436, one feature at a time; the
split took six commits and a sabotage scan per step to keep every test
honest. The ceiling keeps the next one from growing unnoticed:

* a source file over FILE_LIMIT or a class over CLASS_LIMIT fails, unless it
  is on the exception list;
* a listed file or class may not grow past the size recorded here - the
  record is the ceiling for that one;
* a listed one that has come down to the limit must leave the list, so the
  list only ever shrinks and never lies.

1,500 lines per file is what a review section can hold with room to spare
(docs/quality/SECTIONS.txt, 2,000 per section).

COUNTER-CHECK (2026-09-22): lowering the recorded size of control_ui.py by one
line turned the growth check red; a synthetic 1,001-line class is caught by
the class counter (test below); raising FILE_LIMIT to 4,000 made the "must
leave the list" check name all six files.
"""

import ast
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
DIRECTORIES = ("cogs", "services", "app", "utils")
FILE_LIMIT = 1500
CLASS_LIMIT = 1000

# Measured 2026-09-22. May only go down; remove an entry once it is at the limit.
FILE_EXCEPTIONS = {
    "cogs/control_ui.py": 3780,
    "services/scheduling/scheduler.py": 2260,
    "services/mech/animation_cache_service.py": 1846,
    "services/mech/progress_service.py": 1740,
    "app/blueprints/main_routes.py": 1514,
}
CLASS_EXCEPTIONS = {
    "services/mech/animation_cache_service.py::AnimationCacheService": 1762,
    "cogs/status_handlers.py::StatusHandlersMixin": 1325,
    "services/config/config_service.py::ConfigService": 1067,
}


def _sources():
    for directory in DIRECTORIES:
        for path in sorted((PROJECT / directory).rglob("*.py")):
            yield path.relative_to(PROJECT).as_posix(), path.read_text(encoding="utf-8")


def _class_sizes(source):
    return {node.name: node.end_lineno - node.lineno + 1
            for node in ast.walk(ast.parse(source)) if isinstance(node, ast.ClassDef)}


def _file_sizes():
    return {name: len(text.splitlines()) for name, text in _sources()}


def _all_class_sizes():
    return {f"{name}::{cls}": size for name, text in _sources() for cls, size in _class_sizes(text).items()}


def _check(sizes, limit, exceptions):
    too_big = {k: v for k, v in sizes.items() if v > limit and k not in exceptions}
    grew = {k: (exceptions[k], sizes[k]) for k in exceptions if k in sizes and sizes[k] > exceptions[k]}
    may_leave = sorted(k for k in exceptions if sizes.get(k, 0) <= limit)
    return too_big, grew, may_leave


def test_the_scan_sees_the_code():
    sizes = _file_sizes()
    assert "cogs/docker_control.py" in sizes and len(sizes) > 150, len(sizes)


def test_no_file_grows_past_its_ceiling():
    too_big, grew, may_leave = _check(_file_sizes(), FILE_LIMIT, FILE_EXCEPTIONS)
    assert not too_big, f"New files over {FILE_LIMIT} lines - split them: {too_big}"
    assert not grew, f"Listed files grew past their recorded size (record, now): {grew}"
    assert not may_leave, f"At or under the limit now - remove from FILE_EXCEPTIONS: {may_leave}"


def test_no_class_grows_past_its_ceiling():
    too_big, grew, may_leave = _check(_all_class_sizes(), CLASS_LIMIT, CLASS_EXCEPTIONS)
    assert not too_big, f"New classes over {CLASS_LIMIT} lines - split them: {too_big}"
    assert not grew, f"Listed classes grew past their recorded size (record, now): {grew}"
    assert not may_leave, f"At or under the limit now - remove from CLASS_EXCEPTIONS: {may_leave}"


def test_the_class_counter_bites():
    """Proof of effect: a class one line over the limit is counted as such."""
    body = "\n".join(f"    x{i} = {i}" for i in range(CLASS_LIMIT - 1))
    sizes = _class_sizes(f"class Big:\n{body}\n")
    assert sizes == {"Big": CLASS_LIMIT}
    assert _check({"a::Big": CLASS_LIMIT + 1}, CLASS_LIMIT, {}) [0] == {"a::Big": CLASS_LIMIT + 1}
