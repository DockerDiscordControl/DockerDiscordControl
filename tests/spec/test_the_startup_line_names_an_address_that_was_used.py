# -*- coding: utf-8 -*-
"""The startup line points at an address somebody has actually reached.

THE OPERATOR (2026-09-25), with his own startup log:

    Starting IP detection (looking for host IP)...
    Trying traceroute method to find host IP...
    Trying standard Docker host detection as fallback...
    Docker host gateway: 172.17.0.1
    WARNING All host IP detection methods failed, returning None
    Web UI: http://localhost:9374

"We work out the local IP at container start for some feature - I think for the
login line at the end in the console - but it does not work reliably. Did you
find a way?"

I had, an hour earlier and for something else. THE DIAGNOSTICS GUESS FROM THE
INSIDE: traceroute to 8.8.8.8 and read the second hop, the Docker gateway, an
environment variable somebody may have set. All three are attempts to work out,
from inside a container, an address that belongs to the host - and on his
machine all three fail, so the line tells him localhost, which is the one
address that is useless when he is reading it from another computer.

THE CERTIFICATE ALREADY KNOWS. Since this morning the panel learns every
address it is reached on - from SNI, from the redirect, and from the Host of
every request - and keeps them beside the certificate, because a certificate
has to name them. That is not a guess: it is where somebody actually went.
His file already held 192.168.1.249 before this change was written.

WHAT IT STILL CANNOT DO, and does not pretend to: on an installation nobody
has visited yet there is nothing to have learned, and the line falls back to
the old guessing and then to localhost. An address can be observed or guessed;
it cannot be known before anybody has been.

THE SCHEME FOLLOWS THE TLS MODE. The line said http:// on a panel that answers
only https since yesterday - a link that redirects at best.

HOW THIS TEST CAN FAIL: a line that goes back to guessing first, one that
offers an address only the container can reach, or one that names the wrong
scheme.

COUNTER-CHECK (2026-09-25): red before - nothing consulted the learned
addresses, and the case that gives it one found it guessing anyway.
"""

import json
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[2]


@pytest.fixture
def diagnostics(tmp_path, monkeypatch):
    """The service, with a configuration directory of this test's own."""
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    for leftover in ("HOST_IP", "UNRAID_IP", "SERVER_IP"):
        monkeypatch.delenv(leftover, raising=False)
    from app.utils.port_diagnostics import PortDiagnostics

    service = PortDiagnostics()
    # THE GUESSING IS SILENCED BY DEFAULT, because this file is about what the
    # LEARNED addresses contribute and the guessing is what happens after them.
    #
    # Two cases here asserted "nothing is offered" and were green only because
    # the guessing happened to fail on the machines they ran on. On a GitHub
    # runner it succeeds - the first CI run this branch ever had, 2026-09-26,
    # returned 10.1.0.1 for both - so they were passing for a reason that has
    # nothing to do with their rule. The two cases that are ABOUT the guessing
    # set their own stubs below and override this.
    monkeypatch.setattr(service, "_try_traceroute_ip", lambda: None)
    monkeypatch.setattr(service, "_try_docker_host_gateway", lambda: None)
    return service, tmp_path


def _learned(directory, *names):
    tls = Path(directory) / "tls"
    tls.mkdir(parents=True, exist_ok=True)
    (tls / "known_names.json").write_text(json.dumps(sorted(names)), encoding="utf-8")


def test_an_address_that_was_used_is_the_answer(diagnostics):
    """THE FINDING: it guessed, failed, and said localhost."""
    service, directory = diagnostics
    _learned(directory, "192.168.1.249", "127.0.0.1", "localhost")

    assert service._get_actual_host_ip() == "192.168.1.249"


def test_nothing_useless_is_offered(diagnostics):
    """localhost and the loopback address ARE reached - from inside the
    container, and from the health check. Naming one of them in a line an
    operator reads on another computer is the failure this replaces."""
    service, directory = diagnostics
    _learned(directory, "127.0.0.1", "localhost", "::1")

    assert service._get_actual_host_ip() in (None, ""), service._get_actual_host_ip()


def test_a_hostname_counts_too(diagnostics):
    """Not everybody reaches the panel by address."""
    service, directory = diagnostics
    _learned(directory, "ddc.local", "127.0.0.1")

    assert service._get_actual_host_ip() == "ddc.local"


def test_nothing_learned_yet_falls_back(diagnostics, monkeypatch):
    """A fresh installation nobody has visited. It must go on to the old
    guessing rather than raise - and say localhost if that fails too, which is
    honest: nothing has been observed."""
    service, _directory = diagnostics
    monkeypatch.setattr(service, "_try_traceroute_ip", lambda: None)
    monkeypatch.setattr(service, "_try_docker_host_gateway", lambda: None)

    assert service._get_actual_host_ip() in (None, "")


def test_the_observed_address_wins_over_a_guess(diagnostics, monkeypatch):
    """A measured address beats one worked out from a routing table - and
    asking first also saves spawning traceroute on every start."""
    service, directory = diagnostics
    _learned(directory, "192.168.1.249")
    monkeypatch.setattr(service, "_try_traceroute_ip",
                        lambda: pytest.fail("guessed before asking what was observed"))
    monkeypatch.setattr(service, "_try_docker_host_gateway",
                        lambda: pytest.fail("guessed before asking what was observed"))

    assert service._get_actual_host_ip() == "192.168.1.249"


def test_an_unreadable_memory_does_not_stop_the_start(diagnostics):
    """It sits in a directory an operator can edit, and this runs during
    startup."""
    service, directory = diagnostics
    tls = Path(directory) / "tls"
    tls.mkdir(parents=True, exist_ok=True)
    (tls / "known_names.json").write_text("{not json", encoding="utf-8")

    # Must not raise - and must not invent an address out of a broken file.
    assert service._get_actual_host_ip() in (None, "")


@pytest.mark.parametrize("mode,scheme", [("self-signed", "https"), ("off", "http")])
def test_the_line_names_the_right_scheme(diagnostics, monkeypatch, mode, scheme, caplog):
    """It said http:// on a panel that answers only https."""
    import logging

    service, directory = diagnostics
    _learned(directory, "192.168.1.249")
    monkeypatch.setenv("DDC_TLS_MODE", mode)
    with caplog.at_level(logging.INFO):
        service.log_startup_diagnostics()
    said = " ".join(record.message for record in caplog.records)

    assert f"{scheme}://192.168.1.249:9374" in said, said[-300:]
