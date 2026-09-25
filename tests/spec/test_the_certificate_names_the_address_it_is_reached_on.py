# -*- coding: utf-8 -*-
"""The self-signed certificate learns the addresses it is reached on.

THE OPERATOR (2026-09-25), on his browser still saying "not secure": "I think
the 'not secure' comes from the certificate." It did. Read off his running
container:

    Subject: CN=DockerDiscordControl
    SAN:     DNS localhost, IP 127.0.0.1, DNS 1364b5341e94

`1364b5341e94` is the CONTAINER's own hostname. The address he opens the panel
on - 192.168.1.249 - was nowhere in it. A browser checks the name first, so he
could have trusted that certificate as often as he liked and been warned every
time. It was built from the container's view of itself, and a container cannot
see the address somebody reaches it on.

MY FIRST FIX WAS TO PASS THE HOST ADDRESS IN FROM THE DEPLOY SCRIPT, and he
stopped it: "that has to be dynamic, users can give the DDC container any
address they like." He is right. A list written at deploy time covers one
installation - not a hostname, not a Tailscale address, not a second network,
not the name a reverse proxy uses.

SO IT LEARNS, from the two places where the address arrives BEFORE the
certificate is needed:

  SNI       the TLS handshake carries the name the browser asked for, and it
            carries it before the certificate is sent. An unknown name is
            added, the certificate reissued and swapped into THIS handshake,
            so even the first visit gets a matching one. Hostnames only - a
            connection to a bare IP sends no SNI, by design.

  the       a plain HTTP request carries a Host header and happens before any
  redirect  TLS at all. That is where an IP address is learned, which is the
            case SNI cannot cover.

  the       every request carries the address it was aimed at. This is the
  request   only source that sees a bookmark on https://<ip>: a bare address
            sends no SNI and never passes the redirect. The operator clicks
            through the warning once, the address is learned, and the next
            certificate names it.

  the env   DDC_TLS_HOSTNAMES, for anything none of them ever sees.

What is learned is kept beside the certificate, so a restart does not forget
it, and a name is only ever added - never dropped because somebody used a
different one today.

NOT ON EVERY START. A new certificate means a new fingerprint and another round
of trusting it, so one is issued only when a name is genuinely missing, or the
old one is near expiry.

HOW THIS TEST CAN FAIL: a certificate that cannot learn, one that forgets
across a restart, or one reissued when nothing changed.

COUNTER-CHECK (2026-09-25): red before - nothing learned anything, and a
certificate missing every requested name was handed back unchanged.
"""

import datetime
import ipaddress
import json
from pathlib import Path

import pytest


def _san(cert_path: Path):
    from cryptography import x509

    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    return {str(entry.value) for entry in san}


# --- what is in the certificate ----------------------------------------------

def test_the_names_it_is_asked_for_are_in_it(tmp_path):
    """THE FINDING: the address he opens the panel on was nowhere in it."""
    from app.web.tls import ensure_self_signed_certificate

    certificate = ensure_self_signed_certificate(tmp_path, hostnames=["192.168.1.249", "ddc.local"])

    assert {"192.168.1.249", "ddc.local"} <= _san(certificate.cert_path)


def test_the_usual_names_are_still_in_it(tmp_path):
    """Counter-check: the extras are added, they do not replace. Reaching the
    panel from inside the container must keep working."""
    from app.web.tls import ensure_self_signed_certificate

    names = _san(ensure_self_signed_certificate(tmp_path, hostnames=["10.0.0.5"]).cert_path)

    assert {"localhost", "127.0.0.1"} <= names


def test_an_address_is_filed_as_an_address_and_a_name_as_a_name(tmp_path):
    """A browser matches an IP against the IP entries and a hostname against
    the DNS ones; an address filed as a name matches nothing."""
    from cryptography import x509

    from app.web.tls import ensure_self_signed_certificate

    certificate = ensure_self_signed_certificate(tmp_path, hostnames=["192.168.1.249", "ddc.local"])
    cert = x509.load_pem_x509_certificate(certificate.cert_path.read_bytes())
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value

    assert ipaddress.ip_address("192.168.1.249") in san.get_values_for_type(x509.IPAddress)
    assert "ddc.local" in san.get_values_for_type(x509.DNSName)


# --- when a new one is issued -------------------------------------------------

def test_a_missing_name_is_a_reason_to_issue_a_new_one(tmp_path):
    """THE HALF THAT REACHES AN EXISTING INSTALLATION. His certificate already
    existed, and one that is not near expiry used to be handed back whatever
    it named."""
    from app.web.tls import ensure_self_signed_certificate

    first = ensure_self_signed_certificate(tmp_path)

    assert "192.168.1.249" not in _san(first.cert_path)
    second = ensure_self_signed_certificate(tmp_path, hostnames=["192.168.1.249"])

    assert second.created is True, "kept although a name was missing"
    assert "192.168.1.249" in _san(second.cert_path)


