# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Audit 2026-09, package D2: the difficulty slider JS reads what MechWebService returns."""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

# The modal's script moved to app/static on 2026-09-23; the markup stayed.
MODAL = Path(__file__).resolve().parents[3] / "app" / "static" / "js" / "advanced_settings_modal.js"


def _function_body(name: str) -> str:
    src = MODAL.read_text(encoding="utf-8")
    start = src.index(f"function {name}(")
    nxt = re.compile(r"\n(?:async )?function ").search(src, start + 1)
    return src[start:nxt.start() if nxt else len(src)]


def _fields(body: str, var: str) -> set:
    return set(re.findall(rf"\b{var}\.(\w+)", body))


@pytest.fixture
def mech_web_service(monkeypatch):
    import services.mech.mech_data_store as data_store_module
    import services.mech.mech_evolutions as evolutions_module
    import services.mech.mech_service as mech_service_module
    from services.web.mech_web_service import MechWebService

    evolution_info = SimpleNamespace(success=True, difficulty_multiplier=1.5, evolution_mode="static", error=None)
    monkeypatch.setattr(
        data_store_module, "get_mech_data_store",
        lambda: SimpleNamespace(get_evolution_info=lambda request: evolution_info),
    )
    monkeypatch.setattr(evolutions_module, "get_evolution_level", lambda total: 3)
    monkeypatch.setattr(
        evolutions_module, "get_evolution_level_info",
        lambda level: SimpleNamespace(name=f"LEVEL {level}", base_cost=10 * level) if level <= 11 else None,
    )
    monkeypatch.setattr(
        mech_service_module, "get_mech_service",
        lambda *a, **k: SimpleNamespace(set_evolution_mode=lambda **kw: None),
    )
    service = MechWebService()
    monkeypatch.setattr(service, "_get_total_donations", lambda *a, **k: 42.0)
    monkeypatch.setattr(service, "_log_user_action", lambda **k: None)
    return service


def _run(service, **kwargs):
    from services.web.mech_web_service import MechDifficultyRequest

    return service.manage_difficulty(MechDifficultyRequest(**kwargs))


def test_load_reads_only_fields_returned_by_get(mech_web_service):
    result = _run(mech_web_service, operation="get")
    assert result.success
    data = result.data

    body = _function_body("loadDifficultyMultiplier")
    assert _fields(body, "data") <= set(data), _fields(body, "data") - set(data)
    assert _fields(body, "evo") <= set(data["simple_evolution"])
    assert "difficulty_multiplier" not in _fields(body, "data")

    # The next level's name comes from achieved_levels[current_level + 1].name
    assert "nextLevelInfo.name" in body
    next_level = data["simple_evolution"]["achieved_levels"][str(data["simple_evolution"]["current_level"] + 1)]
    assert next_level["name"] == "LEVEL 4"


@pytest.mark.parametrize("function_name", ["saveMechDifficulty", "saveMechOverrideToggle"])
def test_save_handlers_read_fields_returned_by_set_and_reset(mech_web_service, function_name):
    read = _fields(_function_body(function_name), "data")
    assert read == {"success", "message", "error"}

    set_result = _run(mech_web_service, operation="set", multiplier=1.5)   # manual_override on
    reset_result = _run(mech_web_service, operation="reset")               # manual_override off
    failed = _run(mech_web_service, operation="set", multiplier=None)
    assert set_result.success and reset_result.success and not failed.success
    for ok in (set_result.data, reset_result.data):
        assert ok["success"] is True and ok["message"]
    assert failed.data == {"success": False, "error": failed.error}
