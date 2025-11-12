"""Functional coverage for unified donation scenarios."""

from __future__ import annotations

import importlib
import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from services.donation.unified import models as donation_models
from services.mech.progress import reset_progress_runtime
from services.mech.progress_paths import clear_progress_paths_cache


class FakeEventManager:
    """Minimal event manager that records emitted events for assertions."""

    def __init__(self) -> None:
        self.events = []

    def emit_event(self, *, event_type: str, source_service: str, data: dict) -> None:
        self.events.append(
            {
                "event_type": event_type,
                "source_service": source_service,
                "data": data,
            }
        )


@pytest.fixture
def donation_env(tmp_path, monkeypatch):
    """Provide an isolated donation/runtime environment for functional tests."""

    data_dir = tmp_path / "progress"
    monkeypatch.setenv("DDC_PROGRESS_DATA_DIR", str(data_dir))

    # Reset cached singletons so the progress runtime picks up the temporary paths.
    reset_progress_runtime()
    clear_progress_paths_cache()

    progress_service = importlib.reload(importlib.import_module("services.mech.progress_service"))
    progress_service._progress_service = None

    runtime = progress_service.runtime

    level_costs = {str(level): 100 for level in range(1, 12)}
    dynamic_costs = {str(bin_idx): 0 for bin_idx in range(1, 22)}
    config = {
        "timezone": "UTC",
        "difficulty_bins": [0, 50],
        "level_base_costs": level_costs,
        "bin_to_dynamic_cost": dynamic_costs,
        "mech_power_decay_per_day": {"default": 100},
    }

    runtime.configure_defaults(config)
    runtime.paths.config_file.write_text(json.dumps(config), encoding="utf-8")
    progress_service.CFG = runtime.load_config(refresh=True)
    progress_service.TZ = runtime.timezone(refresh=True)
    runtime.paths.member_count_file.write_text(json.dumps({"count": 25}), encoding="utf-8")

    mech_adapter_module = importlib.reload(importlib.import_module("services.mech.mech_service_adapter"))
    mech_adapter_module._mech_service_adapter = None
    adapter = mech_adapter_module.MechServiceAdapter()

    config_module = importlib.import_module("services.config.config_service")
    monkeypatch.setattr(
        config_module,
        "get_config_service",
        lambda: SimpleNamespace(
            get_evolution_mode_service=lambda request: config_module.GetEvolutionModeResult(
                success=True,
                use_dynamic=True,
                difficulty_multiplier=1.0,
            )
        ),
        raising=False,
    )

    donation_service_module = importlib.reload(importlib.import_module("services.donation.unified.service"))
    donation_service_module._unified_donation_service = None

    fake_events = FakeEventManager()
    monkeypatch.setattr(donation_service_module, "get_event_manager", lambda: fake_events, raising=False)
    monkeypatch.setattr(donation_service_module, "get_mech_service", lambda: adapter, raising=False)
    monkeypatch.setattr(donation_service_module, "clear_mech_cache", lambda: None, raising=False)

    donation_models_module = importlib.reload(donation_models)

    context = SimpleNamespace(
        service_module=donation_service_module,
        models=donation_models_module,
        adapter=adapter,
        progress_service=progress_service,
        runtime=runtime,
        event_manager=fake_events,
        mech_adapter_module=mech_adapter_module,
    )

    yield context

    donation_service_module._unified_donation_service = None
    mech_adapter_module._mech_service_adapter = None
    progress_service._progress_service = None
    reset_progress_runtime()
    clear_progress_paths_cache()
    monkeypatch.delenv("DDC_PROGRESS_DATA_DIR", raising=False)


def test_donation_level_up_and_surplus_carryover(donation_env):
    service = donation_env.service_module.UnifiedDonationService()
    request = donation_env.models.DonationRequest(donor_name="Tester", amount=1.5, source="web")

    result = service.process_donation(request)

    assert result.success
    assert result.level_changed
    assert result.old_level == 1
    assert result.new_level == 2
    assert result.new_power == pytest.approx(0.5)

    snapshot = donation_env.progress_service.load_snapshot("main")
    assert snapshot.level == 2
    assert snapshot.evo_acc == 50
    assert snapshot.power_acc == 50

    assert donation_env.event_manager.events
    payload = donation_env.event_manager.events[-1]
    assert payload["event_type"] == "donation_completed"
    assert payload["data"]["level_changed"] is True


def test_power_decay_reduces_power_over_time(donation_env):
    service = donation_env.service_module.UnifiedDonationService()
    request = donation_env.models.DonationRequest(donor_name="Decay", amount=0.5, source="web")

    initial = service.process_donation(request)
    assert initial.success
    assert initial.new_power == pytest.approx(0.5)

    snapshot = donation_env.progress_service.load_snapshot("main")
    snapshot.goal_started_at = (
        datetime.now(ZoneInfo("UTC")) - timedelta(days=2)
    ).isoformat()
    donation_env.progress_service.persist_snapshot(snapshot)

    decayed_state = donation_env.adapter.tick_decay()
    assert decayed_state.power_level == pytest.approx(0.0, abs=1e-6)
    assert decayed_state.power_level < initial.new_power


def test_system_donation_only_affects_power(donation_env):
    before = donation_env.progress_service.load_snapshot("main")
    base_level = before.level
    base_evo = before.evo_acc
    base_power = before.power_acc

    state = donation_env.adapter.add_system_donation(amount=2.5, event_name="Anniversary Bonus")

    after = donation_env.progress_service.load_snapshot("main")
    assert after.level == base_level
    assert after.evo_acc == base_evo
    assert after.power_acc == base_power + 250

    assert state.power_level == pytest.approx((base_power + 250) / 100)
    assert state.evolution_level == base_level