def test_nothing_is_reissued_when_nothing_is_missing(tmp_path):
    """A new certificate is a new fingerprint and another round of trusting
    it."""
    from app.web.tls import ensure_self_signed_certificate

    first = ensure_self_signed_certificate(tmp_path, hostnames=["192.168.1.249"])
    second = ensure_self_signed_certificate(tmp_path, hostnames=["192.168.1.249"])

    assert second.created is False
    assert second.fingerprint == first.fingerprint


def test_expiry_is_still_a_reason(tmp_path):
    """Counter-check on the new condition: it must not have replaced the old
    one."""
    from app.web.tls import ensure_self_signed_certificate

    first = ensure_self_signed_certificate(tmp_path, hostnames=["a.local"])
    second = ensure_self_signed_certificate(tmp_path, hostnames=["a.local"],
                                            now=first.not_after - datetime.timedelta(days=1))

    assert second.created is True


# --- learning -----------------------------------------------------------------

def test_a_new_address_is_remembered(tmp_path):
    from app.web.tls import known_names, remember_name

    assert remember_name(tmp_path, "192.168.1.249") is True
    assert "192.168.1.249" in known_names(tmp_path)


def test_it_is_still_remembered_after_a_restart(tmp_path):
    """Kept beside the certificate: a restart that forgot would reissue on the
    next visit, every time."""
    from app.web.tls import known_names, remember_name

    remember_name(tmp_path, "ddc.local")

    assert "ddc.local" in known_names(tmp_path)          # read fresh from disk
    assert json.loads((tmp_path / "known_names.json").read_text(encoding="utf-8"))


def test_the_same_address_twice_is_not_news(tmp_path):
    """It is what decides whether to reissue, so saying yes twice would mean a
    new certificate on every single visit."""
    from app.web.tls import remember_name

    assert remember_name(tmp_path, "ddc.local") is True
    assert remember_name(tmp_path, "ddc.local") is False


@pytest.mark.parametrize("rubbish", ["", "   ", "not a hostname!", "a" * 300,
                                     "../../etc/passwd", "*.evil.test"])
def test_rubbish_is_not_remembered(tmp_path, rubbish):
    """These arrive from the network, from anybody who can reach the port. A
    name is only kept when it is one."""
    from app.web.tls import known_names, remember_name

    assert remember_name(tmp_path, rubbish) is False
    assert known_names(tmp_path) == []


def test_a_name_is_never_dropped(tmp_path):
    """Two addresses reach the same panel, and using one today must not stop
    the other from working tomorrow."""
    from app.web.tls import known_names, remember_name

    remember_name(tmp_path, "192.168.1.249")
    remember_name(tmp_path, "ddc.local")

    assert set(known_names(tmp_path)) == {"192.168.1.249", "ddc.local"}


def test_what_was_learned_lands_in_the_certificate(tmp_path):
    from app.web.tls import ensure_self_signed_certificate, remember_name

    remember_name(tmp_path, "tailscale-name.ts.net")

    assert "tailscale-name.ts.net" in _san(ensure_self_signed_certificate(tmp_path).cert_path)


def test_an_unreadable_memory_does_not_stop_the_start(tmp_path):
    """The file sits in a directory an operator can edit."""
    from app.web.tls import known_names

    (tmp_path).mkdir(parents=True, exist_ok=True)
    (tmp_path / "known_names.json").write_text("{not json", encoding="utf-8")

    assert known_names(tmp_path) == []


# --- the two places it learns from --------------------------------------------

def test_the_handshake_learns_the_name_the_browser_asked_for():
    """SNI carries it before the certificate is sent, which is why even a
    first visit can get a matching one."""
    import ast

    source = (Path(__file__).resolve().parents[2] / "app" / "web" / "tls.py").read_text(
        encoding="utf-8")
    tree = ast.parse(source)
    assigns = [ast.unparse(node) for node in ast.walk(tree) if isinstance(node, ast.Assign)]

    assert any("sni_callback" in a for a in assigns), (
        "nothing listens to the name the browser asks for")


def test_the_redirect_learns_the_host_it_was_asked_for():
    """A plain HTTP request carries a Host and happens before any TLS - the
    only place an IP address can be learned, since an IP sends no SNI."""
    import ast

    source = (Path(__file__).resolve().parents[2] / "app" / "web" / "tls.py").read_text(
        encoding="utf-8")
    tree = ast.parse(source)
    functions = {node.name: node for node in ast.walk(tree)
                 if isinstance(node, ast.FunctionDef)}

    # Follow the call rather than searching one function for a word: the
    # learning sits in a helper, and a test that insisted on the name being
    # written inside the redirect would fail for a tidier arrangement while
    # passing for a broken one.
    redirect = ast.unparse(functions["_answer_with_a_redirect"])
    learner = next((name for name in functions
                    if name != "_answer_with_a_redirect" and f"{name}(" in redirect
                    and "remember_name" in ast.unparse(functions[name])), None)

    assert learner, ("the redirect throws away the only address an IP-only "
                     "client ever sends")
    assert "Host" in ast.unparse(functions[learner]) or "host" in ast.unparse(functions[learner])


