# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Low-level donation processing helpers."""

from __future__ import annotations

from typing import Optional, Any

from utils.logging_utils import get_module_logger

logger = get_module_logger("donation.unified.processors")


def clear_mech_cache() -> None:
    """Clear the mech data store cache before emitting events."""

    try:
        from services.mech.mech_data_store import get_mech_data_store

        data_store = get_mech_data_store()
        data_store.clear_cache()
        logger.debug("MechDataStore cache cleared before event emission")
    except (ImportError, AttributeError, RuntimeError) as exc:  # pragma: no cover - defensive logging
        # Non-critical: Cache clear failures are logged but don't fail the operation
        logger.warning("Failed to clear MechDataStore cache: %s", exc)


def execute_sync_donation(mech_service, request) -> Any:
    """Execute a synchronous donation via the mech service."""

    return mech_service.add_donation(
        amount=float(request.amount),
        donor=request.donor_name,
        # The channel, not the guild. Both sit on the request - the factory in
        # unified/service.py fills them side by side - and the guild one was
        # passed here under the name channel_id, so it went into the ledger and
        # from there into the append-only DonationAdded payload. Nothing reads
        # that field today, which is why nothing broke and why it was worth
        # correcting now: the events are kept forever and replayed on every
        # rebuild. The guild is recorded separately by emit_donation_event
        # (review D10).
        channel_id=request.discord_channel_id,
        idempotency_key=request.idempotency_key,
    )


async def execute_async_donation(
    mech_service,
    request,
    *,
    guild: Optional[Any] = None,
    member_count: Optional[int] = None,
):
    """Execute an asynchronous donation via the mech service."""

    return await mech_service.add_donation_async(
        amount=float(request.amount),
        donor=request.donor_name,
        channel_id=request.discord_channel_id,   # see execute_sync_donation (review D10)
        guild=guild,
        member_count=member_count,
        idempotency_key=request.idempotency_key,
    )

