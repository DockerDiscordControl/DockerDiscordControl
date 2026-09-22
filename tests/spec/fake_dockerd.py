# -*- coding: utf-8 -*-
"""A stand-in Docker daemon on a unix socket, for tests that need a real docker-py client.

Answers every request plausibly (ping, version, container list/inspect/logs/
stats, start/stop/restart; anything else 200 {}) and records each request
line. A stand-in on purpose: tests must not start or stop real containers.
Shared by the proxy test and the client-factory test so there is one fake,
not two drifting copies.
"""

import contextlib
import http.server
import json
import os
import shutil
import socketserver
import struct
import tempfile
import threading


class FakeDaemon(http.server.BaseHTTPRequestHandler):
    """Answers like dockerd, records every request line it gets."""

    protocol_version = "HTTP/1.1"
    seen = []

    def log_message(self, *args):
        pass

    def address_string(self):  # unix sockets have no client address
        return "fake"

    def _send(self, status, body=b"", content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Api-Version", "1.44")
        self.end_headers()
        self.wfile.write(body)

    def _route(self):
        self.seen.append((self.command, self.path))
        path = self.path.split("?", 1)[0]
        if path.endswith("/_ping"):
            return self._send(200, b"OK", "text/plain")
        if path.endswith("/version"):
            return self._send(200, json.dumps({"ApiVersion": "1.44", "MinAPIVersion": "1.24", "Version": "27.0.0"}).encode())
        if path.endswith("/containers/json"):
            return self._send(200, json.dumps([{"Id": "abc123", "Names": ["/web"], "State": "running"}]).encode())
        if path.endswith("/logs"):
            payload = b"hello from web\n"
            frame = struct.pack(">BxxxL", 1, len(payload)) + payload
            return self._send(200, frame, "application/vnd.docker.raw-stream")
        if path.endswith("/stats"):
            return self._send(200, json.dumps({"cpu_stats": {}, "memory_stats": {}}).encode())
        if path.endswith("/json"):
            return self._send(200, json.dumps({
                "Id": "abc123", "Name": "/web", "Image": "sha256:0",
                "State": {"Running": True, "Status": "running"},
                "Config": {"Tty": False, "Image": "nginx"},
            }).encode())
        if self.command == "POST":
            return self._send(204)
        return self._send(200, b"{}")

    do_GET = do_POST = do_HEAD = do_DELETE = do_PUT = _route


class UnixHTTPServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True




@contextlib.contextmanager
def running_fake_dockerd():
    """Yield (workdir, daemon socket path, list of (method, path) the daemon saw)."""
    workdir = tempfile.mkdtemp(prefix="ddcfd", dir="/tmp")  # AF_UNIX paths are short
    daemon_path = os.path.join(workdir, "d.sock")
    handler = type("Daemon", (FakeDaemon,), {"seen": []})
    daemon = UnixHTTPServer(daemon_path, handler)
    thread = threading.Thread(target=daemon.serve_forever, daemon=True)
    thread.start()
    try:
        yield workdir, daemon_path, handler.seen
    finally:
        daemon.shutdown()
        daemon.server_close()
        shutil.rmtree(workdir, ignore_errors=True)
