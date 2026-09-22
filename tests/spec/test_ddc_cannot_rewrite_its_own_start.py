# -*- coding: utf-8 -*-
"""DDC cannot rewrite the code root runs, and cannot reach the socket past the proxy.

v3.0 keeps ONE container (operator decision 2026-09-22) and puts the allowlist
proxy between DDC and the Docker socket. Measured on the v2.4.1 image, that
boundary had a route around it (V3 §4.3):

* ``/app`` - code and ``entrypoint.sh`` - belonged to ``ddc`` and was writable
  by it (``COPY --chown=ddc:ddc`` plus ``chown -R ddc:ddc /app``), and the
  entrypoint ran as root at every start and even chowned ``/app`` again. Code
  execution in DDC could rewrite the entrypoint; the next restart ran it as
  root, and root has the socket whatever the groups say.
* ``ddc`` was in the socket's group, at build time and again at start.

The four conditions of V3 §4.3, as they can be read from the two files that
build the container:

1. ``/app`` code and the entrypoint are root-owned; only the data directories
   belong to ``ddc``; the entrypoint no longer chowns ``/app``.
2. The proxy runs from a root-owned copy outside every ``ddc`` path
   (``/opt/ddc-proxy``).
3. (The write attempt against the BUILT image lives in
   ``scripts/check_image_boundary.sh`` - these tests read files, they cannot
   prove what an image does.)
4. The proxy user, not ``ddc``, joins the socket's group; the entrypoint starts
   the proxy as that user before dropping to ``ddc`` and points ``DOCKER_HOST``
   at it.

COUNTER-CHECK (2026-09-22): written before the Dockerfile and entrypoint were
changed; every test here was red for the reason its name gives, green after.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")
ENTRYPOINT = (ROOT / "scripts" / "entrypoint.sh").read_text(encoding="utf-8")


def _instructions(text):
    """Dockerfile instructions with line continuations joined, comments dropped."""
    joined = re.sub(r"\\\n", " ", text)
    return [line.strip() for line in joined.splitlines() if line.strip() and not line.strip().startswith("#")]


def _function(name):
    match = re.search(rf"^{name}\(\) \{{\n(.*?)^\}}", ENTRYPOINT, re.S | re.M)
    assert match, f"entrypoint has no function {name}()"
    return "\n".join(l for l in match.group(1).splitlines() if not l.strip().startswith("#"))


def test_no_code_is_copied_as_ddc():
    owned = [i for i in _instructions(DOCKERFILE) if i.startswith("COPY") and "--chown=ddc" in i]
    assert not owned, "code copied as ddc can be rewritten by ddc:\n" + "\n".join(owned)


def test_only_the_data_directories_are_handed_to_ddc():
    data = {"/app/config", "/app/logs", "/app/cached_displays", "/app/cached_animations"}
    for instruction in _instructions(DOCKERFILE):
        for match in re.finditer(r"chown\s+(-R\s+)?ddc(:ddc)?\s+([^&;]+)", instruction):
            targets = set(match.group(3).split())
            assert targets <= data, f"ddc is given more than its data: {sorted(targets - data)}"


def test_the_proxy_runs_from_a_root_owned_copy_outside_app():
    copies = [i for i in _instructions(DOCKERFILE) if i.startswith("COPY") and "allowlist_proxy.py" in i]
    assert copies and all("/opt/ddc-proxy/" in i and "--chown" not in i for i in copies), copies
    assert 'PROXY_SCRIPT="/opt/ddc-proxy/allowlist_proxy.py"' in ENTRYPOINT


def test_ddc_is_not_put_in_the_socket_group_at_build_time():
    joined = " ".join(_instructions(DOCKERFILE))
    assert not re.search(r"adduser\s+ddc\s+docker\b", joined), "ddc joins the docker group in the Dockerfile"


def test_the_entrypoint_no_longer_chowns_app():
    body = _function("fix_permissions")
    assert not re.search(r"chown\s+\S+\s+/app\b(?!/)", body), "fix_permissions still chowns /app itself"


def test_the_proxy_user_joins_the_socket_group_not_ddc():
    body = _function("setup_docker_socket_access")
    assert re.search(r'addgroup "\$PROXY_USER" "\$sock_group"', body), "proxy user is not added to the socket group"
    assert not re.search(r'addgroup "\$APP_USER" "\$sock_group"', body), "ddc is still added to the socket group"


def test_the_proxy_starts_as_its_own_user_and_ddc_is_pointed_at_it():
    body = _function("start_docker_proxy")
    assert re.search(r'su-exec "\$PROXY_USER"', body), "proxy not started as the proxy user"
    assert 'export DOCKER_HOST="unix://$PROXY_SOCKET"' in body
    main = _function("main")
    assert main.index("start_docker_proxy") < main.index("drop_privileges"), "proxy must start before the drop to ddc"


def test_every_process_in_the_image_is_pointed_at_the_proxy():
    """Found after the first rebuild (2026-09-22): the entrypoint exported
    DOCKER_HOST only into its own process tree. DDC used the proxy, but every
    ``docker exec`` session - diagnostics, the boundary check itself - fell back
    to the raw socket and was (rightly) refused. The image sets it for all."""
    envs = " ".join(i for i in _instructions(DOCKERFILE) if i.startswith("ENV"))
    assert 'DOCKER_HOST="unix:///run/ddc-proxy/docker.sock"' in envs, envs
