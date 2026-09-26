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
# How long to wait for another run to finish before giving up (see step 0 below).
LOCK_WAIT="${DDC_TEST_LOCK_WAIT:-3600}"
ADDOPTS="${DDC_TEST_ADDOPTS:--q -rfE --tb=short}"
# Extra ssh options, e.g. DDC_TEST_SSH_OPTS="-i ~/.ssh/id_ed25519 -o IdentitiesOnly=yes".
# Needed when DDC_TEST_HOST is a raw IP: ~/.ssh/config rules usually match a Host alias, so
# ssh falls back to offering every identity it knows and the server aborts the connection
# with "Too many authentication failures" before the right key is tried.
SSH_OPTS="${DDC_TEST_SSH_OPTS:-}"

if [ "$#" -eq 0 ]; then
    echo "usage: $(basename "$0") <pytest args/paths...>   |   $(basename "$0") --all" >&2
    echo "example: $(basename "$0") tests/unit/cogs" >&2
    exit 2
fi

# --all: every group of tests/GROUPS.txt, one container per group (see the note
# above on why one run cannot hold them all), with one line per group and a
# total. The group list is the project's own - the workflows read the same file.
if [ "$1" = "--all" ]; then
    HERE=$(cd "$(dirname "$0")/.." && pwd)
    LIST="$HERE/tests/GROUPS.txt"
    if [ ! -f "$LIST" ]; then
        echo "[ddc_test] $LIST is missing - no group list, no full run" >&2
        exit 2
    fi
    total_passed=0; total_skipped=0; total_bad=0; groups=0; failed_groups=""
    while IFS= read -r group; do
        case "$group" in ""|\#*) continue;; esac
        line=$("$0" "$group" 2>&1 | tail -1)
        groups=$((groups + 1))
        echo "$group :: $line"
        passed=$(printf '%s' "$line" | sed -n 's/.*[^0-9]\([0-9][0-9]*\) passed.*/\1/p')
        skipped=$(printf '%s' "$line" | sed -n 's/.*[^0-9]\([0-9][0-9]*\) skipped.*/\1/p')
        # two plain expressions: "\|" is a GNU extension that neither BSD sed nor
        # busybox understands, and it silently matched nothing here
        failed=$(printf '%s' "$line" | sed -n 's/.*[^0-9]\([0-9][0-9]*\) failed.*/\1/p')
        errors=$(printf '%s' "$line" | sed -n 's/.*[^0-9]\([0-9][0-9]*\) error.*/\1/p')
        bad=$(( ${failed:-0} + ${errors:-0} ))
        [ "$bad" = "0" ] && bad=""
        total_passed=$((total_passed + ${passed:-0}))
        total_skipped=$((total_skipped + ${skipped:-0}))
        total_bad=$((total_bad + ${bad:-0}))
        [ -n "${bad:-}" ] && failed_groups="$failed_groups $group"
    done < "$LIST"
    echo "[ddc_test] $groups groups: $total_passed passed, $total_skipped skipped, $total_bad failed"
    if [ -n "$failed_groups" ]; then
        echo "[ddc_test] groups with failures:$failed_groups" >&2
        exit 1
    fi
    exit 0
fi

# --each [path]: every test file under <path> (default tests/) started ON ITS OWN,
# all inside ONE container. Stage 3(d) of the quality programme: a test that is
# green only inside its group depends on what ran before it, and the next person
# to run that file alone gets a failure nobody can explain.
#
# One container, not one per file: there are 588 test files, and a container per
# file over ssh takes longer than the check is worth. The limits are the same as
# every other run here; each file gets its own wall-clock timeout so one hanging
# file cannot eat the budget for the rest.
#
# It prints ONLY the files that fail alone, plus a count. Silence is the good case.
if [ "$1" = "--each" ]; then
    TARGET="${2:-tests}"
    NAME="ddctest-each-$(date +%s)-$$"
    PER_FILE="${DDC_TEST_PER_FILE_TIMEOUT:-180}"
    REMOTE_SCRIPT=$(cat <<REMOTE
set -u
# 0. ONE RUN AT A TIME, ACROSS SESSIONS. Step 1 below removes every ddctest-*
#    container it finds - which, with two sessions testing on the same host,
#    was the OTHER session's running container (2026-09-26: two Claude sessions
#    killed each other's groups for an afternoon, and exit 137 was reported as
#    "OOM"). The lock makes a second caller wait instead. It lives as long as
#    this remote shell, so a dropped ssh session releases it.
exec 9>/tmp/ddc_test.lock
if ! flock -w ${LOCK_WAIT} 9; then
    echo "[ddc_test] another test run holds /tmp/ddc_test.lock for over ${LOCK_WAIT}s - giving up" >&2
    exit 3
fi
for old in \$(docker ps -aq --filter "name=ddctest-"); do
    docker rm -f "\$old" >/dev/null 2>&1
done
CFG=\$(mktemp -d /tmp/${NAME}-cfg-XXXX)
LOGS=\$(mktemp -d /tmp/${NAME}-logs-XXXX)
chown 1000:1000 "\$CFG" "\$LOGS"
cleanup() { docker rm -f "${NAME}" >/dev/null 2>&1; rm -rf "\$CFG" "\$LOGS"; }
trap cleanup EXIT INT TERM

docker run --rm --name "${NAME}" --init \\
    --memory=${MEMORY} --memory-swap=${MEMORY} --pids-limit=${PIDS} --cpus=${CPUS} \\
    -u ddc \\
    -e PYTHONDONTWRITEBYTECODE=1 \\
    -e PYTHONPATH=/opt/runtime/site-packages:/pytestlib \\
    -v "${REPO}":/app -v "\$CFG":/app/config -v "\$LOGS":/app/logs \\
    -v "${PYTESTLIB}":/pytestlib:ro \\
    -w /app --entrypoint sh "${IMAGE}" \\
    -c 'unset PYTHONOPTIMIZE
        checked=0; broken=0
        for f in \$(find ${TARGET} -name "test_*.py" | sort); do
            checked=\$((checked + 1))
            out=\$(timeout ${PER_FILE} python3 -m pytest -p no:cacheprovider \\
                   -o addopts="-q --tb=line" "\$f" 2>&1)
            rc=\$?
            if [ "\$rc" != "0" ] && [ "\$rc" != "5" ]; then
                broken=\$((broken + 1))
                echo "ALONE-FAIL \$f (exit \$rc)"
                echo "\$out" | tail -6 | sed "s/^/    /"
            fi
        done
        echo "[ddc_test] --each: \$checked files checked, \$broken fail alone"'
REMOTE
)
    ssh -o ConnectTimeout=10 $SSH_OPTS "$HOST" "bash -s" <<< "$REMOTE_SCRIPT"
    exit $?
fi

NAME="ddctest-$(date +%s)-$$"
REMOTE_SCRIPT=$(cat <<REMOTE
set -u
# 0. ONE RUN AT A TIME, ACROSS SESSIONS. Step 1 below removes every ddctest-*
#    container it finds - which, with two sessions testing on the same host,
#    was the OTHER session's running container (2026-09-26: two Claude sessions
#    killed each other's groups for an afternoon, and exit 137 was reported as
#    "OOM"). The lock makes a second caller wait instead. It lives as long as
#    this remote shell, so a dropped ssh session releases it.
exec 9>/tmp/ddc_test.lock
if ! flock -w ${LOCK_WAIT} 9; then
    echo "[ddc_test] another test run holds /tmp/ddc_test.lock for over ${LOCK_WAIT}s - giving up" >&2
    exit 3
fi
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
