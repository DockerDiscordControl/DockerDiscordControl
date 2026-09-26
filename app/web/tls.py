# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""TLS for the web panel: off, behind a reverse proxy, or a self-signed fallback.

v3.0 step 8 (docs/V3_ARCHITECTURE_PLAN.md §5.1). Operator decision 2026-09-22:
both ways - a reverse proxy is recommended, a self-signed certificate is the
fallback for installations without one - and 2FA only over TLS.

``DDC_TLS_MODE``:

* ``off`` (default): plain HTTP, as before v3.0. The session cookie stays
  non-Secure; a Secure cookie is never sent over HTTP.
* ``proxy``: TLS ends at the operator's proxy. The cookie is Secure and a
  request that did not arrive over HTTPS through a trusted proxy
  (``DDC_TRUSTED_PROXIES``, see app/web/extensions.py) is refused, except
  ``/health``. Otherwise the proxy would be optional.
* ``self-signed``: DDC serves HTTPS itself with a certificate kept in
  ``config/tls``, created on first start and renewed at start when it has
  less than RENEW_BEFORE left. Its SHA-256 fingerprint is logged for the
  trust step.

An unknown mode raises instead of falling back to plain HTTP.
"""

from __future__ import annotations

import datetime
import hashlib
import ipaddress
import json
import re
import logging
import os
import socket
import ssl
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Optional

from flask import Flask, Response, request

logger = logging.getLogger("ddc.web.tls")

TLS_MODE_ENV = "DDC_TLS_MODE"
TRUSTED_PROXIES_ENV = "DDC_TRUSTED_PROXIES"  # the same name app/web/extensions.py reads
TLS_HOSTNAMES_ENV = "DDC_TLS_HOSTNAMES"
MODES = ("off", "proxy", "self-signed")
VALIDITY = datetime.timedelta(days=825)
RENEW_BEFORE = datetime.timedelta(days=60)
CERT_NAME = "ddc.crt"
KEY_NAME = "ddc.key"


def tls_mode(env: Mapping[str, str]) -> str:
    """The configured mode; raises ValueError for anything unknown."""
    value = (env.get(TLS_MODE_ENV) or "off").strip().lower()
    if value not in MODES:
        raise ValueError(
            f"{TLS_MODE_ENV}={value!r} is not one of {', '.join(MODES)} - refusing to start "
            f"rather than serving plain HTTP where TLS was asked for"
        )
    return value


def apply_tls_mode(app: Flask, mode: Optional[str] = None) -> None:
    """Set the cookie flag for the mode and, behind a proxy, refuse plain access.

    Without ``mode`` it takes ``app.config["DDC_TLS_MODE"]``, so create_app calls
    it like every other setup step, with the app alone.
    """
    if mode is None:
        mode = app.config.get("DDC_TLS_MODE", "off")
    if mode == "off":
        return
    app.config["SESSION_COOKIE_SECURE"] = True
    app.config["PREFERRED_URL_SCHEME"] = "https"
    if mode != "proxy":
        return
    # Without a trust list request.scheme never becomes https, so the check below
    # would refuse EVERY request while /health kept answering 200 - a panel that
    # cannot be opened behind a healthy-looking container. Say it at the start.
    if not app.config.get("DDC_TRUSTED_NETWORKS"):
        raise ValueError(
            f"{TLS_MODE_ENV}=proxy needs {TRUSTED_PROXIES_ENV} - the address or range of "
            f"your reverse proxy. Without it DDC cannot tell an HTTPS request from your "
            f"proxy apart from a plain one, and would refuse every request."
        )

    @app.before_request
    def _https_through_the_proxy_only():
        # request.scheme is https only when the peer is a trusted proxy that
        # said so (TrustedProxyFix), or when the connection itself is TLS. A
        # client reaching the port directly cannot make it https by a header.
        if request.path == "/health" or request.scheme == "https":
            return None
        return Response(
            "DDC runs with DDC_TLS_MODE=proxy: open it through your reverse proxy over HTTPS.\n",
            status=403,
            mimetype="text/plain",
        )


def learn_from_requests(app: Flask, directory) -> None:
    """Remember the address each request was aimed at.

    THE CASE NEITHER OTHER SOURCE COVERS, and it is the common one: an
    operator with a bookmark on https://<ip>:9374. A bare address sends no
    SNI, so the handshake cannot learn it, and there is no plain request to
    learn it from either. He clicks through the warning once - and by then
    the request has arrived, carrying the address in its Host header.

    So the next certificate names it, and the time after that there is nothing
    to click through. The reissue happens on the next start rather than
    mid-request: a certificate swapped underneath the connection that is
    reading this would end the response he is waiting for.
    """
    @app.before_request
    def _remember_where_this_came_from():
        host = (request.host or "").split(":")[0]
        if host.startswith("[") and "]" in host:
            host = host[1:host.index("]")]
        remember_name(directory, host)
        return None


@dataclass(frozen=True)
class Certificate:
    cert_path: Path
    key_path: Path
    fingerprint: str
    not_after: datetime.datetime
    created: bool


def _fingerprint(der: bytes) -> str:
    digest = hashlib.sha256(der).hexdigest().upper()
    return ":".join(digest[i:i + 2] for i in range(0, len(digest), 2))


KNOWN_NAMES_FILE = "known_names.json"
# A hostname label: letters, digits and hyphens, and something has to be there.
_HOSTNAME = re.compile(r"^(?=.{1,253}$)[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?"
                       r"(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$", re.I)


def _is_a_name(value: str) -> bool:
    """Whether this is an address or a hostname at all.

    It arrives from the network, from anybody who can reach the port, so it is
    checked before it is kept. A wildcard is refused on purpose: a certificate
    for *.something would match more than the panel.
    """
    value = (value or "").strip()
    if not value or len(value) > 253 or "*" in value:
        return False
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return bool(_HOSTNAME.match(value))


def known_names(directory) -> list:
    """The addresses this panel has been reached on before.

    Kept beside the certificate so a restart does not forget them - a panel
    that forgot would issue a new certificate on the next visit, and every
    visit after a restart.
    """
    path = Path(directory) / KNOWN_NAMES_FILE
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # The file sits where an operator can edit it. Unreadable means
        # "nothing learned yet", never "do not start".
        return []
    return [n for n in stored if isinstance(n, str) and _is_a_name(n)] if isinstance(stored, list) else []


def remember_name(directory, name: str) -> bool:
    """Keep an address the panel was reached on. True when it is new.

    Only ever adds. Two addresses reach the same panel, and using one today
    must not stop the other from working tomorrow.
    """
    if not _is_a_name(name):
        return False
    name = name.strip()
    directory = Path(directory)
    current = known_names(directory)
    if name in current:
        return False
    try:
        directory.mkdir(parents=True, exist_ok=True)
        # Durable state, so it goes through the atomic writer: a crash while
        # this is being written would otherwise leave a truncated file, and the
        # panel would forget every address it had learned (utils/atomic_io.py).
        from utils.atomic_io import atomic_write_text

        atomic_write_text(directory / KNOWN_NAMES_FILE,
                          json.dumps(sorted(current + [name]), indent=2))
    except OSError as error:
        logger.warning(f"Could not remember the address {name}: {error}")
        return False
    logger.info(f"New address for this panel: {name} - the certificate will name it")
    return True


def _names(extra: Optional[Iterable[str]]) -> list:
    names = ["localhost", "127.0.0.1", socket.gethostname()]
    names += [n.strip() for n in (os.environ.get(TLS_HOSTNAMES_ENV) or "").split(",") if n.strip()]
    names += list(extra or [])
    names = [n for n in names if _is_a_name(n)]
    seen, unique = set(), []
    for name in names:
        if name and name not in seen:
            seen.add(name)
            unique.append(name)
    return unique


def _load(cert_path: Path, key_path: Path):
    from cryptography import x509

    if not key_path.is_file():
        raise FileNotFoundError(key_path)
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    return cert


def _missing_from(cert, wanted) -> list:
    """The wanted names this certificate does not carry."""
    from cryptography import x509

    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except x509.ExtensionNotFound:
        return list(wanted)
    have = {str(entry.value) for entry in san}
    return [name for name in wanted if name not in have]


def ensure_self_signed_certificate(directory, now: Optional[datetime.datetime] = None,
                                   hostnames: Optional[Iterable[str]] = None) -> Certificate:
    """Return the certificate in ``directory``, creating or renewing it when needed."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    directory = Path(directory)
    now = now or datetime.datetime.now(datetime.timezone.utc)
    cert_path, key_path = directory / CERT_NAME, directory / KEY_NAME

    wanted = _names(list(hostnames or []) + known_names(directory))
    # WHAT MUST BE IN IT, which is not the same as what goes in it. Docker
    # names a container after its id, and that id is new on every rebuild - so
    # requiring it meant a new certificate, a new fingerprint and another
    # trust step every single time the image was rebuilt. Measured twice
    # within the hour on the operator's own server (2026-09-25). Nobody
    # browses to a container id: it is offered, never required.
    must_have = [n for n in wanted if n != socket.gethostname()]

    try:
        cert = _load(cert_path, key_path)
        missing = _missing_from(cert, must_have)
        if cert.not_valid_after_utc - now > RENEW_BEFORE and not missing:
            return Certificate(cert_path, key_path, _fingerprint(cert.public_bytes(serialization.Encoding.DER)),
                               cert.not_valid_after_utc, created=False)
        if missing:
            # Without this the fix would never reach an installation that
            # already has a certificate - which is every installation that has
            # ever started (operator, 2026-09-25).
            logger.warning(f"TLS certificate does not name {', '.join(missing)} - issuing a new one")
        else:
            logger.warning(f"TLS certificate expires {cert.not_valid_after_utc:%Y-%m-%d} - renewing it now")
    except FileNotFoundError:
        pass
    except ValueError as error:
        logger.error(f"TLS certificate in {directory} is unreadable ({error}) - creating a new one")

    directory.mkdir(parents=True, exist_ok=True)
    key = ec.generate_private_key(ec.SECP256R1())
    sans = []
    for name in wanted:
        try:
            sans.append(x509.IPAddress(ipaddress.ip_address(name)))
        except ValueError:
            sans.append(x509.DNSName(name))
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "DockerDiscordControl")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + VALIDITY)
        .add_extension(x509.SubjectAlternativeName(sans), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )

    key_bytes = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                  serialization.NoEncryption())
    # The key is written with 0600 from the first byte, never readable in between.
    tmp_key = key_path.with_suffix(".key.tmp")
    fd = os.open(tmp_key, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(key_bytes)
    os.chmod(tmp_key, 0o600)
    tmp_cert = cert_path.with_suffix(".crt.tmp")
    tmp_cert.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    os.replace(tmp_key, key_path)
    os.replace(tmp_cert, cert_path)

    return Certificate(cert_path, key_path, _fingerprint(cert.public_bytes(serialization.Encoding.DER)),
                       cert.not_valid_after_utc, created=True)


# The first byte of a TLS connection is the record type of a ClientHello:
# 0x16, "handshake" (RFC 8446 §5.1). Every HTTP request starts with a method,
# so with an ASCII letter. One byte tells the two apart.
TLS_HANDSHAKE_BYTE = 0x16


def looks_like_tls(first_byte: bytes) -> bool:
    """Whether a connection that has sent this much is speaking TLS."""
    return bool(first_byte) and first_byte[0] == TLS_HANDSHAKE_BYTE


def redirect_to_https(request_head: bytes, port: int) -> bytes:
    """The answer for a plain HTTP request that arrived on the HTTPS port.

    THE OPERATOR ASKED FOR AN AUTOMATIC REDIRECT (2026-09-25). On one port
    that needs this, because there is otherwise no HTTP request to answer: the
    TLS handshake fails first and the browser shows a connection error, not a
    page. So the first byte decides, and a plain request gets a 301 to the
    same address over HTTPS.

    The Host header is used, not a configured name: the operator reaches the
    panel by IP, by hostname, or through whatever else resolves to it, and a
    redirect to a name his browser cannot resolve is worse than none. A Host
    with a port has it replaced - the port is the one we are listening on.
    A request without a Host header (HTTP/1.0) cannot be redirected anywhere
    sensible and is told so.
    """
    lines = request_head.split(b"\r\n")
    path = b"/"
    if lines and b" " in lines[0]:
        parts = lines[0].split(b" ")
        if len(parts) >= 2 and parts[1].startswith(b"/"):
            path = parts[1]
    host = b""
    for line in lines[1:]:
        if line.lower().startswith(b"host:"):
            host = line.split(b":", 1)[1].strip()
            break
    if not host:
        body = b"DDC speaks HTTPS on this port. Use https://\n"
        return (b"HTTP/1.1 400 Bad Request\r\nContent-Type: text/plain\r\n"
                b"Content-Length: " + str(len(body)).encode() + b"\r\n"
                b"Connection: close\r\n\r\n" + body)
    # Strip a port the client sent, including the brackets of an IPv6 literal.
    if host.startswith(b"["):
        name, _, rest = host.partition(b"]")
        host = name + b"]"
    elif b":" in host:
        host = host.rsplit(b":", 1)[0]
    location = b"https://" + host + b":" + str(port).encode() + path
    return (b"HTTP/1.1 301 Moved Permanently\r\nLocation: " + location +
            b"\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")


# How long a new connection may take to show its first byte and finish the TLS
# handshake. Generous for a browser on a slow link; short enough that a client
# that never speaks is let go.
HANDSHAKE_TIMEOUT_SECONDS = 10


def make_tls_server(app, host: str, port: int, certificate: Certificate):
    """A threaded HTTPS server for the self-signed mode.

    waitress cannot terminate TLS. werkzeug's threaded server can, keeps the
    real client address (so the rate limits still count per client), and ships
    with Flask - no new dependency. gevent's server is not used: DDC does not
    monkey-patch, so its blocking Docker calls would serialise every request.

    IT ALSO ANSWERS PLAIN HTTP WITH A REDIRECT. werkzeug wraps the LISTENING
    socket in TLS, so a plain request dies in the handshake before any code
    sees it. Here the listening socket stays plain and each connection is
    looked at first: a TLS one is wrapped and handed on unchanged, a plain one
    is sent to the same address over HTTPS and closed - on the connection's
    own thread (finish_request below), never on the accepting one.
    """
    from werkzeug.serving import make_server

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(str(certificate.cert_path), str(certificate.key_path))
    server = make_server(host, port, app, threaded=True)      # plain listener
    directory = certificate.cert_path.parent

    def _learn_from_the_handshake(sslobject, server_name, _context):
        """SNI: the name the browser asked for, before the certificate is sent.

        So a first visit under a new hostname already gets a certificate that
        names it - no warning to click through, no second attempt. A bare IP
        sends no server_name; that case is learned by the redirect instead.

        Reissuing here costs a key generation, which is why it only happens
        when the name is genuinely new. Returning None lets the handshake go
        on with whatever context is now set.
        """
        if not server_name or not remember_name(directory, server_name):
            return None
        try:
            fresh = ensure_self_signed_certificate(directory)
            replacement = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            replacement.minimum_version = ssl.TLSVersion.TLSv1_2
            replacement.load_cert_chain(str(fresh.cert_path), str(fresh.key_path))
            replacement.sni_callback = _learn_from_the_handshake
            sslobject.context = replacement
            # The listener keeps handing out the old one otherwise, and every
            # later connection would reissue again.
            context.load_cert_chain(str(fresh.cert_path), str(fresh.key_path))
            logger.info(f"Certificate reissued for {server_name} "
                        f"(fingerprint {fresh.fingerprint})")
        except Exception as error:                   # noqa: BLE001 - never break a handshake
            logger.error(f"Could not reissue for {server_name}: {error}")
        return None

    context.sni_callback = _learn_from_the_handshake

    # THE LOOK AT A CONNECTION HAPPENS ON ITS OWN THREAD. Until 2026-09-26 the
    # peek and the handshake ran in get_request, on socketserver's single
    # accepting thread, and the peek had no timeout: one client that connected
    # and sent nothing - or began a handshake and stalled - held that thread,
    # and no other connection was accepted. finish_request runs on the thread
    # ThreadingMixIn starts per connection, so a silent client now costs one
    # thread and HANDSHAKE_TIMEOUT_SECONDS, not the panel.
    serve_the_request = server.finish_request

    def finish_request(connection, address):
        connection.settimeout(HANDSHAKE_TIMEOUT_SECONDS)
        try:
            first = connection.recv(1, socket.MSG_PEEK)
            if not looks_like_tls(first):
                # The port we are BOUND to, not the one we were asked for: they
                # differ whenever port 0 was given, and a redirect to the wrong
                # port is a redirect to nothing.
                _answer_with_a_redirect(connection, server.socket.getsockname()[1], directory)
                return
            secured = context.wrap_socket(connection, server_side=True)
        except OSError as error:                     # includes ssl.SSLError and timeouts
            logger.debug(f"Dropped a connection before its first request: {error}")
            return
        secured.settimeout(None)
        try:
            serve_the_request(secured, address)
        finally:
            try:
                secured.close()
            except OSError:
                pass

    server.finish_request = finish_request
    server.ssl_context = context          # what werkzeug sets when it wraps
    return server


def _learn_from(request_head: bytes, directory) -> None:
    """Remember the address a plain HTTP request was aimed at.

    This is the only place an IP-only client ever tells us: a connection to a
    bare address sends no SNI, so the handshake cannot learn it. A plain
    request carries a Host and happens before any TLS at all.
    """
    if directory is None:
        return
    for line in request_head.split(b"\r\n")[1:]:
        if not line.lower().startswith(b"host:"):
            continue
        host = line.split(b":", 1)[1].strip()
        if host.startswith(b"["):
            host = host.partition(b"]")[0][1:]
        elif b":" in host:
            host = host.rsplit(b":", 1)[0]
        try:
            remember_name(directory, host.decode("ascii"))
        except UnicodeDecodeError:
            pass
        return


def _answer_with_a_redirect(connection, port: int, directory=None) -> None:
    """Read just enough of the request to build a Location, then say goodbye."""
    try:
        connection.settimeout(5)
        head = b""
        while b"\r\n\r\n" not in head and len(head) < 8192:
            chunk = connection.recv(1024)
            if not chunk:
                break
            head += chunk
        _learn_from(head, directory)
        connection.sendall(redirect_to_https(head, port))
    except OSError as error:
        logger.debug(f"Could not redirect a plain HTTP request: {error}")
    finally:
        try:
            connection.close()
        except OSError:
            pass
