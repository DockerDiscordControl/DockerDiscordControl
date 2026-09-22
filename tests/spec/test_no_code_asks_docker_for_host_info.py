# -*- coding: utf-8 -*-
"""DDC never asks the Docker daemon for host information (GET /info).

The v3.0 proxy lets through an exact list of endpoints (V3 §3): eight that
DDC's code calls plus the ``GET /version`` docker-py sends itself. ``GET /info``
is not on it - it describes the whole host (kernel, storage driver, every
registry, counts of all containers and images), and DDC has no feature that
needs it.

It was reachable in one place only: ``docker_utils.analyze_docker_stats_performance``
called ``client.info`` for a "host info" field in a diagnostic report. The
function had no caller outside tests. Kept, it would have forced the proxy
either to allow a tenth endpoint nobody uses, or to break a function that
looked alive because its tests were green. It is deleted instead.

What counts as a call: ``<something>client.info`` referenced anywhere in app
code, called directly or handed to ``asyncio.to_thread`` (the shape the
deleted function used). ``logger.info`` is not on a client and does not match.

COUNTER-CHECK (2026-09-22): red on docker_utils.py:1131 before the deletion,
green after.
"""

import ast
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
NOT_APP_CODE = {".git", "tests", "config", "logs", "node_modules", "__pycache__", ".pytest_cache"}


def _host_info_references(source):
    # ast.walk is breadth-first, so line numbers come unordered.
    return sorted(
        node.lineno
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Attribute)
        and node.attr == "info"
        and isinstance(node.value, ast.Name)
        and node.value.id.lower().endswith("client")
    )


def test_the_detector_sees_both_shapes_and_ignores_the_logger():
    source = (
        "import asyncio\n"
        "async def a(client):\n"
        "    return await asyncio.to_thread(client.info)\n"
        "def b(_docker_client, logger):\n"
        "    logger.info('x')\n"
        "    return _docker_client.info()\n"
    )
    assert _host_info_references(source) == [3, 6]


def test_no_app_code_asks_for_host_info():
    findings = []
    for path in sorted(PROJECT.rglob("*.py")):
        relative = path.relative_to(PROJECT)
        if relative.parts[0] in NOT_APP_CODE:
            continue
        for lineno in _host_info_references(path.read_text(encoding="utf-8")):
            findings.append(f"{relative}:{lineno}")
    assert not findings, "GET /info is not on the proxy allowlist: " + ", ".join(findings)
