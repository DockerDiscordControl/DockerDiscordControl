"""Event emission helpers for the unified donation service."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from utils.logging_utils import get_module_logger

logger = get_module_logger("donation.unified.events")


def build_donation_event(
    request,
    *,
    old_state,
    new_state,
) -> Dict[str, Any]:
    """Build a donation event payload."""

    old_power = float(getattr(old_state, "Power", 0.0))
    new_power = float(getattr(new_state, "Power", 0.0))

    event_data: Dict[str, Any] = {
        "amount": request.amount,
        "username": request.donor_name,
        "source": request.source,
        "old_power": old_power,
        "new_power": new_power,
        "old_level": getattr(old_state, "level", None),
        "new_level": getattr(new_state, "level", None),
        "level_changed": getattr(old_state, "level", None) != getattr(new_state, "level", None),
        "timestamp": datetime.now().isoformat(),
    }

    if request.discord_user_id:
        event_data["discord_user_id"] = request.discord_user_id
    if request.discord_guild_id:
        event_data["discord_guild_id"] = request.discord_guild_id

    return event_data


def emit_donation_event(event_manager, request, *, old_state, new_state) -> str:
    """Emit the donation completed event via the event manager."""

    event_id = f"donation_{datetime.now().timestamp()}"
    event_data = build_donation_event(request, old_state=old_state, new_state=new_state)

    event_manager.emit_event(
        event_type="donation_completed",
        source_service="unified_donations",
        data=event_data,
    )

    logger.debug("Donation event emitted: %s", event_id)
    return event_id


def emit_reset_event(event_manager, *, source: str, old_state, new_state) -> None:
    """Emit a donation reset event."""

    event_data: Dict[str, Any] = {
        "action": "reset",
        "source": source,
        "old_power": float(getattr(old_state, "Power", 0.0)),
        "new_power": float(getattr(new_state, "Power", 0.0)),
        "old_level": getattr(old_state, "level", None),
        "new_level": getattr(new_state, "level", None),
        "level_changed": getattr(old_state, "level", None) != getattr(new_state, "level", None),
        "timestamp": datetime.now().isoformat(),
    }

    event_manager.emit_event(
        event_type="donation_completed",
        source_service="unified_donations",
        data=event_data,
    )

