# -*- coding: utf-8 -*-
"""An image update is detected by comparing the registry's digest with the local one (Phase 4d, part 1).

The image-update notice asks the registry for the current digest of the tag a
container runs, and compares it with the RepoDigests of the local image
(read through the reserved, read-only GET /images/{name}/json). Checked here
against a stand-in registry that behaves like Docker Hub, ghcr.io and
lscr.io: an anonymous request is answered 401 with a Bearer challenge, the
token comes from the realm, and HEAD on the manifest returns
Docker-Content-Digest.

* image references are normalised the way Docker does (nginx ->
  registry-1.docker.io/library/nginx:latest), digest-pinned references are
  not checked (they cannot change);
* the remote digest is read with the token from the challenge, by HEAD - a
  HEAD does not count against Docker Hub's pull limit;
* an update is "available" only when the remote digest is known and is not
  one of the local RepoDigests of that repository; an unknown remote digest is
  "unknown", never "update".

COUNTER-CHECK (2026-09-22): red before the module existed; a registry answer
without Docker-Content-Digest gives None, not a guessed update.
"""

import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from services.automation.image_updates import (ImageRef, local_digests, parse_image_reference,
                                                remote_digest, update_available)

DIGEST = "sha256:" + "a" * 64


@pytest.mark.parametrize("reference,expected", [
    ("nginx", ("registry-1.docker.io", "library/nginx", "latest")),
    ("nginx:1.27", ("registry-1.docker.io", "library/nginx", "1.27")),
    ("linuxserver/plex", ("registry-1.docker.io", "linuxserver/plex", "latest")),
    ("docker.io/library/redis:7", ("registry-1.docker.io", "library/redis", "7")),
    ("ghcr.io/org/app:v2", ("ghcr.io", "org/app", "v2")),
    ("lscr.io/linuxserver/plex:latest", ("lscr.io", "linuxserver/plex", "latest")),
    ("localhost:5000/tool:dev", ("localhost:5000", "tool", "dev")),
])
def test_references_are_normalised_like_docker(reference, expected):
    ref = parse_image_reference(reference)
    assert (ref.registry, ref.repository, ref.tag) == expected


def test_a_digest_pinned_reference_is_not_checked():
    assert parse_image_reference("nginx@" + DIGEST) is None


def test_local_digests_are_read_per_repository():
    attrs = {"RepoDigests": ["nginx@" + DIGEST, "myregistry/nginx@sha256:" + "b" * 64]}
    assert local_digests(attrs, parse_image_reference("nginx")) == {DIGEST}


def test_update_available_needs_a_known_different_digest():
    assert update_available(remote="sha256:new", local={"sha256:old"}) is True
    assert update_available(remote="sha256:old", local={"sha256:old"}) is False
    assert update_available(remote=None, local={"sha256:old"}) is None
    assert update_available(remote="sha256:new", local=set()) is None


class _Registry(BaseHTTPRequestHandler):
    """401 with a Bearer challenge without a token; the digest with one."""
    seen = []
    send_digest = True

    def log_message(self, *args):
        pass

    def do_GET(self):  # the token endpoint
        self.seen.append(("GET", self.path))
        body = b'{"token": "t0k3n"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self):
        self.seen.append(("HEAD", self.path, self.headers.get("Authorization")))
        if self.headers.get("Authorization") != "Bearer t0k3n":
            self.send_response(401)
            host = self.headers["Host"]
            self.send_header("WWW-Authenticate",
                             f'Bearer realm="http://{host}/token",service="reg",scope="repository:library/nginx:pull"')
            self.end_headers()
            return
        self.send_response(200)
        if self.send_digest:
            self.send_header("Docker-Content-Digest", DIGEST)
        self.end_headers()


@pytest.fixture
def registry():
    handler = type("Registry", (_Registry,), {"seen": [], "send_digest": True})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"127.0.0.1:{server.server_port}", handler
    server.shutdown()


def test_the_remote_digest_is_read_with_the_challenge_token(registry):
    host, handler = registry
    ref = ImageRef(registry=host, repository="library/nginx", tag="latest")
    digest = asyncio.run(remote_digest(ref, scheme="http"))
    assert digest == DIGEST
    heads = [s for s in handler.seen if s[0] == "HEAD"]
    assert heads[0][2] is None and heads[-1][2] == "Bearer t0k3n"
    # The token request names the scope from the challenge. Compared by value,
    # not by spelling: the first version demanded "%3A" and failed on an
    # unencoded ":" that every registry accepts.
    from urllib.parse import parse_qs, urlparse
    token_queries = [parse_qs(urlparse(s[1]).query) for s in handler.seen if s[0] == "GET"]
    assert token_queries and token_queries[0]["scope"] == ["repository:library/nginx:pull"]
    assert token_queries[0]["service"] == ["reg"]


def test_no_digest_header_means_unknown_not_update(registry):
    host, handler = registry
    handler.send_digest = False
    ref = ImageRef(registry=host, repository="library/nginx", tag="latest")
    assert asyncio.run(remote_digest(ref, scheme="http")) is None


# --------------------------------------------------------------------------- #
# A container created from a bare image id
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("reference", [
    "sha256:9f3a2b1c" + "0" * 56,
    "9f3a2b1c" + "0" * 56,                       # what Config.Image holds for an untagged image
])
def test_a_bare_image_id_is_not_asked_about(reference):
    """THE FINDING: an id normalised like a name becomes
    registry-1.docker.io/library/sha256:<id>, and DDC asked Docker Hub about
    it every six hours for the life of the container - a question with no
    answer, for an image whose tag was deleted after it was created.

    COUNTER-CHECK (2026-09-22): red before - parse_image_reference returned
    ImageRef('registry-1.docker.io', 'library/sha256', '9f3a...')."""
    assert parse_image_reference(reference) is None


def test_a_normal_name_that_starts_with_hex_is_still_asked_about():
    """Counter-check: "abcdef" is a legal repository name."""
    ref = parse_image_reference("abcdef/tool:1.2")
    assert (ref.repository, ref.tag) == ("abcdef/tool", "1.2")
