# -*- coding: utf-8 -*-
"""Lost phone and lost recovery codes: the host owner has a way back (V3 §5.3).

Forcing people through a second factor with no way out locks them out - at
DDC's download numbers that is a certainty, an attack is not. The way back is
on the host, deliberately: whoever owns the host is outside the security
boundary anyway (V3 §5.2), and nobody who only has the panel password can use
it. ``scripts/disable_2fa.py`` moves two_factor.json aside (restorable), and
the image ships it next to reset_password.py.

COUNTER-CHECK (2026-09-22): written before the script existed; red. The file
is moved, not deleted - the test checks the aside copy exists.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_the_script_switches_2fa_off_and_keeps_a_copy(tmp_path, monkeypatch):
    state = tmp_path / "two_factor.json"
    state.write_text('{"enabled": true, "secret": "JBSWY3DPEHPK3PXP"}')
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "disable_2fa.py")],
        capture_output=True, text=True, timeout=60, cwd=ROOT,
        env={"DDC_CONFIG_DIR": str(tmp_path), "PYTHONPATH": f"{ROOT}:{':'.join(sys.path)}"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert not state.exists()
    aside = list(tmp_path.glob("two_factor.json.removed-*"))
    assert len(aside) == 1 and "JBSWY3DPEHPK3PXP" in aside[0].read_text()
    assert "off" in result.stdout.lower()


def test_the_script_says_so_when_there_is_nothing_to_do(tmp_path):
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "disable_2fa.py")],
        capture_output=True, text=True, timeout=60, cwd=ROOT,
        env={"DDC_CONFIG_DIR": str(tmp_path), "PYTHONPATH": f"{ROOT}:{':'.join(sys.path)}"},
    )
    assert result.returncode == 0 and "already off" in result.stdout.lower()


def test_the_image_ships_it():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY scripts/disable_2fa.py /app/scripts/disable_2fa.py" in dockerfile
