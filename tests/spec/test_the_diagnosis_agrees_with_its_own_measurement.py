# -*- coding: utf-8 -*-
"""The diagnostic report must not contradict what it just measured.

THE OPERATOR, 2026-09-26, on the System diagnostics dialog: "check this one
too, whether it works at all."

IT RUNS, AND IT MEASURES WELL. Run against his own container it reported the
port mapping correctly::

    "port_mappings": {"9374": [{"host": "0.0.0.0", "port": "9374"}, ...]}

and then, three lines further down, told him::

    "Check Unraid Docker settings: Host Port 8374 -> Container Port 9374"
    "Access Web UI at: http://[UNRAID-IP]:8374 (default: admin/admin)"

THREE THINGS WRONG IN TWO SENTENCES, all of them knowable:

    the host port    8374, while it had just measured 9374
    the scheme       http, while DDC_TLS_MODE=self-signed answers only HTTPS
    the password     admin/admin, which has never existed - the first-time
                     bootstrap is admin/setup, and only while no password is
                     configured at all

THE LINES WERE NEVER MEASURED. They were three fixed strings appended to
every report for an Unraid host, whether anything was wrong or not - so the
dialog lectured about a port mapping that was in order, using numbers from
somebody's default template rather than from this installation.

IT IS THE VEIN OF THE WHOLE WEEK ONE MORE TIME: a claim the code cannot know,
stated as if measured. And the worst of the three is the password, because it
is the one a reader would act on.

WHAT THE REPORT SAYS NOW: where the panel actually is, built from the mapping
it measured and the TLS mode it runs under - and nothing at all about
credentials. When the mapping could NOT be read, it stays with the advice
that was already there and was written with care (_get_unraid_solutions).

HOW THIS TEST CAN FAIL: a report naming a port, a scheme or a credential that
its own measurement does not support.

COUNTER-CHECK (2026-09-26): red before on all three.
"""

import re

import pytest


@pytest.fixture
def diagnostics(monkeypatch):
    """The real class, with only the two things it asks the host for stubbed.

    Not a double of the report: the question is what get_diagnostic_report
    does with a measurement, so the measurement is what is placed, and every
    line of the method under test runs.
    """
    from app.utils.port_diagnostics import PortDiagnostics

    monkeypatch.setattr(PortDiagnostics, "_detect_container_name",
                        lambda self: "dockerdiscordcontrol")
    monkeypatch.setattr(PortDiagnostics, "_get_host_info",
                        lambda self: {"is_unraid": True, "is_docker": True,
                                      "platform": "alpine", "docker_socket_available": True})

    def make(mappings, known=True, listening=True, tls="self-signed"):
        monkeypatch.setenv("DDC_TLS_MODE", tls) if tls else \
            monkeypatch.delenv("DDC_TLS_MODE", raising=False)
        probe = PortDiagnostics()
        monkeypatch.setattr(PortDiagnostics, "_is_port_listening",
                            lambda self, port: listening)
        monkeypatch.setattr(PortDiagnostics, "_get_docker_port_mappings",
                            lambda self: (mappings, known))
        return probe

    return make


HIS_CONTAINER = {"9374": [{"host": "0.0.0.0", "port": "9374"},
                          {"host": "::", "port": "9374"}]}


def _said(report):
    return " || ".join(report["recommendations"])


# AN ADDRESS, not the word. A first version of the two scheme cases below
# searched the whole text for "http://" and went red on the report's own
# sentence "a plain http:// address will be refused" - the same trap this
# repository has walked into on both sides of a scan several times now. What
# is being asked is what a reader would TYPE, so it matches host and port.
ADDRESS = re.compile(r"(https?)://[^\s|]+:\d+")


def _schemes_offered(report):
    return {match.group(1) for match in ADDRESS.finditer(_said(report))}


def test_it_does_not_hand_out_a_password(diagnostics):
    """THE FINDING THAT MATTERS MOST, because it is the one a reader acts
    on. admin/admin has never been a DDC credential: the first-time
    bootstrap is admin/setup, and it closes the moment a password is set.
    """
    report = diagnostics(HIS_CONTAINER).get_diagnostic_report()

    assert not re.search(r"admin/\w+|default:\s*\w+/", _said(report)), (
        f"the report names a credential pair: {_said(report)}")


def test_it_names_the_port_it_measured(diagnostics):
    """THE FINDING: it measured 9374 and then told him to check 8374."""
    report = diagnostics(HIS_CONTAINER).get_diagnostic_report()
    said = _said(report)

    assert "9374" in said, said
    assert "8374" not in said, (
        f"the report tells him about a host port he does not have - it "
        f"measured {report['port_check']['port_mappings']}: {said}")


def test_it_names_the_scheme_it_runs_under(diagnostics):
    """DDC_TLS_MODE=self-signed answers HTTPS only, and a plain-http address
    is not merely untidy: it is the one thing a reader types."""
    report = diagnostics(HIS_CONTAINER).get_diagnostic_report()

    assert _schemes_offered(report) == {"https"}, _said(report)


def test_without_tls_it_says_http(diagnostics):
    """THE OPPOSITE MISTAKE: a report that always says https would be just
    as wrong for the default installation, which is plain HTTP."""
    report = diagnostics(HIS_CONTAINER, tls="off").get_diagnostic_report()

    assert _schemes_offered(report) == {"http"}, _said(report)


def test_a_different_mapping_is_reported_as_it_is(diagnostics):
    """The counter-check that the number is READ and not swapped for
    another constant: the common Unraid mapping must come out as 8374."""
    report = diagnostics({"9374": [{"host": "0.0.0.0", "port": "8374"}]}).get_diagnostic_report()
    said = _said(report)

    assert "8374" in said, said


def test_when_the_mapping_cannot_be_read_it_keeps_the_advice(diagnostics):
    """Silence is not the answer either. When nothing could be measured -
    no Docker socket, a proxy that will not say - the careful advice that
    was already there is what is left, and it must still be there."""
    report = diagnostics({}, known=False).get_diagnostic_report()
    said = _said(report)

    assert said.strip(), "the report says nothing at all when it cannot measure"
    assert "port" in said.lower(), said


def test_the_report_still_carries_what_it_always_did(diagnostics):
    """The counter-check for a rule met by deleting the field."""
    report = diagnostics(HIS_CONTAINER).get_diagnostic_report()

    assert set(report) >= {"timestamp", "container_name", "host_info",
                           "port_check", "recommendations"}, sorted(report)
    assert report["port_check"]["port_mappings"] == HIS_CONTAINER
    assert report["recommendations"], "the recommendations are gone rather than corrected"
