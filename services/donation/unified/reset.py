# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Donation reset helpers."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
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

        # Hold the progress lock so a concurrent donation cannot interleave with the reset
        from services.mech.progress_service import LOCK as progress_lock
        with progress_lock:
            # Das Ereignislog ist die einzige Aufzeichnung der echten Spenden dieser
            # Instanz. Vorher schrieb _clear_event_log() ersatzlos "" hinein - ein
            # versehentlicher Aufruf vernichtete die Historie endgueltig. Die Sicherung
            # laeuft deshalb VOR dem Loeschen und innerhalb derselben Sperre, und ein
            # Fehler dabei bricht den Reset ab (die OSError-Behandlung unten faengt ihn),
            # statt nur zu warnen: eine Sicherung, die im Fehlerfall weiterloescht,
            # waere keine. Dieselbe Konvention benutzt scripts/reset_donations.sh:32-44.
            # Siehe SPEC.md Z1.
            _backup_before_reset(progress_paths)
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


def _backup_before_reset(paths: ProgressPaths) -> Path:
    """Lege eine wiederherstellbare Kopie des Spendenbuchs an.

    Kopiert Ereignislog, Sequenzzaehler und Snapshots nach
    ``<data_dir>/backup_<Zeitstempel>/``. Der Zeitstempel bekommt bei Bedarf einen
    Zaehler, damit zwei Resets in derselben Sekunde nicht dieselbe Sicherung
    ueberschreiben - sonst koennte ein Doppelklick beide Staende vernichten.

    Fehler werden absichtlich NICHT gefangen: der Aufrufer bricht den Reset ab.
    """
    ziel = paths.data_dir / f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    lauf = 2
    while ziel.exists():
        ziel = ziel.with_name(f"{ziel.name.split('__')[0]}__{lauf}")
        lauf += 1
    ziel.mkdir(parents=True)

    if paths.event_log.exists():
        shutil.copy2(paths.event_log, ziel / paths.event_log.name)
    if paths.seq_file.exists():
        shutil.copy2(paths.seq_file, ziel / paths.seq_file.name)
    if paths.snapshot_dir.exists():
        shutil.copytree(paths.snapshot_dir, ziel / paths.snapshot_dir.name)
    return ziel


def _clear_event_log(paths: ProgressPaths) -> None:
    event_log = paths.event_log
    if event_log.exists():
        event_log.write_text("", encoding="utf-8")


def _reset_sequence_counter(paths: ProgressPaths) -> None:
    seq_file = paths.seq_file
    seq_file.write_text("0", encoding="utf-8")


def _write_fresh_snapshot(paths: ProgressPaths) -> None:
    # Build the level-1 snapshot with the same helpers a level-up uses, so the goal is the
    # real level-1 cost and all timestamps are timezone-aware UTC (a naive timestamp
    # stopped power decay until the first level-up)
    from services.mech import progress_service

    snapshot_file = paths.snapshot_for("main")
    snap = progress_service.Snapshot(mech_id="main")
    # Price the new goal for the community size like the startup step prices a new mech
    # (it will not re-price it: the count did not change). The event log was just
    # cleared, so this is member_count.json, else the count of the replaced snapshot.
    # A later rebuild_from_events keeps this goal (it reuses the goals the live path set).
    snap.last_user_count_sample = _previous_member_count(snapshot_file)
    progress_service.set_new_goal_for_next_level(
        snap, user_count=progress_service.member_count_for_goal(snap, events=[], default=0)
    )
    snap.last_decay_day = progress_service.today_local_str()

    snapshot_file.parent.mkdir(parents=True, exist_ok=True)
    tmp_file = snapshot_file.with_name(f".{snapshot_file.name}.reset.tmp")
    with tmp_file.open("w", encoding="utf-8") as handle:
        json.dump(snap.to_json(), handle, indent=2)
    os.replace(tmp_file, snapshot_file)


def _previous_member_count(snapshot_file) -> int:
    """Return the member count stored in the snapshot being replaced (0 if unavailable)."""
    try:
        with snapshot_file.open("r", encoding="utf-8") as handle:
            return max(0, int(json.load(handle).get("last_user_count_sample", 0) or 0))
    except (OSError, ValueError, TypeError, AttributeError):
        return 0

