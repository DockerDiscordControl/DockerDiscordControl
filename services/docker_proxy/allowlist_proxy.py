# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""An allowlist proxy in front of the Docker socket.

Why this exists (docs/V3_ARCHITECTURE_PLAN.md §3, §4): write access to the
Docker API is root on the host. DDC needs nine endpoints of it - eight its own
code calls, plus the ``GET /version`` docker-py sends on every client
construction - and one reserved read-only endpoint (image inspect). This proxy
lets exactly those through, matched on method and path with the query string
stripped, and answers everything else with 403. ``POST /containers/create`` or
``.../exec`` cannot be reached by construction.

Deliberately small and stdlib-only: it runs as its own user, from a
root-owned copy outside every path DDC can write, and a sceptical user should
be able to read the rule table in a minute. There are no switches that widen
it at runtime.

One request per connection: the proxy forwards the request with
``Connection: close`` and relays the response until the daemon closes. That
keeps the proxy free of HTTP body parsing on the response side (chunked logs,
stats) - the price is one connection per request on a local socket.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import socket
import socketserver
import sys
from typing import Optional, Tuple

logger = logging.getLogger("ddc.docker_proxy")

_NAME = r"[a-zA-Z0-9_.-]+"
_PREFIX = r"^/(v[0-9]+\.[0-9]+/)?"

# The whole policy. Method, then the path without its query string.
ALLOWLIST = (
    ("GET", re.compile(_PREFIX + r"_ping\Z")),
    ("HEAD", re.compile(_PREFIX + r"_ping\Z")),
    # docker-py 7.1.0 negotiates the API version with GET /version (unprefixed)
    # on every client built without version=. The first draft of this list
    # forgot it, and no client could be built at all.
    ("GET", re.compile(_PREFIX + r"version\Z")),
    ("GET", re.compile(_PREFIX + r"containers/json\Z")),
    ("GET", re.compile(_PREFIX + r"containers/" + _NAME + r"/(json|logs|stats)\Z")),
    ("POST", re.compile(_PREFIX + r"containers/" + _NAME + r"/(start|stop|restart)\Z")),
    # Reserved, read-only: image inspect for the image-update notice (V3 §8 item 4).
    # No "@": a digest-pinned reference cannot change, so the image-update check
    # skips it before it reads the image, and docker-py would percent-encode the
    # "@" anyway - which this proxy refuses. Permitting it only widened the
    # surface for something nobody can ask for.
    ("GET", re.compile(_PREFIX + r"images/[a-zA-Z0-9_./:-]+/json\Z")),
)

MAX_HEAD_BYTES = 64 * 1024
MAX_BODY_BYTES = 64 * 1024
IDLE_TIMEOUT_SECONDS = 120


def is_allowed(method: str, target: str) -> bool:
    """True if the request line may pass. Everything not listed is refused."""
    path = target.split("?", 1)[0]
    # Nothing DDC sends needs these, and each is a way to make a path mean
    # something else to the daemon than to this check.
    if not path.startswith("/") or "%" in path or "//" in path or "\\" in path:
        return False
    if any(segment in (".", "..") for segment in path.split("/")):
        return False
    return any(method == allowed and rule.match(path) for allowed, rule in ALLOWLIST)


def _read_head(conn: socket.socket) -> Tuple[bytes, bytes]:
    """Read up to the end of the request head; return (head, body bytes already read)."""
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = conn.recv(8192)
        if not chunk:
            raise ConnectionError("client closed before the request head was complete")
        data += chunk
        if len(data) > MAX_HEAD_BYTES:
            raise ValueError("request head too large")
    head, _, rest = data.partition(b"\r\n\r\n")
    return head, rest


def _parse(head: bytes):
    """Split the request head, refusing anything two HTTP readers could read differently.

    dockerd (Go) accepts a bare LF as a line ending; this proxy splits on CRLF.
    A bare LF or CR inside the head would therefore hide a header - say a
    Transfer-Encoding - from this check while the daemon acts on it. The same
    goes for a second Content-Length, and for anything after the protocol
    version on the request line.
    """
    if b"\n" in head.replace(b"\r\n", b"") or b"\r" in head.replace(b"\r\n", b""):
        raise ValueError("bare CR or LF in the request head")
    lines = head.decode("latin-1").split("\r\n")
    parts = lines[0].split(" ")
    if len(parts) != 3 or parts[2] not in ("HTTP/1.0", "HTTP/1.1"):
        raise ValueError("malformed request line")
    method, target, version = parts
    headers = []
    for line in lines[1:]:
        name, separator, value = line.partition(":")
        if not separator or not name or name != name.strip():
            raise ValueError("malformed header line")
        headers.append((name, value.strip()))
    if sum(1 for name, _ in headers if name.lower() == "content-length") > 1:
        raise ValueError("more than one Content-Length")
    return method, target, version, headers


