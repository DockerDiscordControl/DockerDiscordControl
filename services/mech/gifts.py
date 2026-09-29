# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Power gifts: what a mech is given, and when.

Two campaigns use this. The welcome gift a fresh installation gets once, and
the release gift: when DDC starts on a new version and the mech has run dry,
it is given three days of the energy its level consumes. Both go to the ENERGY
account only - a gift never buys evolution progress.

The release gift is decided at the FIRST start of a version, and only then:
a mech that still has energy at that moment gets nothing for this version,
not three days later when it runs dry (operator, 2026-09-29).

A gift is refused when the mech still has energy, and when the event log
already carries that campaign - so a restart gives nothing a second time.

Split out of progress_service.py (2026-09-23), which is on the size list and
may only shrink.
"""

from __future__ import annotations
from utils.logging_utils import get_module_logger

import hashlib
import json
import logging
from typing import Optional, Tuple, TYPE_CHECKING

from utils.atomic_io import atomic_write_json

from services.mech.progress_service import (
    DATA_DIR, LOCK, Event, ProgressState, apply_decay_on_demand, apply_power_event,
    battery_capacity_cents, compute_ui_state, current_power_cents, decay_per_day, load_snapshot,
    next_seq, now_utc_iso, persist_snapshot, read_events, append_event,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from services.mech.progress_service import ProgressService

logger = get_module_logger('gifts')


def three_days_of_energy(level: int) -> int:
    """Three days of this level's consumption, in cents (level 1: $3.00).

    What a new DDC release gives a mech that has run dry - the decay IS the
    energy consumption, so three days of it is three days of standing still.
    """
    return 3 * decay_per_day(level)


def deterministic_gift_1_3(mech_id: str, campaign_id: str) -> int:
    h = hashlib.sha256((mech_id + "|" + campaign_id).encode("utf-8")).hexdigest()
    n = int(h[:8], 16)
    return ((n % 3) + 1) * 100  # 1-3 dollars in cents


def _currently_deleted(events) -> set:
    """The event seqs that are deleted right now.

    Deletion is a toggle in this ledger: an odd number of DonationDeleted
    events for one seq means it is deleted, an even number means it was
    restored (see ProgressService.delete_donation).
    """
    counts: dict = {}
    for event in events:
        if event.type != "DonationDeleted":
            continue
        seq = (event.payload or {}).get("deleted_seq")
        if seq is not None:
            counts[seq] = counts.get(seq, 0) + 1
    return {seq for seq, count in counts.items() if count % 2 == 1}


def grant_power_gift(service: "ProgressService", campaign_id: str,
                     gift_cents: Optional[int] = None) -> Tuple[ProgressState, Optional[int]]:
    """Grant a power gift if power is 0 AND the campaign has not been used.

    ``gift_cents`` fixes the amount (a release gives three days of energy);
    without it the campaign's deterministic $1-$3 is used. Returns
    (state, gift_dollars or None).
    """
    with LOCK:
        service._heal_if_lagging(read_events())
        snap = load_snapshot(service.mech_id)
        # Both refusals below write only if apply_decay_on_demand() actually
        # changed something - it is a documented no-op apart from backfilling
        # last_decay_day once. A refused gift changed nothing else, and
        # rewriting the snapshot for it is the pattern get_state() was
        # already taken off (review D26).
        decay_day_before = snap.last_decay_day
        apply_decay_on_demand(snap)

        def _persist_if_decay_day_changed() -> None:
            if snap.last_decay_day != decay_day_before:
                persist_snapshot(snap)

        # Use the CURRENT (decayed) power: raw power_acc stays > 0 while decay runs
        if current_power_cents(snap) > 0:
            logger.info(f"Power gift skipped: power > 0")
            _persist_if_decay_day_changed()
            return compute_ui_state(snap), None

        # CHECK FOR DUPLICATE: Search event log for this campaign_id. A gift the
        # admin DELETED does not count - deleting it rebuilds the power back
        # down, and the campaign would otherwise be spent on a gift that is no
        # longer in the ledger.
        all_events = read_events()
        deleted = _currently_deleted(all_events)
        for evt in all_events:
            if evt.type == "PowerGiftGranted" and evt.mech_id == service.mech_id:
                existing_campaign = evt.payload.get("campaign_id")
                if existing_campaign == campaign_id and evt.seq not in deleted:
                    logger.info(f"Power gift skipped: campaign_id '{campaign_id}' already used")
                    _persist_if_decay_day_changed()
                    return compute_ui_state(snap), None

        if gift_cents is None:
            gift_cents = deterministic_gift_1_3(service.mech_id, campaign_id)
        # Only what FITS is given: the ledger entry is what the history, the
        # totals and the average are built from, so a gift written as $15.00
        # when $10.00 landed overstates every one of them.
        capacity = battery_capacity_cents(snap)
        if capacity is not None:
            gift_cents = min(gift_cents, max(0, capacity - current_power_cents(snap)))
        if gift_cents <= 0:
            # Three days of a level that consumes nothing is nothing. Writing
            # the event anyway put a "🎁 Power Gift - $0.00" row in the donation
            # history, dragged the average down, and spent the campaign - so
            # that version could never grant anything again.
            logger.info(f"Power gift skipped: nothing would fit (level {snap.level})")
            _persist_if_decay_day_changed()
            return compute_ui_state(snap), None

        evt = Event(
            seq=next_seq(),
            ts=now_utc_iso(),
            type="PowerGiftGranted",
            mech_id=service.mech_id,
            payload={"campaign_id": campaign_id, "power_units": gift_cents},
        )
        append_event(evt)

        # Power is 0 here: fold any decay debt and restart the decay clock before adding
        apply_power_event(snap, evt)
        snap.version += 1
        snap.last_event_seq = evt.seq
        persist_snapshot(snap)

        # gift_cents is already what FITS (capped above), which is what the
        # event carries and what landed. Measuring snap.power_acc against its
        # value before apply_power_event would subtract the decay that the
        # settle inside it takes off - and report a NEGATIVE gift for a mech
        # whose raw power_acc had not been settled yet.
        gift_dollars = gift_cents / 100.0
        logger.info(f"Power gift granted: ${gift_dollars:.2f}")
        return compute_ui_state(snap), gift_dollars


RELEASES_CHECKED_FILE = "release_gifts_checked.json"


def _release_decisions() -> dict:
    """What the first start of each version decided: "granted" or "passed"."""
    try:
        with open(DATA_DIR / RELEASES_CHECKED_FILE, "r", encoding="utf-8") as f:
            decisions = json.load(f).get("versions", {})
        return {k: v for k, v in decisions.items() if isinstance(k, str) and isinstance(v, str)}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, AttributeError) as e:
        logger.warning(f"Release gift record unreadable, starting a new one: {e}")
        return {}


def release_gift(service: "ProgressService", version: str) -> Tuple[ProgressState, Optional[int]]:
    """Three days of energy for a mech that is dry at the first start of a release.

    The first start of a version decides and is recorded. A version it passed
    over - the mech had energy - gives nothing on any later start, also not
    after the mech has run dry under it. Until 2026-09-29 only a GRANTED gift
    spent the campaign, so a mech with energy at the update was handed its
    three days by whichever restart found it empty, days later.

    A version whose gift was granted stays with the event log's campaign
    check, as before: a restart is refused, and a gift the admin deleted
    frees the campaign again (test_a_deleted_gift_frees_its_campaign).
    """
    with LOCK:
        decisions = _release_decisions()
        if decisions.get(version) == "passed":
            logger.info(f"Release gift skipped: the mech had energy at the first start of {version}")
            return service.get_state(), None
        # Under the lock: a donation that levels up in between would size
        # the gift from the level the mech no longer has.
        level = load_snapshot(service.mech_id).level
        state, gift = service.power_gift(f"release_{version}",
                                         gift_cents=three_days_of_energy(level))
        if version not in decisions:
            decisions[version] = "granted" if gift else "passed"
            try:
                atomic_write_json(DATA_DIR / RELEASES_CHECKED_FILE, {"versions": decisions})
            except (OSError, RuntimeError, TypeError) as e:
                logger.warning(f"Could not record the release gift decision for {version}: {e}")
        return state, gift
