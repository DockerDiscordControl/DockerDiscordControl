# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Audit 2026-09 Package E regression tests       #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Package E (mech & donations): service / web / UI regressions.

E2 web donation cents, E5 speed from the real level, E6 difficulty responses,
E8 status cache loop, E9 donation result defaults, E10 delete by seq,
E11 donation modal without inline handlers, E12 animation cache writes.
"""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from services.donation.donation_management_service import DonationManagementService
from services.web.donation_service import DonationRequest, DonationResult, DonationService
from services.web.mech_web_service import MechAnimationRequest, MechDifficultyRequest, MechWebService

REPO_ROOT = Path(__file__).resolve().parents[3]


# ---------------------------------------------------------------------------
# E2 / E9 - web donation service
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("amount", [10.75, 0.5])
@patch("services.donation.unified_donation_service.process_web_ui_donation")
def test_e2_web_donation_keeps_cents(mock_process, amount, tmp_path):
    mock_process.return_value = SimpleNamespace(success=True, new_state=None, error_message=None)
    service = DonationService()
    service.NOTIFICATION_DIR = str(tmp_path)

    with patch("services.infrastructure.action_logger.log_user_action"):
        result = service.process_donation(DonationRequest(amount=amount, donor_name="Ann",
                                                          publish_to_discord=False))

    assert result.success is True  # $0.50 used to become int 0 -> rejected
    assert mock_process.call_args.kwargs["amount"] == amount


@pytest.mark.parametrize("amount", [0, -3, 0.001])
def test_e9_invalid_amount_returns_message_not_type_error(amount):
    result = DonationService().process_donation(DonationRequest(amount=amount, donor_name="Bob"))
    assert result.success is False
    assert result.message == "Invalid donation amount"
    assert result.error == "Invalid donation amount"
    assert result.status_code == 400


def test_e9_result_message_has_default():
    assert DonationResult(success=False, error="x").message == ""


# ---------------------------------------------------------------------------
# E5 - speed from the real level and the power bar
# ---------------------------------------------------------------------------

def test_e5_speed_follows_power_bar_without_level_guess():
    from services.mech.speed_levels import get_speed_level_for_state

    # Level 2 with a $16 power bar: $14.99 -> $15 must not drop 99 -> 75 (guessed level 3)
    assert get_speed_level_for_state(2, 14.99, power_max=16.0) == 93
    assert get_speed_level_for_state(2, 15.0, power_max=16.0) == 93
    assert get_speed_level_for_state(2, 0.0, power_max=16.0) == 0


def test_e5_combined_status_uses_real_level_not_lifetime_total():
    from services.mech import speed_levels

    evolution_info = {"name": "L2", "color": "#666666"}
    with patch("services.mech.mech_evolutions.get_evolution_info", return_value=evolution_info), \
         patch.object(speed_levels, "_get_evolution_context",
                      side_effect=AssertionError("level must not be guessed from totals")):
        status = speed_levels.get_combined_mech_status(
            Power_amount=8.0, total_donations_received=200.0, language="en",
            evolution_level=2, power_max=16.0,
        )
    # $200 lifetime used to be treated as level 11
    assert status["speed"]["level"] == 50


def test_e5_live_animation_uses_real_level_and_power_max():
    cache_service = MagicMock()
    cache_service.get_cached_status.return_value = SimpleNamespace(
        success=True, level=2, power=15.0, bars=SimpleNamespace(Power_max_for_level=16.0),
    )
    animation_service = MagicMock()
    animation_service.get_animation_with_speed_and_power.return_value = b"WEBP"

    with patch("services.mech.mech_status_cache_service.get_mech_status_cache_service",
               return_value=cache_service), \
         patch("services.mech.animation_cache_service.get_animation_cache_service",
               return_value=animation_service), \
         patch("services.mech.mech_evolutions.get_evolution_info",
               return_value={"name": "L2", "color": "#666666"}):
        result = MechWebService().get_live_animation(MechAnimationRequest())

    assert result.success is True
    level, speed = animation_service.get_animation_with_speed_and_power.call_args[0][:2]
    assert (level, speed) == (2, 93)


def test_e5_status_cache_passes_real_level_and_power_max():
    from services.mech.mech_status_cache_service import MechStatusCacheService

    data_result = SimpleNamespace(
        success=True, current_level=2, current_power=15.0, total_donated=200.0,
        level_name="L2", next_level_threshold=50, bars=SimpleNamespace(Power_max_for_level=16.0),
    )
    data_store = MagicMock()
    data_store.get_comprehensive_data.return_value = data_result
    with patch("services.mech.mech_data_store.get_mech_data_store", return_value=data_store), \
         patch("services.mech.speed_levels.get_combined_mech_status",
               # "level" completes the double: the cache now takes the speed
               # NUMBER from this same answer instead of a constant 50.0
               # (review C19). This test is about the arguments going in.
               return_value={"speed": {"level": 93, "description": "x",
                                       "color": "#fff"}}) as combined:
        out = MechStatusCacheService()._fetch_fresh_status(True)

    assert out.success is True
    assert combined.call_args.kwargs["evolution_level"] == 2
    assert combined.call_args.kwargs["power_max"] == 16.0


# ---------------------------------------------------------------------------
# E6 - difficulty responses carry 'success'
# ---------------------------------------------------------------------------

def test_e6_set_and_reset_difficulty_report_success():
    svc = MechWebService()
    with patch("services.mech.mech_service.get_mech_service", return_value=MagicMock()), \
         patch.object(svc, "_get_total_donations", return_value=0.0), \
         patch("services.mech.mech_evolutions.get_evolution_level", return_value=1), \
         patch("services.mech.mech_evolutions.get_evolution_level_info", return_value=None), \
         patch.object(svc, "_log_user_action"):
        set_result = svc.manage_difficulty(MechDifficultyRequest(operation="set", multiplier=1.5))
        reset_result = svc.manage_difficulty(MechDifficultyRequest(operation="reset"))

    # The route returns result.data as-is and the modal checks data.success
    assert set_result.success is True and set_result.data["success"] is True
    assert reset_result.success is True and reset_result.data["success"] is True
    assert set_result.data["message"]


def test_e6_failed_difficulty_data_has_success_false():
    result = MechWebService().manage_difficulty(MechDifficultyRequest(operation="set", multiplier=9.0))
    assert result.success is False
    assert result.data == {"success": False, "error": result.error}


# ---------------------------------------------------------------------------
# E8 - status cache background loop
# ---------------------------------------------------------------------------

def test_e8_background_loop_survives_permission_error():
    from services.mech.mech_status_cache_service import MechStatusCacheService

    svc = MechStatusCacheService()
    svc._refresh_interval = 0
    calls = []

    async def flaky_refresh():
        calls.append(1)
        if len(calls) == 1:
            raise PermissionError("snapshot not writable")
        svc._loop_running = False  # stop after the second iteration

    svc._background_refresh = flaky_refresh
    asyncio.run(svc.start_background_loop())

    assert len(calls) == 2  # the loop used to end forever after the first error


def test_e8_decay_error_does_not_skip_cache_refresh():
    from services.mech.mech_status_cache_service import MechStatusCacheService

    svc = MechStatusCacheService()
    progress = MagicMock()
    progress.get_state.side_effect = PermissionError("read-only snapshot")
    with patch("services.mech.progress_service.get_progress_service", return_value=progress), \
         patch.object(svc, "get_cached_status") as refresh:
        asyncio.run(svc._background_refresh())

    assert refresh.call_count == 2


# ---------------------------------------------------------------------------
# E10 - delete / restore by stable seq
# ---------------------------------------------------------------------------

def _write_events(path: Path, events) -> None:
    path.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")


def _donation(seq, donor, units=1000):
    return {"seq": seq, "type": "DonationAdded", "ts": f"2026-09-0{seq}T10:00:00+00:00",
            "mech_id": "main", "payload": {"donor": donor, "units": units}}


def _deletion(seq, deleted_seq, reason="admin_deletion"):
    return {"seq": seq, "type": "DonationDeleted", "ts": f"2026-09-0{seq}T11:00:00+00:00",
            "mech_id": "main", "payload": {"deleted_seq": deleted_seq, "reason": reason}}


@pytest.fixture
def event_log(tmp_path):
    path = tmp_path / "events.jsonl"
    with patch("services.donation.donation_management_service.get_progress_paths",
               return_value=SimpleNamespace(event_log=path)):
        yield path


def _delete(seq):
    progress = MagicMock()
    with patch("services.mech.progress_service.get_progress_service", return_value=progress):
        result = DonationManagementService().delete_donation(seq)
    return result, progress


def test_e10_delete_targets_seq_even_if_new_events_arrived(event_log):
    # Page loaded with Alice(1), Bob(2); Charlie(3) arrives before the admin clicks Bob
    _write_events(event_log, [_donation(1, "Alice"), _donation(2, "Bob"), _donation(3, "Charlie")])

    result, progress = _delete(2)

    assert result.success is True
    assert result.data["action"] == "Deleted"
    progress.delete_donation.assert_called_once_with(2)  # by index it would have hit Alice/Charlie


def test_e10_restore_via_deletion_event_seq(event_log):
    _write_events(event_log, [_donation(1, "Alice"), _deletion(2, 1)])

    result, progress = _delete(2)

    assert result.success is True
    assert result.data["action"] == "Restored"
    progress.delete_donation.assert_called_once_with(1)


def test_e10_stale_clicks_do_not_toggle_back(event_log):
    # Already restored (two toggles): clicking the old deletion row again must not delete it
    _write_events(event_log, [_donation(1, "Alice"), _deletion(2, 1), _deletion(3, 1, "admin_restore")])
    result, progress = _delete(2)
    assert result.success is False
    progress.delete_donation.assert_not_called()

    # Double click on delete: the second click must not restore it
    _write_events(event_log, [_donation(1, "Alice"), _deletion(2, 1)])
    result, progress = _delete(1)
    assert result.success is False
    progress.delete_donation.assert_not_called()


def test_e10_unknown_seq_fails(event_log):
    _write_events(event_log, [_donation(1, "Alice")])
    result, progress = _delete(42)
    assert result.success is False and "not found" in result.error
    progress.delete_donation.assert_not_called()


def test_e10_history_skips_corrupt_event_line(event_log):
    event_log.write_text(json.dumps(_donation(1, "Alice")) + "\n" + '{"seq": 2, "ty\n', encoding="utf-8")
    mech_service = MagicMock()
    mech_service.get_mech_state_service.return_value = SimpleNamespace(success=True, total_donated=10.0, level=1)
    with patch("services.mech.mech_service.get_mech_service", return_value=mech_service):
        result = DonationManagementService().get_donation_history()
    assert result.success is True
    assert [d["seq"] for d in result.data["donations"]] == [1]


# ---------------------------------------------------------------------------
# E11 - donation modal: no donor names in inline JS
# ---------------------------------------------------------------------------

def test_e11_modal_uses_data_attributes_and_delegation():
    # Its script moved to app/static on 2026-09-23; the markup stayed.
    html = ((REPO_ROOT / "app" / "templates" / "_donation_management_modal.html").read_text(encoding="utf-8")
            + (REPO_ROOT / "app" / "static" / "js" / "donation_management_modal.js").read_text(encoding="utf-8"))
    assert 'onclick="deleteDonation(' not in html
    assert 'onclick="restoreDonation(' not in html
    assert 'data-donation-action="delete" data-seq="${seq}"' in html
    assert 'data-donation-action="restore" data-seq="${seq}"' in html
    assert "container.addEventListener('click'" in html
    assert ".textContent = donorName" in html
    assert "/api/donations/delete/${seq}" in html


# ---------------------------------------------------------------------------
# E12 - animation cache writes / warmup off the event loop
# ---------------------------------------------------------------------------

def _bare_animation_service():
    from services.mech.animation_cache_service import AnimationCacheService
    # Skip __init__ (it touches the real cache directory)
    return AnimationCacheService.__new__(AnimationCacheService)


def test_e12_cache_write_is_atomic(tmp_path):
    svc = _bare_animation_service()
    target = tmp_path / "mech_L1_walk_small_S50.webp"
    target.write_bytes(b"old")

    svc._write_cache_file_atomic(target, b"new-bytes")
    assert target.read_bytes() == b"new-bytes"

    with patch("services.mech.animation_cache_service.os.replace", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            svc._write_cache_file_atomic(target, b"partial")
    assert target.read_bytes() == b"new-bytes"  # never a half-written file
    assert list(tmp_path.glob("*.tmp")) == []


# ---------------------------------------------------------------------------
# Follow-ups: donation routes and speed call sites outside the mech services
# ---------------------------------------------------------------------------

@pytest.fixture
def routes_app(monkeypatch):
    from app.blueprints.main_routes import main_bp
    from tests.unit.blueprints.test_main_automation_security_routes import _AUTH_HEADER, _build_app
    return _build_app(main_bp, monkeypatch), _AUTH_HEADER


def test_e9_donation_route_returns_validation_message_with_400(routes_app):
    app, auth = routes_app
    resp = app.test_client().post("/api/donation/submit", json={"amount": 0, "donor_name": "Bob"},
                                  headers=auth)
    # Used to be a generic 500 "Failed to process donation"
    assert resp.status_code == 400
    assert resp.get_json() == {"success": False, "error": "Invalid donation amount"}


def test_e10_delete_route_passes_event_seq(routes_app, monkeypatch):
    app, auth = routes_app
    svc = MagicMock()
    svc.delete_donation.return_value = SimpleNamespace(
        success=True, error=None,
        data={"action": "Restored", "type": "DonationDeleted", "deleted_seq": 7, "target_seq": 3},
    )
    monkeypatch.setattr("services.donation.donation_management_service.get_donation_management_service",
                        lambda: svc)

    resp = app.test_client().post("/api/donations/delete/7", headers=auth)

    assert resp.status_code == 200
    svc.delete_donation.assert_called_once_with(7)
    assert "#7" in resp.get_json()["message"]


def test_e5_donation_status_speed_uses_real_level():
    from services.web.donation_status_service import DonationStatusService

    with patch("services.mech.speed_levels._get_evolution_context",
               side_effect=AssertionError("level must not be guessed from totals")):
        info = DonationStatusService()._calculate_speed_information(
            power=15.0, total_donated=200.0, evolution_level=2, power_max=16.0)
    assert info["level"] == 93


def test_e12_async_warmup_runs_in_worker_thread():
    svc = _bare_animation_service()
    threads = []
    svc._perform_service_first_sync_warmup = lambda: threads.append(threading.get_ident())

    asyncio.run(svc._perform_service_first_async_warmup())

    assert threads and threads[0] != threading.get_ident()
