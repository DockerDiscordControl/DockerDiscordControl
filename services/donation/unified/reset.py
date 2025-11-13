"""Donation reset helpers."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from services.donation.unified.models import DonationResult
from services.donation.unified.processors import clear_mech_cache
from services.donation.unified import events
from services.mech.progress_paths import ProgressPaths, get_progress_paths
from services.exceptions import MechServiceError


def reset_donations(
    mech_service,
    event_manager,
    *,
    source: str,
    paths: Optional[ProgressPaths] = None,
) -> DonationResult:
    """Reset donations and emit the corresponding event."""

    try:
        old_state = mech_service.get_state()

        progress_paths = paths or get_progress_paths()

        _clear_event_log(progress_paths)
        _reset_sequence_counter(progress_paths)
        _write_fresh_snapshot(progress_paths)

        new_state = mech_service.get_state()

        clear_mech_cache()
        events.emit_reset_event(event_manager, source=source, old_state=old_state, new_state=new_state)

        return DonationResult.from_states(
            success=True,
            old_state=old_state,
            new_state=new_state,
            event_emitted=True,
        )
    except MechServiceError as exc:  # pragma: no cover - defensive logging
        # Mech service errors (get_state failures)
        return DonationResult.from_states(
            success=False,
            old_state=None,
            new_state=None,
            error_message=f"Mech service error: {exc}",
            error_code="MECH_SERVICE_ERROR",
        )
    except (IOError, OSError) as exc:  # pragma: no cover - defensive logging
        # File I/O errors (event log, sequence counter, snapshot)
        return DonationResult.from_states(
            success=False,
            old_state=None,
            new_state=None,
            error_message=f"File I/O error: {exc}",
            error_code="FILE_ERROR",
        )
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive logging
        # JSON errors (unlikely but possible)
        return DonationResult.from_states(
            success=False,
            old_state=None,
            new_state=None,
            error_message=f"JSON error: {exc}",
            error_code="JSON_ERROR",
        )
    except (RuntimeError, AttributeError) as exc:  # pragma: no cover - defensive logging
        # Event emission or other runtime errors
        return DonationResult.from_states(
            success=False,
            old_state=None,
            new_state=None,
            error_message=str(exc),
            error_code="RESET_ERROR",
        )


def _clear_event_log(paths: ProgressPaths) -> None:
    event_log = paths.event_log
    if event_log.exists():
        event_log.write_text("", encoding="utf-8")


def _reset_sequence_counter(paths: ProgressPaths) -> None:
    seq_file = paths.seq_file
    seq_file.write_text("0", encoding="utf-8")


def _write_fresh_snapshot(paths: ProgressPaths) -> None:
    snapshot_file = paths.snapshot_for("main")
    fresh_snapshot = {
        "mech_id": "main",
        "level": 1,
        "evo_acc": 0,
        "power_acc": 0,
        "goal_requirement": 400,
        "difficulty_bin": 1,
        "goal_started_at": datetime.now().isoformat(),
        "last_decay_day": datetime.now().date().isoformat(),
        "power_decay_per_day": 100,
        "version": 0,
        "last_event_seq": 0,
        "mech_type": "default",
        "last_user_count_sample": 0,
        "cumulative_donations_cents": 0,
    }

    snapshot_file.parent.mkdir(parents=True, exist_ok=True)
    with snapshot_file.open("w", encoding="utf-8") as handle:
        json.dump(fresh_snapshot, handle, indent=2)

