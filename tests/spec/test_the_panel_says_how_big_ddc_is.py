# -*- coding: utf-8 -*-
"""The panel reports DDC's own size and memory, because it can ask.

TWO FIELDS STILL ANSWERED "unknown" after the port mapping was fixed
(9c79dd58), for the same reason and with the same remedy:

    "ddc_image_size":   "unknown",
    "ddc_memory_usage": "unknown",

Both shelled out to a `docker` binary that is deliberately not in the image -
`docker stats`, `docker images` - caught the FileNotFoundError and said
"unknown". That is honest, which is why it was left until now; it is simply
not the best available answer.

DDC'S OWN ALLOWLIST PROXY PERMITS BOTH QUESTIONS: GET /containers/<id>/stats
and GET /images/<name>/json. Asked through it on the operator's machine:

    image     166,222,536 bytes
    memory    169,558,016 of 536,870,912

A LIMIT IS NOT ALWAYS A LIMIT, and this is the trap the mech watchdog fell
into first. A container started WITHOUT --memory is reported with the host's
entire RAM as its limit, so a percentage of it means nothing - that is how a
"90 % of memory" rule once fired at 56 GB on a machine that was fine. When the
reported limit is the host's own total, the usage is given alone and no
percentage is invented.

HOW THIS TEST CAN FAIL: either field claiming a number it could not obtain, or
a percentage computed against a limit that is really the whole machine.

COUNTER-CHECK (2026-09-25): red before - both answered "unknown" whatever
Docker said.
"""

from types import SimpleNamespace

import pytest

from app.utils.port_diagnostics import PortDiagnostics

A_REAL_LIMIT = 512 * 1024 * 1024            # the container's own --memory
HOST_TOTAL = 64 * 1024 * 1024 * 1024        # what Docker reports without one
IN_USE = 169558016                          # measured on the operator's machine
IMAGE_BYTES = 166222536


def _diagnostics(monkeypatch, usage=IN_USE, limit=A_REAL_LIMIT, image=IMAGE_BYTES,
                 reachable=True, host_total=HOST_TOTAL):
    """A PortDiagnostics whose Docker answers what this test decides."""
    import app.utils.port_diagnostics as module

    container = SimpleNamespace(
        attrs={"Config": {"Image": "dockerdiscordcontrol"}},
        stats=lambda stream=False: {"memory_stats": {"usage": usage, "limit": limit}},
    )
    client = SimpleNamespace(
        containers=SimpleNamespace(get=lambda _id: container),
        images=SimpleNamespace(get=lambda _ref: SimpleNamespace(attrs={"Size": image})),
    )

    def _client(timeout):
        if not reachable:
            raise RuntimeError("docker unavailable")
        return client

    monkeypatch.setattr(module, "_own_container_id", lambda: "abc123def456")
    monkeypatch.setattr(module, "_docker_client", _client)
    made = PortDiagnostics.__new__(PortDiagnostics)
    monkeypatch.setattr(made, "_host_memory_total", lambda: host_total, raising=False)
    return made


def test_the_image_size_is_reported(monkeypatch):
    """THE FINDING: 'unknown' for a number the API hands over."""
    answer = _diagnostics(monkeypatch)._get_ddc_image_size()

    assert "158" in answer, answer
    assert "MB" in answer, answer


def test_the_memory_usage_is_reported(monkeypatch):
    """Same shape, same source. 169,558,016 of 536,870,912 is 161 of 512."""
    answer = _diagnostics(monkeypatch)._get_ddc_memory_usage()

    assert "161MB" in answer, answer
    assert "512MB" in answer, answer
    assert "31.6%" in answer, answer


def test_no_percentage_against_the_whole_machine(monkeypatch):
    """THE TRAP. Without --memory, Docker reports the HOST's total as the
    container's limit - a percentage of that is meaningless, and a rule built
    on one once fired at 56 GB on a healthy machine."""
    answer = _diagnostics(monkeypatch, limit=HOST_TOTAL)._get_ddc_memory_usage()

    assert "161MB" in answer, answer
    assert "%" not in answer, f"a percentage of the whole host: {answer}"
    assert "64" not in answer, f"the host's RAM is being shown as DDC's limit: {answer}"


def test_a_real_limit_still_gets_its_percentage(monkeypatch):
    """Counter-check: dropping every percentage would pass the case above and
    lose the one number worth having."""
    answer = _diagnostics(monkeypatch, limit=A_REAL_LIMIT)._get_ddc_memory_usage()

    assert "%" in answer, answer


def test_the_container_is_called_by_its_name(monkeypatch):
    """THE THIRD FIELD, same cause. _detect_container_name ran
    `docker inspect <hostname> --format {{.Name}}` and, when that binary was
    not there, fell back to the hostname - which Docker sets to the short id.
    That is why the page showed "e993e9fb661b" instead of the container's
    name, and why a suggested command once carried a hex string as --name."""
    import app.utils.port_diagnostics as module

    monkeypatch.setattr(module, "_own_container_id", lambda: "abc123def456")
    monkeypatch.setattr(module, "_docker_client", lambda timeout: SimpleNamespace(
        containers=SimpleNamespace(get=lambda _id: SimpleNamespace(name="dockerdiscordcontrol"))))

    assert PortDiagnostics.__new__(PortDiagnostics)._detect_container_name() == "dockerdiscordcontrol"


def test_without_docker_the_id_is_better_than_nothing(monkeypatch):
    """Counter-check on that one: the id is not a NAME, but it does identify
    the container, so it is the right fallback - unlike the memory and size
    fields, where there is no lesser answer to give."""
    import app.utils.port_diagnostics as module

    def _unreachable(timeout):
        raise RuntimeError("docker unavailable")

    monkeypatch.setattr(module, "_own_container_id", lambda: "abc123def456")
    monkeypatch.setattr(module, "_docker_client", _unreachable)

    assert PortDiagnostics.__new__(PortDiagnostics)._detect_container_name() == "abc123def456"


@pytest.mark.parametrize("field", ["_get_ddc_image_size", "_get_ddc_memory_usage"])
def test_without_docker_it_says_unknown(monkeypatch, field):
    """The rule the whole diagnostics file rests on since 9c79dd58: a question
    that could not be answered gets no answer, never an invented one."""
    answer = getattr(_diagnostics(monkeypatch, reachable=False), field)()

    assert answer == "unknown", answer


def test_nothing_shells_out_to_a_docker_binary():
    """From the syntax tree. Both fields called subprocess.run(['docker', ...])
    against a binary the image does not carry - the same mistake the port
    check made, and the reason it claimed a working panel was unreachable."""
    import ast
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "app" / "utils"
              / "port_diagnostics.py").read_text(encoding="utf-8")
    shelling = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call) or "subprocess.run" not in ast.unparse(node.func):
            continue
        for argument in node.args[:1]:
            if "'docker'" in ast.unparse(argument) or '"docker"' in ast.unparse(argument):
                shelling.append(f"line {node.lineno}")

    assert shelling == [], f"still calling a docker binary that is not there: {shelling}"
