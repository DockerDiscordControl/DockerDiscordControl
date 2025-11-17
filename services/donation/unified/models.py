# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Data models used by the unified donation service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from services.mech.mech_service import MechState


@dataclass(frozen=True)
class DonationRequest:
    """Unified donation request for all donation entry points."""

    donor_name: str
    amount: float
    source: str

    discord_user_id: Optional[str] = None
    discord_guild_id: Optional[str] = None
    discord_channel_id: Optional[str] = None
    timestamp: Optional[str] = None

    bot_instance: Optional[Any] = None
    use_member_count: bool = False


@dataclass(frozen=True)
class DonationResult:
    """Result object returned by the unified donation service."""

    success: bool
    new_state: Optional["MechState"] = None
    old_level: Optional[int] = None
    new_level: Optional[int] = None
    old_power: Optional[float] = None
    new_power: Optional[float] = None
    level_changed: bool = False
    event_emitted: bool = False
    event_id: Optional[str] = None
    error_message: Optional[str] = None
    error_code: Optional[str] = None

    @classmethod
    def from_states(
        cls,
        *,
        success: bool,
        old_state: Optional["MechState"],
        new_state: Optional["MechState"],
        event_emitted: bool = False,
        event_id: Optional[str] = None,
        error_message: Optional[str] = None,
        error_code: Optional[str] = None,
    ) -> "DonationResult":
        """Factory helper that calculates deltas between mech states."""

        def _level(state: Optional["MechState"]) -> Optional[int]:
            return getattr(state, "level", None) if state is not None else None

        def _power(state: Optional["MechState"]) -> Optional[float]:
            value = getattr(state, "Power", None) if state is not None else None
            return float(value) if value is not None else None

        old_level = _level(old_state)
        new_level = _level(new_state)
        old_power = _power(old_state)
        new_power = _power(new_state)

        return cls(
            success=success,
            new_state=new_state,
            old_level=old_level,
            new_level=new_level,
            old_power=old_power,
            new_power=new_power,
            level_changed=(old_level != new_level) if None not in (old_level, new_level) else False,
            event_emitted=event_emitted,
            event_id=event_id,
            error_message=error_message,
            error_code=error_code,
        )

