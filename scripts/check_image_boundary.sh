#!/bin/bash
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
#
# Prove the v3.0 one-container boundary against a RUNNING container built from
# the current image (docs/V3_ARCHITECTURE_PLAN.md §4.3, condition 3). Run it on
# the Docker host after a rebuild:
#
#   bash scripts/check_image_boundary.sh [container-name]
#
# Everything is attempted AS ddc, the user DDC's code runs as. The static
# tests in tests/spec/test_ddc_cannot_rewrite_its_own_start.py read the
# Dockerfile and entrypoint; only this script can show what the built image
# actually lets ddc do. Exit code 0 only if every attempt that must fail
# failed and every way that must work worked.

# NO assert in the probes: the image sets PYTHONOPTIMIZE=1, which strips every
# assert statement - a probe built on assert passes whatever happens (found on
# the first run of this script: the 403 check stayed "ok" on an image without
# any proxy). Probes exit non-zero explicitly instead.

set -u
CONTAINER="${1:-dockerdiscordcontrol}"
fail=0

as_ddc() { docker exec -u ddc "$CONTAINER" sh -c "$1" >/dev/null 2>&1; }

must_fail() {
    if as_ddc "$2"; then
        echo "FAIL  $1"
        fail=1
    else
        echo "ok    $1"
    fi
}

must_work() {
    if as_ddc "$2"; then
        echo "ok    $1"
    else
        echo "FAIL  $1"
        fail=1
    fi
}

echo "Boundary check against container '$CONTAINER' (as ddc):"

# Condition 1: ddc cannot change the code root runs at the next start.
# Probes never change what they probe: existing files are tested with -w, and a
# probe file that could be created is removed at once (the script must be safe
# to run against an image where the boundary does NOT hold).
must_fail "write /app/entrypoint.sh"          "test -w /app/entrypoint.sh"
must_fail "write /app/run.py"                 "test -w /app/run.py"
must_fail "create a file in /app"             "touch /app/.boundary_probe && rm -f /app/.boundary_probe"
must_fail "create a file in /app/services"    "touch /app/services/.boundary_probe && rm -f /app/services/.boundary_probe"
# Condition 2: ddc cannot change the proxy or its rules.
must_work "the proxy copy exists"             "test -f /opt/ddc-proxy/allowlist_proxy.py"
must_fail "write the proxy"                   "test -w /opt/ddc-proxy/allowlist_proxy.py"
must_fail "create a file in /opt/ddc-proxy"   "touch /opt/ddc-proxy/.boundary_probe && rm -f /opt/ddc-proxy/.boundary_probe"
# Condition 4: ddc cannot open the Docker socket itself.
must_fail "open /var/run/docker.sock"         "python3 -c \"import socket; s=socket.socket(socket.AF_UNIX); s.connect('/var/run/docker.sock')\""
# DDC itself (PID 1) and any exec session are pointed at the proxy.
must_work "PID 1 uses the proxy"              "tr '\\0' '\\n' < /proc/1/environ | grep -qx 'DOCKER_HOST=unix:///run/ddc-proxy/docker.sock'"
# ... and reaches Docker through it, for what DDC needs and nothing else.
must_work "ping Docker through the proxy"     "python3 -c \"import docker, sys; c=docker.from_env(timeout=10); sys.exit(0 if c.ping() else 1)\""
must_work "list containers through the proxy" "python3 -c \"import docker; c=docker.from_env(timeout=10); c.containers.list(all=True)\""
must_fail "GET /info through the proxy"       "python3 -c \"import docker; c=docker.from_env(timeout=10); c.info()\""
# The create probe names an image that cannot exist, so even where the boundary
# does NOT hold nothing is created - the daemon answers "no such image" (an
# error, so the probe still counts as refused there: read the next line).
must_fail "create a container through the proxy" "python3 -c \"import docker; c=docker.from_env(timeout=10); c.containers.create('ddc-boundary-probe/does-not-exist:none')\""
must_work "the create was refused by the proxy" "python3 -c \"
import docker
c = docker.from_env(timeout=10)
try:
    c.containers.create('ddc-boundary-probe/does-not-exist:none')
except docker.errors.APIError as e:
    raise SystemExit(0 if e.status_code == 403 and 'DDC docker proxy' in str(e) else 1)
raise SystemExit(1)
\""
# Data directories stay writable for ddc.
must_work "write /app/config"                 "touch /app/config/.boundary_probe && rm /app/config/.boundary_probe"
must_work "write /app/logs"                   "touch /app/logs/.boundary_probe && rm /app/logs/.boundary_probe"

if [ "$fail" = "0" ]; then
    echo "Boundary holds."
else
    echo "BOUNDARY BROKEN - see FAIL lines above."
fi
exit "$fail"