# --- against a running server -------------------------------------------------

def test_a_first_visit_under_a_new_name_already_gets_a_matching_certificate(tmp_path):
    """THE WHOLE POINT, end to end and against a real handshake.

    A browser asking for a hostname the certificate does not carry would
    normally be warned. SNI arrives before the certificate is sent, so the
    name is learned, a new certificate issued and swapped into this very
    handshake - the client sees one that names it, on the first try.
    """
    import socket
    import ssl as ssl_module
    import threading

    from flask import Flask

    from app.web import tls

    app = Flask(__name__)

    @app.route("/health")
    def health():
        return "ok"

    certificate = tls.ensure_self_signed_certificate(tmp_path)

    assert "panel.example.test" not in _san(certificate.cert_path), "the name is already known"

    server = tls.make_tls_server(app, "127.0.0.1", 0, certificate)
    port = server.socket.getsockname()[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        context = ssl_module._create_unverified_context()
        with socket.create_connection(("127.0.0.1", port), timeout=10) as raw:
            with context.wrap_socket(raw, server_hostname="panel.example.test") as tls_sock:
                served = tls_sock.getpeercert(binary_form=True)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    from cryptography import x509

    cert = x509.load_der_x509_certificate(served)
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    names = {str(entry.value) for entry in san}

    assert "panel.example.test" in names, (
        f"the certificate served in the handshake does not name it: {sorted(names)}")
    assert "panel.example.test" in known_names_of(tmp_path), "it was not remembered either"


def known_names_of(directory):
    from app.web.tls import known_names

    return known_names(directory)


def test_a_request_teaches_it_the_address_it_was_aimed_at(tmp_path):
    """THE SOURCE FOR A BOOKMARK ON AN IP, which neither of the others sees."""
    from flask import Flask

    from app.web import tls

    app = Flask(__name__)

    @app.route("/health")
    def health():
        return "ok"

    tls.learn_from_requests(app, tmp_path)
    app.test_client().get("/health", headers={"Host": "192.168.1.249:9374"})

    assert "192.168.1.249" in known_names_of(tmp_path)


def test_the_port_does_not_come_along(tmp_path):
    """A certificate names addresses, never address-and-port."""
    from flask import Flask

    from app.web import tls

    app = Flask(__name__)

    @app.route("/health")
    def health():
        return "ok"

    tls.learn_from_requests(app, tmp_path)
    app.test_client().get("/health", headers={"Host": "ddc.local:9374"})

    assert known_names_of(tmp_path) == ["ddc.local"]


def test_the_process_wires_that_up():
    import ast

    source = (Path(__file__).resolve().parents[2] / "run.py").read_text(encoding="utf-8")
    called = {ast.unparse(node.func) for node in ast.walk(ast.parse(source))
              if isinstance(node, ast.Call)}

    assert any("learn_from_requests" in name for name in called), (
        "nothing teaches the certificate the address a bookmark uses")


def test_a_new_container_does_not_cost_a_new_certificate(tmp_path, monkeypatch):
    """THE COST OF GETTING THIS WRONG: trusting it again after every rebuild.

    Docker gives each container a hostname, and that hostname is its id - a new
    one on every rebuild. It is put IN the certificate, which is harmless, but
    requiring it was not: the name was missing from yesterday's certificate by
    definition, so every rebuild issued a new one with a new fingerprint, and
    every browser warned again.

    Measured on the operator's own server: two rebuilds, two fingerprints, and
    the second one arrived within the hour (2026-09-25).

    Nobody browses to a container id. It is offered, never required.
    """
    import socket

    from app.web.tls import ensure_self_signed_certificate

    monkeypatch.setattr(socket, "gethostname", lambda: "1364b5341e94")
    first = ensure_self_signed_certificate(tmp_path, hostnames=["192.168.1.249"])

    assert "1364b5341e94" in _san(first.cert_path), "the container is not named at all"

    monkeypatch.setattr(socket, "gethostname", lambda: "0fbaede411b9")
    second = ensure_self_signed_certificate(tmp_path, hostnames=["192.168.1.249"])

    assert second.created is False, "a rebuild cost a new certificate and a new trust step"
    assert second.fingerprint == first.fingerprint


def test_an_address_that_was_learned_is_still_required(tmp_path, monkeypatch):
    """Counter-check: excusing the container's own name must not excuse the
    ones that matter, or the certificate would stop following the operator."""
    import socket

    from app.web.tls import ensure_self_signed_certificate, remember_name

    monkeypatch.setattr(socket, "gethostname", lambda: "1364b5341e94")
    ensure_self_signed_certificate(tmp_path)
    remember_name(tmp_path, "ddc.local")

    assert ensure_self_signed_certificate(tmp_path).created is True
