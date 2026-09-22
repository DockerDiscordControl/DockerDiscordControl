# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                      #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Audit 2026-09, package F - scripts / deployment regressions.

F5  reset_password.py uses change_web_ui_password() and is shipped in the image
F8  entrypoint fix_permissions detects wrong-owned entries inside the data dirs
F2/F3/F4/F9 static checks of rebuild.sh, start.sh, requirements, Dockerfile
"""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[3]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _load_reset_password():
    spec = importlib.util.spec_from_file_location(
        "ddc_reset_password_script", ROOT / "scripts" / "reset_password.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------- #
# F5                                                                           #
# --------------------------------------------------------------------------- #

class TestF5ResetPassword:
    @pytest.fixture
    def config_service(self, monkeypatch):
        import services.config.config_service as cs

        # save_config() must not be used any more (it wrote the decrypted token and
        # left the encrypted token under the old password hash).
        monkeypatch.setattr(cs, "save_config", MagicMock(side_effect=AssertionError("save_config used")), raising=False)
        return cs

    def test_uses_change_web_ui_password(self, monkeypatch, config_service):
        calls = []
        monkeypatch.setattr(config_service, "change_web_ui_password", calls.append, raising=False)
        monkeypatch.setenv("DDC_ADMIN_PASSWORD", "N3w-Passw0rd!")
        assert _load_reset_password().reset_password() is True
        assert calls == ["N3w-Passw0rd!"]

    def test_validation_error_is_reported(self, monkeypatch, config_service, capsys):
        def _reject(password):
            raise ValueError("Password must be at least 8 characters")

        monkeypatch.setattr(config_service, "change_web_ui_password", _reject, raising=False)
        monkeypatch.setenv("DDC_ADMIN_PASSWORD", "short")
        assert _load_reset_password().reset_password() is False
        assert "at least 8 characters" in capsys.readouterr().out

    def test_save_error_is_reported(self, monkeypatch, config_service, capsys):
        from services.exceptions import ConfigSaveError

        def _fail(password):
            raise ConfigSaveError("disk full")

        monkeypatch.setattr(config_service, "change_web_ui_password", _fail, raising=False)
        monkeypatch.setenv("DDC_ADMIN_PASSWORD", "N3w-Passw0rd!")
        assert _load_reset_password().reset_password() is False
        assert "Failed to save configuration" in capsys.readouterr().out

    def test_interactive_mismatch_changes_nothing(self, monkeypatch, config_service):
        change = MagicMock()
        monkeypatch.setattr(config_service, "change_web_ui_password", change, raising=False)
        monkeypatch.delenv("DDC_ADMIN_PASSWORD", raising=False)
        module = _load_reset_password()
        answers = iter(["first-password", "second-password"])
        monkeypatch.setattr(module.getpass, "getpass", lambda prompt="": next(answers))
        assert module.reset_password() is False
        change.assert_not_called()

    def test_shipped_in_image_and_documented_with_ddc_user(self):
        assert "COPY --chown=ddc:ddc scripts/reset_password.py /app/scripts/reset_password.py" in _read("Dockerfile")
        for relative in ("scripts/reset_password.py", "scripts/safe_reset_mech.sh", "README.md"):
            for line in _read(relative).splitlines():
                if "docker exec" in line and ("reset_password" in line or "python3 -c" in line):
                    assert "-u ddc" in line, f"{relative}: {line.strip()}"


# --------------------------------------------------------------------------- #
# F8                                                                           #
# --------------------------------------------------------------------------- #

class TestF8EntrypointPermissions:
    def test_data_dirs_include_cached_animations_and_assets(self):
        match = re.search(r'^DATA_DIRS="([^"]*)"', _read("scripts/entrypoint.sh"), re.M)
        assert match
        dirs = match.group(1).split()
        for expected in ("/app/config", "/app/logs", "/app/cached_displays", "/app/cached_animations", "/app/assets"):
            assert expected in dirs

    def test_entrypoint_syntax(self):
        sh = shutil.which("sh")
        if not sh:
            pytest.skip("no sh available")
        result = subprocess.run([sh, "-n", str(ROOT / "scripts" / "entrypoint.sh")], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr

    def test_fix_permissions_only_touches_unusable_entries(self, tmp_path):
        import stat

        sh = shutil.which("sh")
        if not sh or not shutil.which("find"):
            pytest.skip("needs sh + find")
        primary = os.getgid()
        other = next((g for g in os.getgroups() if g != primary), None)
        if other is None:
            pytest.skip("needs a supplementary group to create foreign-group entries without root")

        data = tmp_path / "data"
        smb_dir = data / "smb_dir"
        smb_dir.mkdir(parents=True)
        smb_file = smb_dir / "written_via_smb.json"
        smb_file.write_text("{}")
        locked_file = smb_dir / "created_by_docker_exec.json"
        locked_file.write_text("{}")
        locked_dir = data / "locked_dir"
        locked_dir.mkdir()
        # Usable through the "other" bits (like 1001:100 766 files on the SMB share) -> untouched
        os.chown(smb_file, -1, other)
        os.chmod(smb_file, 0o766)
        os.chown(smb_dir, -1, other)
        os.chmod(smb_dir, 0o777)
        # Not usable by the app user -> must be fixed
        os.chmod(locked_file, 0o000)
        os.chmod(locked_dir, 0o000)

        body = _read("scripts/entrypoint.sh").rsplit('main "$@"', 1)[0]
        chown_app = 'chown "$target_uid:$target_gid" /app 2>/dev/null || true'
        assert chown_app in body
        body = body.replace(chown_app, ":")  # never touch the real /app from a test
        harness = tmp_path / "harness.sh"
        harness.write_text(body + f'\nDATA_DIRS="{data}"\nfix_permissions {os.getuid()} {primary}\n')

        result = subprocess.run([sh, str(harness)], capture_output=True, text=True, timeout=60)
        assert "needs fix" in result.stdout, result.stdout + result.stderr
        assert "Fixed unusable entries" in result.stdout, result.stdout + result.stderr

        for path, mode in ((smb_file, 0o766), (smb_dir, 0o777)):
            st = os.stat(path)
            assert (st.st_gid, stat.S_IMODE(st.st_mode)) == (other, mode), path
        assert stat.S_IMODE(os.stat(locked_file).st_mode) & 0o600 == 0o600
        assert stat.S_IMODE(os.stat(locked_dir).st_mode) & 0o700 == 0o700

        again = subprocess.run([sh, str(harness)], capture_output=True, text=True, timeout=60)
        assert "already usable" in again.stdout, again.stdout + again.stderr


# --------------------------------------------------------------------------- #
# F2 / F3 / F4 / F9 static checks                                              #
# --------------------------------------------------------------------------- #

def test_f2_no_predictable_secret_key_fallbacks():
    assert "temporary-dev-key-" not in _read("scripts/rebuild.sh")
    assert "dev-only-$(date" not in _read("scripts/start.sh")


def test_f3_requirements():
    prod = _read("requirements.prod.txt")
    assert re.search(r"^croniter>=", prod, re.M)
    assert re.search(r"^psutil>=", prod, re.M)
    dev = _read("requirements.txt")
    for name in ("waitress==", "Flask-WTF>=", "croniter>=", "psutil>="):
        assert re.search(rf"^{re.escape(name)}", dev, re.M), name


def test_f4_dockerfile_healthcheck():
    dockerfile = _read("Dockerfile")
    assert re.search(r"^HEALTHCHECK ", dockerfile, re.M)
    # Audit R3-2/R3-3: loopback URL, proxies ignored, port from DDC_WEB_PORT (default 9374)
    assert "'http://127.0.0.1:' + p + '/health'" in dockerfile
    assert "ProxyHandler({})" in dockerfile
    assert "DDC_WEB_PORT" in dockerfile and "'9374'" in dockerfile


def test_f9_rebuild_docker_run_failure_is_visible():
    text = _read("scripts/rebuild.sh")
    match = re.search(r"^if docker run -d \\\n(.*?); then$", text, re.M | re.S)
    assert match, "docker run must be checked with 'if docker run ...; then'"
    assert "2>/dev/null" not in match.group(1)  # errors must stay visible
    assert "if [ $? -eq 0 ]" not in text
    # the user's prune block is kept, with a corrected (host-wide) comment
    assert "docker builder prune -a -f" in text
    assert "HOST-WIDE" in text
