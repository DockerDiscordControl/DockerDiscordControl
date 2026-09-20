# -*- coding: utf-8 -*-
"""
THE FINDING (review C16, section 34 F5 and F6): two statements in
`app/utils/port_diagnostics.py` do not say what they claim to say.

F5 - `get_diagnostic_report()` builds

    report = {'timestamp': logger.name, ...}

`logger.name` is the fixed string "app.utils.port_diagnostics". The field is
called `timestamp`, so anyone reading the report - or a future caller that logs
or displays it - gets the module's own name where the time of the measurement
should be. Nothing reads the field today, which makes it a trap rather than a
wrong answer on screen.

F6 - `check_port_binding()` matches a Docker port mapping to the web port with

    if str(internal_port).startswith(str(self.EXPECTED_WEB_PORT)):

A prefix match where equality was meant. With EXPECTED_WEB_PORT = 9374, the
port 93745 would be accepted as "the web UI's own mapping". DDC exposes only
the one port today, so nothing misfires in practice - but the check does not
mean what it reads as.

Both are stated as "sure" by the reviewer and both are certain from the code;
what is NOT true is that either produces a wrong answer for an operator today.
They are recorded and fixed as what they are: statements that will be wrong the
moment someone relies on them.

The counter-check (test_the_matching_port_is_still_found) keeps the fix from
turning the port check into "never matches".
"""

import re

import pytest

from app.utils.port_diagnostics import PortDiagnostics


@pytest.fixture
def diagnostics(monkeypatch):
    instance = PortDiagnostics.__new__(PortDiagnostics)
    instance.container_name = "ddc"
    instance.EXPECTED_WEB_PORT = 9374
    instance.host_info = {'is_unraid': False, 'is_docker': True}
    monkeypatch.setattr(instance, "_is_port_listening", lambda port: True, raising=False)
    return instance


def _with_mappings(instance, monkeypatch, mappings):
    monkeypatch.setattr(instance, "_get_docker_port_mappings", lambda: mappings)
    monkeypatch.setattr(instance, "_is_external_port_accessible", lambda port: True)
    monkeypatch.setattr(instance, "_check_internal_port", lambda: True, raising=False)


def test_the_timestamp_field_holds_a_time(diagnostics, monkeypatch):
    """THE FINDING (F5): a field called timestamp must not hold a logger name."""
    monkeypatch.setattr(diagnostics, "check_port_binding", lambda: {'issues': []})

    report = diagnostics.get_diagnostic_report()

    assert "port_diagnostics" not in str(report['timestamp'])
    assert re.match(r"^\d{4}-\d{2}-\d{2}T", str(report['timestamp'])), report['timestamp']


def test_a_longer_port_is_not_the_web_port(diagnostics, monkeypatch):
    """THE FINDING (F6): 93745 only starts with 9374 - it is not it."""
    _with_mappings(diagnostics, monkeypatch, {93745: ['8374']})

    result = diagnostics.check_port_binding()

    assert any("not mapped" in issue for issue in result['issues']), result


def test_the_matching_port_is_still_found(diagnostics, monkeypatch):
    """COUNTER-CHECK: the real mapping must still be recognised."""
    _with_mappings(diagnostics, monkeypatch, {9374: ['8374']})

    result = diagnostics.check_port_binding()

    assert not any("not mapped" in issue for issue in result['issues']), result
    assert result['external_ports'] == ['8374']
