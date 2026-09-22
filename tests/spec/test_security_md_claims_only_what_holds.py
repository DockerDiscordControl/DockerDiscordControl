# -*- coding: utf-8 -*-
"""docs/SECURITY.md claims what v3.0 delivers - no more (V3 §2, §3, §5.2, step 10).

A security document that is stronger than the code is worse than none: the
next reader relies on it. Until v3.0 it listed "Read-only Docker socket
mounting" as a security feature - ``:ro`` makes the socket FILE unmodifiable
and leaves the API behind it untouched; DDC's own Stop button worked through
that very mount. It also promised "Secure session cookies", which is false on
the plain-HTTP default.

What the document must say instead, checked here as sentences a reader can
find, not as wording:

* the three doors (Docker API, web panel, Discord bot) and which lock closes
  which - 2FA does not protect the bot, the proxy does not protect the panel;
* the boundary: whoever has root on the host is outside it, deliberately;
* the exact endpoint list, and what the allowed endpoints still expose -
  container environment variables through inspect, and container logs;
* the reserved image-inspect endpoint, named as read-only.

COUNTER-CHECK (2026-09-22): red against the v2.4.1 document on every point,
green after the rewrite.
"""

import re
from pathlib import Path

DOC = (Path(__file__).resolve().parents[2] / "docs" / "SECURITY.md").read_text(encoding="utf-8")
LOWER = DOC.lower()


def test_the_read_only_socket_is_not_sold_as_protection():
    for line in DOC.splitlines():
        if re.search(r"read-only docker socket|:ro\b", line, re.I):
            assert re.search(r"not a (permission )?boundary|does not|no protection|not protect", line, re.I), line


def test_no_blanket_secure_cookie_claim():
    assert "secure session cookies" not in LOWER


def test_the_three_doors_are_named():
    for door in ("docker api", "web panel", "discord bot"):
        assert door in LOWER, door
    assert re.search(r"2fa does not protect.*(discord|bot)", LOWER, re.S)
    assert re.search(r"proxy does not protect.*(panel|web)", LOWER, re.S)


def test_the_boundary_excludes_the_host_owner():
    assert re.search(r"root on the host.*outside", LOWER, re.S)


def test_the_allowed_endpoints_and_their_exposure_are_listed():
    for endpoint in ("/_ping", "/version", "/containers/json", "/containers/{id}/json",
                     "/containers/{id}/logs", "/containers/{id}/stats",
                     "/containers/{id}/start", "/containers/{id}/stop", "/containers/{id}/restart"):
        assert endpoint in DOC, endpoint
    assert "environment variables" in LOWER and "logs" in LOWER
    assert re.search(r"/images/\{name\}/json.*read-only", DOC, re.S | re.I)
