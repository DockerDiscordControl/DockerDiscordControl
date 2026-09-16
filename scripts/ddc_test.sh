#!/bin/bash
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
#
# Run the test suite inside a throwaway container built from the production
# image, against the working tree on the Unraid host.
#
#   scripts/ddc_test.sh tests/unit/cogs
#   scripts/ddc_test.sh -k "weekday" tests/unit/audit_2026_09
#
# Run ONE test group per call. Collecting several groups in a single pytest run makes
# tests/unit/services/ (no __init__.py, but named like the real package) shadow the real
# services package, and ~29 modules fail to import with
#   ModuleNotFoundError: No module named 'services.infrastructure.action_log_service'
# That is a test-layout artefact, not a code error: the same modules pass when run alone.
#
# Why this script exists (2026-09-15): a test with an endless loop ran in a
# container WITHOUT limits, grew to ~18 GB and the host OOM-killed processes
# until it became unresponsive. Leftover containers kept refilling memory after
# the ssh session had dropped. So every run here:
#   * caps memory, PIDs and CPU, and has a wall-clock timeout
#   * mounts EMPTY temp dirs over config/ and logs/ (tests must never touch
#     live data; some tests start real services)
#   * uses a fixed name prefix and removes leftovers before and after
#   * runs ONE container at a time
#
# Requirements on the host: the pytest bundle in /tmp/pytestlib (see
# docs/TESTING or the project notes for how it is built).

set -uo pipefail

: "${DDC_TEST_HOST:?set DDC_TEST_HOST to the docker host, e.g. root@192.168.1.10 (or localhost handling below)}"
HOST="${DDC_TEST_HOST}"
IMAGE="${DDC_TEST_IMAGE:-dockerdiscordcontrol}"
REPO="${DDC_TEST_REPO:-/mnt/user/appdata/dockerdiscordcontrol}"
PYTESTLIB="${DDC_TEST_PYTESTLIB:-/tmp/pytestlib}"
MEMORY="${DDC_TEST_MEMORY:-1g}"
PIDS="${DDC_TEST_PIDS:-256}"
CPUS="${DDC_TEST_CPUS:-2}"
TIMEOUT="${DDC_TEST_TIMEOUT:-600}"
ADDOPTS="${DDC_TEST_ADDOPTS:--q -rfE --tb=short}"
# Extra ssh options, e.g. DDC_TEST_SSH_OPTS="-i ~/.ssh/id_ed25519 -o IdentitiesOnly=yes".
# Needed when DDC_TEST_HOST is a raw IP: ~/.ssh/config rules usually match a Host alias, so
# ssh falls back to offering every identity it knows and the server aborts the connection
# with "Too many authentication failures" before the right key is tried.
SSH_OPTS="${DDC_TEST_SSH_OPTS:-}"

if [ "$#" -eq 0 ]; then
    echo "usage: $(basename "$0") <pytest args/paths...>" >&2
    echo "example: $(basename "$0") tests/unit/cogs" >&2
    exit 2
fi

NAME="ddctest-$(date +%s)-$$"
REMOTE_SCRIPT=$(cat <<REMOTE
set -u
# 1. never run two test containers at once; clean up anything left behind
for old in \$(docker ps -aq --filter "name=ddctest-"); do
    echo "[ddc_test] removing leftover test container \$(docker inspect -f '{{.Name}}' "\$old")" >&2
    docker rm -f "\$old" >/dev/null 2>&1
done

# 2. empty config/ and logs/ so tests can never touch live data
CFG=\$(mktemp -d /tmp/${NAME}-cfg-XXXX)
LOGS=\$(mktemp -d /tmp/${NAME}-logs-XXXX)
chown 1000:1000 "\$CFG" "\$LOGS"

cleanup() {
    docker rm -f "${NAME}" >/dev/null 2>&1
    rm -rf "\$CFG" "\$LOGS"
}
trap cleanup EXIT INT TERM

# 3. limits + timeout; --init so a killed pytest leaves no stray children
docker run --rm --name "${NAME}" --init \\
    --memory=${MEMORY} --memory-swap=${MEMORY} --pids-limit=${PIDS} --cpus=${CPUS} \\
    -u ddc \\
    -e PYTHONDONTWRITEBYTECODE=1 \\
    -e PYTHONPATH=/opt/runtime/site-packages:/pytestlib \\
    -v "${REPO}":/app \\
    -v "\$CFG":/app/config \\
    -v "\$LOGS":/app/logs \\
    -v "${PYTESTLIB}":/pytestlib:ro \\
    -w /app --entrypoint sh "${IMAGE}" \\
    -c "unset PYTHONOPTIMIZE; timeout ${TIMEOUT} python3 -m pytest -p no:cacheprovider -o addopts='${ADDOPTS}' $*"
rc=\$?

if [ "\$rc" = "124" ]; then
    echo "[ddc_test] TIMEOUT after ${TIMEOUT}s - container killed (likely a hanging test)" >&2
elif [ "\$rc" = "137" ]; then
    echo "[ddc_test] container hit the ${MEMORY} memory limit (OOM) - the host stayed safe" >&2
fi
exit \$rc
REMOTE
)

ssh -o ConnectTimeout=10 $SSH_OPTS "$HOST" "bash -s" <<< "$REMOTE_SCRIPT"
