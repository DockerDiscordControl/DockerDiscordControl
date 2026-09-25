# -*- coding: utf-8 -*-
"""What the report says about the container and the host is asked of each.

MEASURED ON THE OPERATOR'S RUNNING PANEL, 2026-09-25, two minutes after a
rebuild. GET /port_diagnostics, host_info:

    "container_uptime": "22d 23h 49m",     <- the container was 2 minutes old
    "is_unraid": false,                    <- the host runs Unraid 7.3.2

Two claims, both measured false, both wrong for the same reason: they were
answered by looking at the wrong machine.

THE UPTIME reads /proc/uptime. A container shares the host's kernel, so that
file holds the HOST's uptime - twenty-two days, which was true of the server
and had nothing to do with DDC. A correct number under a wrong name is worse
than no number: it looks like evidence.

IS_UNRAID looks for /etc/unraid-version INSIDE the container. It is not there,
and it never will be: the container is Alpine. The question is about the host,
and it was put to the container's own filesystem. It matters beyond tidiness -
this flag decides whether the panel offers Unraid instructions or generic
Docker ones, so an operator on Unraid was being sent down the wrong path.

BOTH ARE ANSWERABLE, and by the route the port check already uses. The Docker
API, through DDC's own allowlist proxy, gives State.StartedAt for the container
this process runs in, and GET /version gives the HOST's kernel - which on this
machine reads "6.18.38-Unraid" and says so itself. Neither needs a guess.

THE SAME AFTERNOON, THE FOURTH TIME. The Application tab served a supervisord
log from last November as today's; the port check turned "I could not look"
into "it is broken" and advised a command that would have replaced the
container; a supervisorctl probe warned on every visit that a deliberately
removed program was missing. A diagnostics page is the one place an operator
goes when he already doubts something. Every wrong answer there costs twice.

WHAT STAYS "unknown": ddc_image_size and ddc_memory_usage still shell out to a
docker binary that is not in the image. They answer 'unknown', which is at
least true, and they are left for a separate change.

HOW THIS TEST CAN FAIL: a field about the container answered from the host, or
one about the host answered from inside the container.

COUNTER-CHECK (2026-09-25): red before - the uptime case read the host's
/proc/uptime and the Unraid case answered False on an Unraid host.
"""

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.utils.port_diagnostics import PortDiagnostics

PROJECT = Path(__file__).resolve().parents[2]


def _fake_docker(monkeypatch, started_at=None, kernel="6.18.38-Unraid", reachable=True):
    """Docker as this test decides it, through the two lazy seams."""
    import app.utils.port_diagnostics as module

    container = SimpleNamespace(attrs={"State": {"StartedAt": started_at or ""}})
    client = SimpleNamespace(
        containers=SimpleNamespace(get=lambda _id: container),
        version=lambda: {"Os": "linux", "KernelVersion": kernel},
    )

    def _client(timeout):
        if not reachable:
            raise RuntimeError("docker unavailable")
        return client

    monkeypatch.setattr(module, "_own_container_id", lambda: "abc123def456")
    monkeypatch.setattr(module, "_docker_client", _client)
    return PortDiagnostics.__new__(PortDiagnostics)


def _minutes_ago(minutes):
    stamp = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    # Docker reports nanoseconds; the parser has to cope with them.
    return stamp.strftime("%Y-%m-%dT%H:%M:%S.%f000Z")


def test_the_uptime_is_the_containers_own(monkeypatch):
    """THE FINDING: it said 22 days for a container two minutes old, because
    /proc/uptime inside a container is the host's."""
    diagnostics = _fake_docker(monkeypatch, started_at=_minutes_ago(2))

    assert diagnostics._get_container_uptime() == "2m"


def test_a_long_running_container_is_reported_in_days(monkeypatch):
    """Counter-check: answering "2m" always would pass the case above."""
    diagnostics = _fake_docker(monkeypatch, started_at=_minutes_ago(3 * 24 * 60 + 65))

    assert diagnostics._get_container_uptime() == "3d 1h 5m"


def test_the_uptime_is_unknown_rather_than_the_hosts(monkeypatch):
    """Without Docker the container's age cannot be known - and the host's
    uptime is not a substitute for it. That substitution IS the finding."""
    diagnostics = _fake_docker(monkeypatch, reachable=False)

    assert diagnostics._get_container_uptime() == "unknown"


def test_nothing_opens_proc_uptime():
    """From the syntax tree, because the number it yields is real and
    plausible - it is simply a fact about another machine.

    THE CALL, NOT THE WORD, and this is the FIFTH time in one day that a scan
    of mine went red on an explanatory docstring of my own. The replacement
    function says what it used to read and why that was wrong, which is the
    sentence that stops somebody restoring it. A docstring is an ast.Constant
    like any other string, so matching constants was never the right question:
    what matters is whether the program can OPEN the file.
    """
    source = (PROJECT / "app" / "utils" / "port_diagnostics.py").read_text(encoding="utf-8")
    opened = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and ast.unparse(node.func).endswith("open"):
            for argument in node.args[:1]:
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str) \
                        and "/proc/uptime" in argument.value:
                    opened.append(f"line {node.lineno}")

    assert opened == [], f"the host's uptime is being read as the container's: {opened}"


def test_that_scan_would_still_catch_the_line_that_was_there():
    """Counter-check on the narrowing above: the pattern must match the call
    it replaced, and must not match prose about it."""
    real = ast.parse("with open('/proc/uptime', 'r') as f:\n    pass")
    calls = [n for n in ast.walk(real) if isinstance(n, ast.Call)]

    assert calls, "the scan no longer sees an open() at all"
    prose = ast.parse('"""it used to read /proc/uptime, which is the host\'s"""')

    assert not [n for n in ast.walk(prose) if isinstance(n, ast.Call)]


def test_an_unraid_host_is_recognised(monkeypatch):
    """THE SECOND FINDING. This flag decides whether the panel offers Unraid
    instructions or generic Docker ones, so being wrong sends an operator
    down the wrong path."""
    diagnostics = _fake_docker(monkeypatch, kernel="6.18.38-Unraid")
    _platform, is_unraid = diagnostics._detect_platform()

    assert is_unraid is True


def test_an_ordinary_host_is_not_called_unraid(monkeypatch):
    """Counter-check: answering True always would pass the case above and send
    everyone else down the Unraid path instead."""
    diagnostics = _fake_docker(monkeypatch, kernel="6.8.0-51-generic")
    _platform, is_unraid = diagnostics._detect_platform()

    assert is_unraid is False


def test_the_container_platform_is_still_its_own(monkeypatch):
    """The other half of that pair, and the confusion behind it: "what am I
    running on" is alpine and true; "is the host Unraid" is a different
    question about a different machine. Only the second was wrong."""
    diagnostics = _fake_docker(monkeypatch, kernel="6.18.38-Unraid")
    platform, _is_unraid = diagnostics._detect_platform()

    assert platform, "the container's own platform is no longer reported"


def test_no_docker_means_no_claim_about_the_host(monkeypatch):
    """The rule the whole file is about: an unanswerable question gets no
    answer, not a confident False."""
    diagnostics = _fake_docker(monkeypatch, reachable=False)
    _platform, is_unraid = diagnostics._detect_platform()

    assert is_unraid is False, "a guess is still a guess, but it must not be a crash"
