# -*- coding: utf-8 -*-
"""A cancellation is not one error among others.

THE FINDING (review C60, section 16 F5 and the same shape in fourteen more
places): ``_emergency_full_fetch`` ends with

    except (RuntimeError, OSError, asyncio.CancelledError) as e:
        perf_service.update_performance(docker_name, 0, False)
        logger.error(f"Emergency fetch failed for {docker_name}: {e}")
        return docker_name, last_exception, None

``asyncio.CancelledError`` inherits from ``BaseException``, not from
``Exception``, precisely so that it is not swallowed by accident. Naming it in
a tuple with ordinary errors undoes that on purpose. The task then returns a
normal value instead of ending as cancelled: ``task.cancelled()`` is False,
the shutdown believes the task finished by itself, and the emergency fetch can
keep the shutdown waiting for up to ``max_timeout`` (300 s at the top of the
configured range). The container is also marked as a failure in the
performance profile for something it never did.

The same shape sits in fourteen other places across bot startup, the admin
overview, the info modal, the update notifier and the cleanup service. The
scan below holds the whole class shut.

A handler that names ``asyncio.CancelledError`` on its own is a different
matter: that is a visible decision about a cancellation, usually a task loop
leaving its while, and it stays allowed.
"""

import ast
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
SOURCE_DIRS = ("services", "app", "cogs", "utils")


def _is_cancelled_error(node: ast.AST) -> bool:
    """`asyncio.CancelledError` or a bare `CancelledError`."""
    if isinstance(node, ast.Attribute):
        return node.attr == "CancelledError"
    return isinstance(node, ast.Name) and node.id == "CancelledError"


def _scan(source: str) -> list:
    """except clauses that mix a cancellation into a tuple of errors."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.ExceptHandler) or node.type is None:
            continue
        if not isinstance(node.type, ast.Tuple):
            continue            # named on its own: a visible decision, allowed
        if any(_is_cancelled_error(part) for part in node.type.elts):
            found.append((node.lineno, ast.unparse(node.type)))
    return found


def _python_files():
    for directory in SOURCE_DIRS:
        yield from (PROJECT / directory).rglob("*.py")


def test_no_except_clause_treats_a_cancellation_as_an_error():
    """THE FINDING: a cancellation must reach the task that issued it."""
    offenders = []
    for path in _python_files():
        for lineno, expression in _scan(path.read_text(encoding="utf-8")):
            offenders.append(f"{path.relative_to(PROJECT)}:{lineno} {expression}")

    assert offenders == [], "\n".join(offenders)


def test_the_scan_finds_a_planted_one():
    """BLINDNESS GUARD: an empty result must mean "none left", not "looked
    for nothing"."""
    planted = (
        "import asyncio\n"
        "\n"
        "async def f():\n"
        "    try:\n"
        "        pass\n"
        "    except (RuntimeError, asyncio.CancelledError):\n"
        "        pass\n"
    )

    assert _scan(planted) == [(6, "(RuntimeError, asyncio.CancelledError)")]


def test_the_scan_finds_an_imported_one():
    """BLINDNESS GUARD: `from asyncio import CancelledError` counts too."""
    planted = (
        "from asyncio import CancelledError\n"
        "\n"
        "async def f():\n"
        "    try:\n"
        "        pass\n"
        "    except (OSError, CancelledError):\n"
        "        pass\n"
    )

    assert _scan(planted) == [(6, "(OSError, CancelledError)")]


def test_the_scan_leaves_a_deliberate_handler_alone():
    """BLINDNESS GUARD, other side: naming it on its own stays allowed."""
    deliberate = (
        "import asyncio\n"
        "\n"
        "async def f():\n"
        "    while True:\n"
        "        try:\n"
        "            pass\n"
        "        except asyncio.CancelledError:\n"
        "            break\n"
        "        except (RuntimeError, OSError):\n"
        "            pass\n"
    )

    assert _scan(deliberate) == []


# --------------------------------------------------------------------------- #
# The finding in the concrete: the emergency fetch of section 16 F5.
# --------------------------------------------------------------------------- #

import asyncio

import pytest

from services.docker_status.fetch_service import DockerStatusFetchService


@pytest.mark.asyncio
async def test_a_cancelled_emergency_fetch_ends_as_cancelled(monkeypatch):
    service = DockerStatusFetchService()

    async def _cancelled(docker_name, timeout_seconds):
        raise asyncio.CancelledError()

    monkeypatch.setattr(service, "_fetch_info_and_stats", _cancelled)

    with pytest.raises(asyncio.CancelledError):
        await service._emergency_full_fetch("web", RuntimeError("earlier attempt"))


@pytest.mark.asyncio
async def test_a_cancelled_fetch_is_not_recorded_as_a_slow_container(monkeypatch):
    """The container did nothing wrong - it was never asked."""
    service = DockerStatusFetchService()
    recorded = []

    async def _cancelled(docker_name, timeout_seconds):
        raise asyncio.CancelledError()

    class _Perf:
        @staticmethod
        def get_config():
            return type("Config", (), {"max_timeout": 30000})()

        @staticmethod
        def update_performance(name, elapsed, success):
            recorded.append((name, success))

    monkeypatch.setattr(service, "_fetch_info_and_stats", _cancelled)
    monkeypatch.setattr("services.docker_status.fetch_service.get_performance_service",
                        lambda: _Perf())

    with pytest.raises(asyncio.CancelledError):
        await service._emergency_full_fetch("web", RuntimeError("earlier attempt"))

    assert recorded == [], (
        f"a cancellation was written into the performance profile as a failure: {recorded}"
    )


@pytest.mark.asyncio
async def test_a_real_error_is_still_handled(monkeypatch):
    """Counter-check: an OSError still comes back as the documented answer."""
    service = DockerStatusFetchService()

    async def _broken(docker_name, timeout_seconds):
        raise OSError("docker socket is gone")

    monkeypatch.setattr(service, "_fetch_info_and_stats", _broken)

    name, info, stats = await service._emergency_full_fetch("web", RuntimeError("earlier"))

    assert name == "web"
    assert isinstance(info, RuntimeError)
    assert stats is None
