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
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.warning("Failed to clear MechDataStore cache: %s", exc)


def execute_sync_donation(mech_service, request) -> Any:
    """Execute a synchronous donation via the mech service."""

    return mech_service.add_donation(
        amount=float(request.amount),
        donor=request.donor_name,
        channel_id=request.discord_guild_id,
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
        channel_id=request.discord_guild_id,
        guild=guild,
        member_count=member_count,
    )

