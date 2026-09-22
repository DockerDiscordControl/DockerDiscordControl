# -*- coding: utf-8 -*-
"""Every place that builds a Docker client is on one list.

v3.0 puts an allowlist proxy between DDC and the Docker socket and points
``DOCKER_HOST`` at it. A site that builds its client some other way - a
hard-coded ``unix:///var/run/docker.sock``, or the configured
``docker_socket_path`` - keeps talking to the socket directly, past the
proxy. Both paths work, so no functional test notices; the security claim of
v3.0 would simply be false. See docs/V3_ARCHITECTURE_PLAN.md §6.

This is a ratchet, not a fix. It pins the sites as they ARE today, including
their differences, and turns red when one appears, disappears or changes how
it resolves the socket. The client factory of v3.0 (Etappe 2c) will empty the
table on purpose, one row at a time.

It also pins that no site passes ``version=``: without it docker-py 7.1.0 calls
``GET /version`` (unprefixed) on every client construction to negotiate the
API version, which is why the proxy allowlist needs that endpoint. The day the
factory pins the version, this assertion is changed on purpose, not silently.

How a site is found: the syntax tree, not a text search. The two pool sites
pass ``docker.DockerClient`` as a callable to ``asyncio.to_thread`` - a search
for ``DockerClient(`` misses both. Type annotations (``-> docker.DockerClient``)
are not sites and are skipped: only a reference that is called, or handed to a
call as an argument, builds a client.

EIGHT SITES, NOT SEVEN: V3 §6 and the independent review both list seven. The
syntax tree finds an eighth, ``docker_utils.get_docker_client_async``'s inner
``individual_client`` (``docker.from_env()`` without timeout), used when the
connection pool is switched off or fails to import. It is pinned here like the
others.

COUNTER-CHECK (2026-09-22): the table was first written from V3 §6 (seven
rows) and the test went red naming the eighth site. Then, with the table
complete: removing ``base_url=...`` from container_log_service turned the
hard-coded check red; adding ``version="1.43"`` to web_helpers' probe turned
the version check red; and the ``to_thread`` case is covered by the detector
test below.
"""

import ast
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
CONSTRUCTORS = {"from_env", "DockerClient", "APIClient"}
NOT_APP_CODE = {".git", "tests", "config", "logs", "node_modules", "__pycache__", ".pytest_cache"}
DEFAULT_SOCKET = "unix:///var/run/docker.sock"

# The one place that may build a client (v3.0 step 6). It follows DOCKER_HOST
# and passes version= on purpose: the version it negotiated once.
FACTORY = ("services/docker_service/client_factory.py", "build_docker_client")

# (file, enclosing function) -> (constructors used, hard-codes the default socket)
# Every row except the factory is a site still to be moved onto the factory;
# the table only shrinks.
KNOWN_SITES = {
    FACTORY: ({"from_env"}, False),
    ("services/docker_service/docker_client_pool.py", "DockerClientService._create_new_client_async"):
        ({"DockerClient", "from_env"}, False),
    ("services/docker_service/docker_client_pool.py", "get_docker_client_async"):
        ({"DockerClient", "from_env"}, False),
    ("services/docker_service/docker_utils.py", "get_docker_client"):
        ({"DockerClient", "from_env"}, True),
    ("services/docker_service/docker_utils.py", "get_docker_client_async.individual_client"):
        ({"from_env"}, False),
}


def _is_constructor(node):
    return (
        isinstance(node, ast.Attribute)
        and node.attr in CONSTRUCTORS
        and isinstance(node.value, ast.Name)
    )


class _Finder(ast.NodeVisitor):
    """Collects the calls that build a client, with their enclosing function."""

    def __init__(self):
        self.scope = []
        self.calls = []  # (qualname, constructor, call node)

    def _enter(self, node):
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_FunctionDef = visit_AsyncFunctionDef = visit_ClassDef = _enter

    def visit_Call(self, node):
        # docker.from_env(...)  or  asyncio.to_thread(docker.DockerClient, ...)
        for candidate in [node.func, *node.args]:
            if _is_constructor(candidate):
                self.calls.append((".".join(self.scope), candidate.attr, node))
        self.generic_visit(node)


def _find(source):
    finder = _Finder()
    finder.visit(ast.parse(source))
    return finder.calls


def _all_calls():
    for path in sorted(PROJECT.rglob("*.py")):
        relative = path.relative_to(PROJECT)
        if relative.parts[0] in NOT_APP_CODE:
            continue
        for qualname, constructor, call in _find(path.read_text(encoding="utf-8")):
            yield str(relative), qualname, constructor, call


def _hardcodes_socket(call):
    return any(
        kw.arg == "base_url" and isinstance(kw.value, ast.Constant) and kw.value.value == DEFAULT_SOCKET
        for kw in call.keywords
    )


def _found_sites():
    sites = {}
    for file, qualname, constructor, call in _all_calls():
        constructors, hardcoded = sites.get((file, qualname), (set(), False))
        sites[(file, qualname)] = (constructors | {constructor}, hardcoded or _hardcodes_socket(call))
    return sites


def test_the_finder_sees_both_call_shapes():
    """Proof of effect: the pool's ``to_thread`` form is exactly what a text
    search misses. If the finder missed it too, the table would shrink and the
    test would still pass."""
    source = (
        "import asyncio, docker\n"
        "async def pool():\n"
        "    return await asyncio.to_thread(docker.DockerClient, base_url='unix:///var/run/docker.sock')\n"
        "def direct() -> docker.DockerClient:\n"
        "    return docker.from_env(timeout=5)\n"
    )
    found = {(q, c) for q, c, _ in _find(source)}
    assert found == {("pool", "DockerClient"), ("direct", "from_env")}, found


def test_every_client_site_is_on_the_list():
    found = _found_sites()
    unknown = sorted(set(found) - set(KNOWN_SITES))
    gone = sorted(set(KNOWN_SITES) - set(found))
    assert not unknown and not gone, (
        f"New client sites (route them through the one place instead): {unknown}\n"
        f"Sites that disappeared (update the table on purpose): {gone}"
    )


def test_each_site_resolves_the_socket_as_recorded():
    found = _found_sites()
    changed = {
        site: {"recorded": KNOWN_SITES[site], "now": found[site]}
        for site in KNOWN_SITES
        if site in found and found[site] != KNOWN_SITES[site]
    }
    assert not changed, f"Client sites changed how they build the client: {changed}"


def test_only_the_factory_passes_a_version():
    """Changed on purpose on 2026-09-22 with the factory: it passes the version
    it negotiated once. Any other site passing version= would bypass that."""
    pinned = [
        f"{file}:{call.lineno} {qualname}"
        for file, qualname, _, call in _all_calls()
        if any(kw.arg == "version" for kw in call.keywords) and (file, qualname) != FACTORY
    ]
    assert not pinned, f"Only the factory may pass version=: {pinned}"
