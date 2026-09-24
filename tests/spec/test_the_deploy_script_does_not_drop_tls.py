# -*- coding: utf-8 -*-
"""The deploy script hands the container its TLS mode.

OPERATOR DECISION (2026-09-25), after asking whether a certificate had to be
bought: no. A public certificate authority does not issue for a private
address at any price - the CA/Browser Forum rules forbid it - so buying one
would have done nothing for http://192.168.1.249:9374. A name would be needed,
and a name he owns already gets a free one. He chose the other way:
DDC_TLS_MODE=self-signed, which needs no name, no DNS and no proxy.

The machinery was already there (app/web/tls.py, v3.0 step 8, decided
2026-09-22: "reverse proxy recommended, self-signed as the fallback"). What
was missing is that nothing handed the container the mode, so every install
ran the default - off.

WHY THIS IS PINNED. The mode lives in one `-e` line of a shell script. A later
edit that reorders or trims those lines takes HTTPS away silently: the panel
keeps answering, on plain HTTP, and the only sign is a URL that still works.
The session cookie quietly stops being Secure and 2FA quietly stops being
offered, because both are gated on TLS by design.

HOW THIS TEST CAN FAIL: a deploy script that stops handing the mode over, one
that bakes a mode in with no way past it, or a health check that keeps speaking
HTTP while the panel speaks HTTPS.

COUNTER-CHECK (2026-09-25): red before - the script named no TLS mode at all,
and the case that reads the line raised StopIteration because there was no line
to read. Then three sabotages on the green baseline: the line dropped as if by
a tidy-up, the mode baked in with no override, and the health check put back to
plain HTTP - one case red each.

WHAT IT DOES NOT PIN: which mode. `off`, `proxy` and `self-signed` are all
legitimate - the decision was explicitly "both ways" - so the case requires
that the script PASSES the setting on, not what it is set to. An installation
behind a proxy sets `proxy` and must not fail this.
"""

import re
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[2]
REBUILD = PROJECT / "scripts" / "rebuild.sh"
DOCKERFILE = PROJECT / "Dockerfile"
TLS = PROJECT / "app" / "web" / "tls.py"


def test_the_deploy_script_passes_the_mode():
    """THE GAP: the machinery existed and nothing switched it on."""
    script = REBUILD.read_text(encoding="utf-8")

    assert "DDC_TLS_MODE" in script, (
        "scripts/rebuild.sh does not hand the container a TLS mode, so every "
        "rebuild falls back to plain HTTP")
    line = next(l for l in script.splitlines() if "DDC_TLS_MODE" in l)

    assert line.lstrip().startswith("-e "), f"not passed as an environment variable: {line.strip()}"


def test_the_mode_can_still_be_overridden():
    """An installation behind a reverse proxy sets `proxy`, and one that wants
    none sets `off`. A value baked in with no way past it would make this
    script useless to everybody but its author."""
    line = next(l for l in REBUILD.read_text(encoding="utf-8").splitlines()
                if "DDC_TLS_MODE" in l)

    assert "${DDC_TLS_MODE" in line, (
        f"the mode cannot be overridden from the environment: {line.strip()}")


def test_the_health_check_follows_the_mode():
    """A container serving HTTPS while its health check speaks HTTP is a
    healthy-looking container that Docker keeps restarting."""
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    check = dockerfile[dockerfile.index("HEALTHCHECK"):]
    check = check[:check.index("ENTRYPOINT")]

    assert "DDC_TLS_MODE" in check, "the health check ignores the TLS mode"
    assert "https" in check, "the health check cannot speak HTTPS"
    assert "_create_unverified_context" in check, (
        "the health check verifies a certificate that is self-signed by design")


@pytest.mark.parametrize("mode", ["off", "proxy", "self-signed"])
def test_the_three_modes_are_the_ones_the_code_knows(mode):
    """The script's comment names them; the code decides them. If a mode is
    ever renamed, a comment telling the operator to use the old name is worse
    than no comment."""
    from app.web.tls import tls_mode

    assert tls_mode({"DDC_TLS_MODE": mode}) == mode


def test_an_unknown_mode_stops_the_start():
    """It must not quietly fall back to plain HTTP: an operator who mistypes
    the mode would believe he has TLS."""
    from app.web.tls import tls_mode

    with pytest.raises(ValueError):
        tls_mode({"DDC_TLS_MODE": "https"})


def test_the_self_signed_certificate_is_kept_with_the_configuration():
    """It is a secret and it must survive a rebuild; config/ is the one
    directory bound into the container from the host."""
    script = REBUILD.read_text(encoding="utf-8")

    assert re.search(r'-v\s+"?\$\(pwd\)/config"?:/app/config', script), (
        "config/ is not bound in, so a new certificate would be made on every "
        "rebuild and every browser would warn again")
    assert 'Path(get_config_dir()) / "tls"' in (PROJECT / "run.py").read_text(encoding="utf-8")