def _refuse(conn: socket.socket, status: str, message: str) -> None:
    body = ('{"message": "%s (DDC docker proxy)"}' % message).encode()
    conn.sendall(
        (
            f"HTTP/1.1 {status}\r\nContent-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n"
        ).encode()
        + body
    )


class _Handler(socketserver.BaseRequestHandler):
    upstream_path: str = "/var/run/docker.sock"

    def handle(self) -> None:
        conn: socket.socket = self.request
        conn.settimeout(IDLE_TIMEOUT_SECONDS)
        try:
            head, body = _read_head(conn)
        except (ValueError, ConnectionError, OSError) as error:
            logger.warning(f"docker proxy: unreadable request ({error})")
            return
        try:
            method, target, version, headers = _parse(head)
        except ValueError as error:
            logger.warning(f"docker proxy: DENIED malformed request ({error})")
            _refuse(conn, "400 Bad Request", "malformed request")
            return

        names = {name.lower() for name, _ in headers}
        if not is_allowed(method, target):
            logger.warning(f"docker proxy: DENIED {method} {target.split('?', 1)[0]}")
            _refuse(conn, "403 Forbidden", "endpoint not allowed")
            return
        # Allowed endpoints need neither a streamed body nor a protocol switch.
        if "transfer-encoding" in names or "upgrade" in names:
            logger.warning(f"docker proxy: DENIED {method} {target.split('?', 1)[0]} (body/upgrade)")
            _refuse(conn, "403 Forbidden", "streamed bodies and upgrades are not allowed")
            return

        length = 0
        for name, value in headers:
            if name.lower() == "content-length":
                # Digits only, the way Go's strconv.ParseUint reads it. Python's
                # int() also takes "-1", "+5" and "1_0"; with "-1" the size check
                # passed and body[:length] cut a byte off - proxy and daemon
                # reading one request differently, which is what this file exists
                # to prevent.
                digits = value.strip()
                # isascii() as well: str.isdigit() also says yes to "١٢"
                if not digits.isascii() or not digits.isdigit():
                    _refuse(conn, "400 Bad Request", "bad content-length")
                    return
                length = int(digits)
        if length > MAX_BODY_BYTES:
            _refuse(conn, "413 Payload Too Large", "request body too large")
            return
        try:
            while len(body) < length:
                chunk = conn.recv(min(65536, length - len(body)))
                if not chunk:
                    return
                body += chunk
        except OSError as error:
            # A client that promises a body and then stops used to raise out of
            # handle(), so the log got a socketserver traceback instead of a line
            logger.warning(f"docker proxy: client stopped mid-body ({error})")
            return
        body = body[:length]

        kept = [(n, v) for n, v in headers if n.lower() not in ("connection", "keep-alive", "proxy-connection")]
        request = f"{method} {target} {version}\r\n" + "".join(f"{n}: {v}\r\n" for n, v in kept)
        request += "Connection: close\r\n\r\n"

        upstream = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        upstream.settimeout(IDLE_TIMEOUT_SECONDS)
        relayed = False
        try:
            upstream.connect(self.upstream_path)
            upstream.sendall(request.encode("latin-1") + body)
            while True:
                chunk = upstream.recv(65536)
                if not chunk:
                    break
                conn.sendall(chunk)
                relayed = True
        except OSError as error:
            logger.error(f"docker proxy: upstream failed for {method} {target.split('?', 1)[0]}: {error}")
            # Only when this request produced nothing yet. Written into an answer
            # that had already started, the 502 was a second HTTP response inside
            # the body of the first, and the client read the two as one.
            if not relayed:
                try:
                    _refuse(conn, "502 Bad Gateway", "docker daemon unreachable")
                except OSError:
                    pass
        finally:
            upstream.close()


class _Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def serve(listen_path: str, upstream_path: str, mode: int = 0o660) -> _Server:
    """Bind the proxy socket and return the server (not yet serving)."""
    if os.path.exists(listen_path):
        os.unlink(listen_path)
    handler = type("Handler", (_Handler,), {"upstream_path": upstream_path})
    server = _Server(listen_path, handler)
    os.chmod(listen_path, mode)
    return server


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="DDC allowlist proxy for the Docker socket")
    parser.add_argument("--listen", required=True, help="unix socket path to listen on")
    parser.add_argument("--upstream", default="/var/run/docker.sock", help="the real Docker socket")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    server = serve(args.listen, args.upstream)
    logger.info(f"docker proxy: listening on {args.listen}, upstream {args.upstream}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
