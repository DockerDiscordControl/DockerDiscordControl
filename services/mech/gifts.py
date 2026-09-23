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

A gift is refused when the mech still has energy, and when the event log
already carries that campaign - so a restart gives nothing a second time.

Split out of progress_service.py (2026-09-23), which is on the size list and
may only shrink.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Optional, Tuple, TYPE_CHECKING

from services.mech.progress_service import (
    LOCK, Event, ProgressState, apply_decay_on_demand, apply_power_event,
    battery_capacity_cents, compute_ui_state, current_power_cents, decay_per_day, load_snapshot,
    next_seq, now_utc_iso, persist_snapshot, read_events, append_event,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from services.mech.progress_service import ProgressService

logger = logging.getLogger(__name__)


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

        # CHECK FOR DUPLICATE: Search event log for this campaign_id
        all_events = read_events()
        for evt in all_events:
            if evt.type == "PowerGiftGranted" and evt.mech_id == service.mech_id:
                existing_campaign = evt.payload.get("campaign_id")
                if existing_campaign == campaign_id:
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
