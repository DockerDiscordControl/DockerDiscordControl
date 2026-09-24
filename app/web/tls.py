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


def _names(extra: Optional[Iterable[str]]) -> list:
    names = ["localhost", "127.0.0.1", socket.gethostname()]
    names += [n.strip() for n in (os.environ.get(TLS_HOSTNAMES_ENV) or "").split(",") if n.strip()]
    names += list(extra or [])
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

    try:
        cert = _load(cert_path, key_path)
        if cert.not_valid_after_utc - now > RENEW_BEFORE:
            return Certificate(cert_path, key_path, _fingerprint(cert.public_bytes(serialization.Encoding.DER)),
                               cert.not_valid_after_utc, created=False)
        logger.warning(f"TLS certificate expires {cert.not_valid_after_utc:%Y-%m-%d} - renewing it now")
    except FileNotFoundError:
        pass
    except ValueError as error:
        logger.error(f"TLS certificate in {directory} is unreadable ({error}) - creating a new one")

    directory.mkdir(parents=True, exist_ok=True)
    key = ec.generate_private_key(ec.SECP256R1())
    sans = []
    for name in _names(hostnames):
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
    is sent to the same address over HTTPS and closed. Raising OSError
    afterwards is how socketserver is told there is no request to serve - it
    catches exactly that around get_request and carries on.
    """
    from werkzeug.serving import make_server

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(str(certificate.cert_path), str(certificate.key_path))
    server = make_server(host, port, app, threaded=True)      # plain listener

    def get_request():
        connection, address = server.socket.accept()
        try:
            first = connection.recv(1, socket.MSG_PEEK)
        except OSError:
            connection.close()
            raise
        if looks_like_tls(first):
            return context.wrap_socket(connection, server_side=True), address
        # The port we are BOUND to, not the one we were asked for: they differ
        # whenever port 0 was given, and a redirect to the wrong port is a
        # redirect to nothing.
        _answer_with_a_redirect(connection, server.socket.getsockname()[1])
        raise OSError("plain HTTP on the HTTPS port - answered with a redirect")

    server.get_request = get_request
    server.ssl_context = context          # what werkzeug sets when it wraps
    return server


def _answer_with_a_redirect(connection, port: int) -> None:
    """Read just enough of the request to build a Location, then say goodbye."""
    try:
        connection.settimeout(5)
        head = b""
        while b"\r\n\r\n" not in head and len(head) < 8192:
            chunk = connection.recv(1024)
            if not chunk:
                break
            head += chunk
        connection.sendall(redirect_to_https(head, port))
    except OSError as error:
        logger.debug(f"Could not redirect a plain HTTP request: {error}")
    finally:
        try:
            connection.close()
        except OSError:
            pass
