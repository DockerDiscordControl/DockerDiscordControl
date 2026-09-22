# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Audit 2026-09, package C2 - admin / discord / action-log service regression tests.

C2-4  status overview channel config cache: one timestamp per channel entry
C2-5  action log: locked read-modify-write, unique temp file, no overwrite of a corrupt log
C2-6  admin_service: atomic admins.json write, no nonexistent json.JSONEncodeError
C2-7  no duplicate exception classes within one try statement (ruff B025)
"""

import ast
import json
import os
import stat
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

import services.discord.status_overview_service as sov
from services.admin.admin_service import AdminService
from services.infrastructure.action_log_service import ActionLogEntry, ActionLogService

PROJECT_ROOT = Path(__file__).resolve().parents[3]
IS_ROOT = hasattr(os, "geteuid") and os.geteuid() == 0


# ---------------------------------------------------------------------------
# C2-4
# ---------------------------------------------------------------------------

def test_c2_4_each_channel_cache_entry_expires_on_its_own(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(sov, "time", SimpleNamespace(time=lambda: now[0]))
    svc = sov.StatusOverviewService()
    cfg = {
        "default_channel_permissions": {},
        "channel_permissions": {"1": {"update_interval_minutes": 5}, "2": {"update_interval_minutes": 5}},
    }

    assert svc._get_channel_update_config(1, cfg).update_interval_minutes == 5
    now[0] = 1050.0
    svc._get_channel_update_config(2, cfg)  # a miss on another channel must not refresh channel 1

    cfg["channel_permissions"]["1"]["update_interval_minutes"] = 30
    cfg["channel_permissions"]["2"]["update_interval_minutes"] = 99
    now[0] = 1070.0
    assert svc._get_channel_update_config(1, cfg).update_interval_minutes == 30  # 70 s old -> reloaded
    assert svc._get_channel_update_config(2, cfg).update_interval_minutes == 5   # 20 s old -> cached


# ---------------------------------------------------------------------------
# C2-5
# ---------------------------------------------------------------------------

def _entry(n: int) -> ActionLogEntry:
    return ActionLogEntry(timestamp="2026-09-15T00:00:00+00:00", timestamp_unix=n, timezone="UTC",
                          action="START", target=f"c{n}", user="u", source="test", details="-",
                          entry_id=str(n))


def _temp_leftovers(directory: Path):
    return [p.name for p in directory.iterdir() if p.name.endswith(".tmp")]


class TestC25ActionLog:

    def test_concurrent_writes_lose_no_entries(self, tmp_path):
        svc = ActionLogService(logs_dir=str(tmp_path))
        errors = []

        def worker(base):
            for i in range(25):
                result = svc._save_to_json(_entry(base * 100 + i))
                if not result.success:
                    errors.append(result.error)

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert len(json.loads((tmp_path / "user_actions.json").read_text())) == 200
        assert _temp_leftovers(tmp_path) == []

    @pytest.mark.parametrize("corrupt", ['[{"id": "1"}, {"id": "2"', '{"not": "a list"}'])
    def test_corrupt_log_is_backed_up_not_overwritten(self, tmp_path, corrupt):
        log = tmp_path / "user_actions.json"
        log.write_text(corrupt)
        svc = ActionLogService(logs_dir=str(tmp_path))

        assert svc._save_to_json(_entry(1)).success

        backups = list(tmp_path.glob("user_actions.json.corrupt-*"))
        assert len(backups) == 1
        assert backups[0].read_text() == corrupt
        assert [e["id"] for e in json.loads(log.read_text())] == ["1"]

    @pytest.mark.skipif(IS_ROOT, reason="root ignores file permissions")
    def test_unreadable_log_is_never_overwritten(self, tmp_path):
        log = tmp_path / "user_actions.json"
        log.write_text(json.dumps([{"id": "keep"}]))
        svc = ActionLogService(logs_dir=str(tmp_path))
        os.chmod(log, 0)
        try:
            assert not svc._save_to_json(_entry(2)).success
        finally:
            os.chmod(log, 0o644)
        assert json.loads(log.read_text()) == [{"id": "keep"}]
        assert _temp_leftovers(tmp_path) == []

    def test_file_mode_is_preserved(self, tmp_path):
        log = tmp_path / "user_actions.json"
        log.write_text("[]")
        os.chmod(log, 0o640)
        svc = ActionLogService(logs_dir=str(tmp_path))
        assert svc._save_to_json(_entry(3)).success
        assert stat.S_IMODE(log.stat().st_mode) == 0o640


# ---------------------------------------------------------------------------
# C2-6
# ---------------------------------------------------------------------------

@pytest.fixture
def admins_file(monkeypatch, tmp_path):
    """Point admin_service at tmp_path/config via DDC_CONFIG_DIR.

    Used to stub the module's Path, because the service derived its file from
    Path(__file__).parents[2]; it now reads utils.config_paths.get_config_dir().
    """
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path / "config"))
    import services.config.config_service as cs
    monkeypatch.setattr(cs, "load_config", lambda: {"version": "test"})
    (tmp_path / "config").mkdir()
    return tmp_path / "config" / "admins.json"


class TestC26AdminService:

    def test_unserializable_data_returns_false_and_keeps_file(self, admins_file):
        original = json.dumps({"discord_admin_users": ["1"], "admin_notes": {}})
        admins_file.write_text(original)

        # Previously: truncated admins.json + AttributeError (json.JSONEncodeError)
        assert AdminService().save_admin_data(["2"], {"2": object()}) is False

        assert admins_file.read_text() == original
        assert _temp_leftovers(admins_file.parent) == []

    def test_save_replaces_file_and_keeps_mode(self, admins_file):
        admins_file.write_text(json.dumps({"discord_admin_users": [], "admin_notes": {}}))
        os.chmod(admins_file, 0o640)

        assert AdminService().save_admin_data(["1", "2"], {"1": "owner"}) is True

        data = json.loads(admins_file.read_text())
        # admin_containers joined the document with the per-admin container
        # assignment; an empty mapping is "nobody is assigned", which is what
        # this file always meant (review F1/F2).
        assert data == {"discord_admin_users": ["1", "2"], "admin_notes": {"1": "owner"},
                        "admin_containers": {}}
        assert stat.S_IMODE(admins_file.stat().st_mode) == 0o640
        assert _temp_leftovers(admins_file.parent) == []


# ---------------------------------------------------------------------------
# C2-7 (and the duplicate in C2-6)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rel_path", [
    "services/admin/admin_service.py",
    "services/config/server_config_service.py",
    "services/discord/channel_cleanup_service.py",
])
def test_c2_7_no_duplicate_exception_in_one_try(rel_path):
    tree = ast.parse((PROJECT_ROOT / rel_path).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        seen = set()
        for handler in node.handlers:
            if handler.type is None:
                continue
            types = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
            for exc_type in types:
                name = ast.unparse(exc_type)
                assert name not in seen, f"{rel_path}:{handler.lineno} catches {name} twice (unreachable)"
                seen.add(name)
