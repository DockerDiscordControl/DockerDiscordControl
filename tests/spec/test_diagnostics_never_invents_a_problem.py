# -*- coding: utf-8 -*-
"""A diagnosis it could not make is not reported as a fault.

MEASURED ON THE OPERATOR'S RUNNING PANEL, 2026-09-25, two minutes after a
rebuild. GET /port_diagnostics answered:

    "issues": ["Port 9374 not mapped to any external port"],
    "solutions": [
      "DOCKER FIX: Add port mapping: -p 8374:9374",
      "DOCKER FIX: Recreate container with: docker run -d --name e993e9fb661b
       -p 8374:9374 dockerdiscordcontrol/dockerdiscordcontrol:latest",
      ...
    ]

The port IS mapped. `docker inspect` says 9374/tcp -> 0.0.0.0:9374, and the
panel that printed this was served through it.

AND THE "SOLUTION" WOULD HAVE DESTROYED THE INSTALLATION. That docker run line
carries no -v, so it creates a container with no config directory, no logs and
no Mech state, named after a hex id. An operator who trusted it would lose
everything and gain a second container fighting the first for the port.

WHY IT HAPPENED, and the code says so itself:

    except (FileNotFoundError, subprocess.TimeoutExpired):
        # Docker command not available - this is normal inside containers
        return {}

It shells out to a `docker` binary that is deliberately not in the image,
catches the failure, and returns an empty mapping - which the caller reads as
"nothing is mapped". "I could not look" became "it is broken", and then
advice. This is the same disease as an INFO line announcing work it does not
do, in its most damaging form: not noise, not untruth about the past, but a
wrong instruction about what to do next.

IT DOES NOT HAVE TO GUESS. DDC reaches Docker through its own allowlist proxy,
which permits GET /containers/<name>/json - exactly what this needs - and
self_restart.py already identifies the container DDC runs in. The mapping is
read from the API, through the sanctioned client, and "could not determine" is
kept as its own answer rather than being flattened into "no".

HOW THIS TEST CAN FAIL: an unanswerable question reported as a fault, or a
suggested command that would replace the operator's container.

COUNTER-CHECK (2026-09-25): red before - the case with no Docker access found
an issue raised and four solutions offered.
"""

from unittest.mock import MagicMock

import pytest

from app.utils.port_diagnostics import PortDiagnostics


class _Container:
    def __init__(self, ports):
        self.name = "dockerdiscordcontrol"
        self.attrs = {"NetworkSettings": {"Ports": ports}}


def _diagnostics(monkeypatch, ports=None, reachable=True, container_id="e993e9fb661b"):
    """A PortDiagnostics whose Docker access is decided by this test."""
    import app.utils.port_diagnostics as module

    monkeypatch.setattr(module, "_own_container_id", lambda: container_id)

    def _client(*_args, **_kwargs):
        if not reachable:
            raise RuntimeError("docker socket unavailable")
        client = MagicMock()
        client.containers.get.return_value = _Container(ports or {})
        return client

    monkeypatch.setattr(module, "_docker_client", _client)
    made = PortDiagnostics()
    # The internal listen check is a different question with its own answer,
    # and in a test process nothing is listening on 9374. Left alone it would
    # short-circuit every case here before the mapping is even looked at.
    monkeypatch.setattr(made, "_is_port_listening", lambda port: True)
    return made


MAPPED = {"9374/tcp": [{"HostIp": "0.0.0.0", "HostPort": "9374"}]}


def test_a_mapped_port_is_not_a_problem(monkeypatch):
    """THE FINDING: this is his actual container, and it was called broken."""
    result = _diagnostics(monkeypatch, ports=MAPPED).check_port_binding()

    assert result["issues"] == [], result["issues"]
    assert result["solutions"] == [], result["solutions"]


def test_the_mapping_is_read_from_the_api(monkeypatch):
    """Counter-check: reporting nothing at all would pass the case above. The
    mapping has to actually come back."""
    result = _diagnostics(monkeypatch, ports=MAPPED).check_port_binding()

    assert result["port_mappings"], "the mapping was not read"
    assert any(entry.get("port") == "9374"
               for entries in result["port_mappings"].values() for entry in entries), result


def test_no_docker_access_raises_no_issue(monkeypatch):
    """THE CASE THAT MATTERS. Without Docker the question cannot be answered -
    and an unanswerable question is not a fault."""
    result = _diagnostics(monkeypatch, reachable=False).check_port_binding()

    assert result["issues"] == [], (
        f"a question it could not answer was reported as a fault: {result['issues']}")
    assert result["solutions"] == [], result["solutions"]


def test_not_being_in_a_container_raises_no_issue(monkeypatch):
    """Run from a checkout there is no container to inspect, and no port to
    map. Silence, not an accusation."""
    result = _diagnostics(monkeypatch, container_id=None).check_port_binding()

    assert result["issues"] == [], result["issues"]


def test_a_genuinely_unmapped_port_is_still_reported(monkeypatch):
    """The opposite mistake: staying quiet about everything would pass all the
    cases above and make the check worthless. A container that really has no
    mapping is a real problem an operator wants to hear about."""
    result = _diagnostics(monkeypatch, ports={"9374/tcp": None}).check_port_binding()

    assert any("not mapped" in issue for issue in result["issues"]), result["issues"]


def test_no_suggestion_would_replace_the_container(monkeypatch):
    """THE DANGEROUS HALF. Even when the port really is unmapped, `docker run`
    without the operator's volumes builds a container with no configuration,
    no logs and no Mech state - and a second one fighting for the port."""
    result = _diagnostics(monkeypatch, ports={"9374/tcp": None}).check_port_binding()

    for advice in result["solutions"]:

        assert "docker run" not in advice, f"this would replace his container: {advice}"
        assert "Recreate" not in advice, f"this would replace his container: {advice}"


def test_something_useful_is_still_suggested(monkeypatch):
    """Counter-check on the case above: deleting every suggestion would pass
    it and leave an operator with a real problem and no way forward."""
    result = _diagnostics(monkeypatch, ports={"9374/tcp": None}).check_port_binding()

    assert result["solutions"], "a real problem is reported with nothing to do about it"
