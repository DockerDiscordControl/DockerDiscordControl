# -*- coding: utf-8 -*-
"""
THE FINDING (review C30, section 35 F4): `sanitize_log_message` is the
project's only log redactor and misses the shapes secrets actually have.

    re.sub(r'(token|password|key|secret)[:=]\\s*[^\\s]+', r'\\1=***', ...)
    re.sub(r'\\b[A-Za-z0-9]{32,}\\b', '***', ...)

The first pattern needs the exact `label=value` or `label:value` shape, so
"failed with token NzI3ODkw..." - a space instead of a separator - goes
through untouched. The second only catches one unbroken run of 32+
alphanumeric characters, so anything containing a '.', '-' or '_' passes,
which is the general shape of a Discord bot token and of most bearer and
session tokens.

WHAT IS TRUE ABOUT THE REACH, stated plainly: nothing in the project calls this
function. Only tests do. So no secret is being leaked today, and this is not an
outage - it is a trap. The function sits in `utils/common_helpers.py` under a
name the next person needing redaction will find and trust.

The counter-check matters more than usual here: a redactor that eats ordinary
log lines is worse than none, because it makes the log useless and people turn
it off. test_ordinary_log_lines_are_left_intact holds module paths, container
names, timestamps, versions and plain sentences untouched.
"""

import pytest

from utils.common_helpers import sanitize_log_message


@pytest.mark.parametrize("line", [
    "Login failed with token NzI3ODkwMTIzNDU2Nzg5MDEy.GaBcDe.FgHiJkLmNoPqRsTuVwXyZ",
    "Authorization Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIn0.abc",
    "password hunter2secretvalue",
    "api_key abcdef0123456789abcdef0123456789",
])
def test_a_secret_without_the_exact_shape_is_redacted(line):
    """THE FINDING: a space is a separator too, and dots do not make a value
    safe."""
    out = sanitize_log_message(line)

    for word in line.split():
        if len(word) >= 12 and any(c.isdigit() for c in word):
            assert word not in out, f"{word!r} survived in {out!r}"


def test_a_dotted_token_is_redacted():
    """The shape the second pattern was built for, with dots in it."""
    token = "MTIzNDU2Nzg5MDEyMzQ1Njc4.GAbCdE.f1g2h3i4j5k6l7m8n9o0p1q2"

    assert token not in sanitize_log_message(f"connecting with {token}")


def test_the_old_shapes_are_still_redacted():
    """What already worked keeps working."""
    assert "secret123abc" not in sanitize_log_message("token=secret123abc")
    assert "A" * 40 not in sanitize_log_message("api_value=" + "A" * 40)


@pytest.mark.parametrize("line", [
    "services.mech.progress.runtime loaded",
    "Container dockerdiscordcontrol started",
    "2026-09-20T15:46:58 Docker cache updated with 23 containers",
    "the key to a fast startup is a warm cache",
    "/mnt/user/appdata/dockerdiscordcontrol/config/channels",
    "Task t1 is due (scheduled: 2026-09-20 14:04:43, grace: 300s)",
])
def test_ordinary_log_lines_are_left_intact(line):
    """COUNTER-CHECK: a redactor that eats the log is worse than none - people
    switch it off. Nothing here is a secret and nothing may be touched."""
    assert sanitize_log_message(line) == line
