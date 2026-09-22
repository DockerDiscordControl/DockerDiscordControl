# -*- coding: utf-8 -*-
"""The configuration guide does not offer a setting DDC ignores.

THE FINDING: docs/CONFIGURATION.md still lists "Docker Socket | Docker socket
path | /var/run/docker.sock" among the advanced settings. Since v3.0 every
Docker client follows DOCKER_HOST and that field is ignored - the client
factory even says so once in the log. A guide that offers it sends an
operator whose socket really lives elsewhere to type it in and wait for
something to happen.

The same page says nothing about the container watchdog, the one feature of
this release an operator has to set up themselves.

COUNTER-CHECK (2026-09-22): red before - the row was there and the watchdog
was not.
"""

from pathlib import Path

import pytest

GUIDE = (Path(__file__).resolve().parents[2] / "docs" / "CONFIGURATION.md").read_text(encoding="utf-8")


def test_the_retired_socket_setting_is_not_offered():
    """Not as a SETTING - the sentence that says it is ignored may name it."""
    advanced = GUIDE[GUIDE.index("### Advanced Settings"):GUIDE.index("## Environment Variables")]
    rows = [line for line in advanced.splitlines() if line.startswith("|")]
    assert not [row for row in rows if "socket" in row.lower()], rows


def test_the_guide_says_what_replaced_it():
    assert "DOCKER_HOST" in GUIDE


def test_the_watchdog_is_explained():
    assert "Container state" in GUIDE
    assert "unhealthy" in GUIDE.lower()


@pytest.mark.parametrize("variable", ["DDC_TRUSTED_PROXIES", "DDC_TLS_MODE", "DDC_TLS_HOSTNAMES"])
def test_the_new_variables_are_documented(variable):
    """The three v3.0 variables an operator may have to set. The README has them;
    the configuration guide, which is where people look for variables, did not.

    COUNTER-CHECK (2026-09-22): red before - none of the three was in the file.
    """
    assert variable in GUIDE
