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


def make_tls_server(app, host: str, port: int, certificate: Certificate):
    """A threaded HTTPS server for the self-signed mode.

    waitress cannot terminate TLS. werkzeug's threaded server can, keeps the
    real client address (so the rate limits still count per client), and ships
    with Flask - no new dependency. gevent's server is not used: DDC does not
    monkey-patch, so its blocking Docker calls would serialise every request.
    """
    from werkzeug.serving import make_server

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(str(certificate.cert_path), str(certificate.key_path))
    return make_server(host, port, app, threaded=True, ssl_context=context)
