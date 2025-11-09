#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Mech Service Adapter                          #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""
Mech Service Adapter - Bridges old mech_service API to new progress_service

This adapter maintains backward compatibility with existing code while using
the new event-sourced progress service internally.
"""

import logging
from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

from .progress_service import get_progress_service, ProgressState
from .mech_levels import get_level_name

if TYPE_CHECKING:
    import discord

logger = logging.getLogger('ddc.mech_service_adapter')


@dataclass
class MechState:
    """Legacy MechState for backward compatibility"""
    evolution_level: int
    power_level: float
    is_offline: bool
    total_donations: float
    next_evolution_at: float
    evolution_progress: float
    animation_type: str
    speed_level: float
    difficulty_tier: str
    difficulty_bin: int
    member_count: int

    # Backward compatibility properties for old code
    @property
    def level(self) -> int:
        """Alias for evolution_level (backward compatibility)"""
        return self.evolution_level

    @property
    def Power(self) -> float:
        """Alias for power_level (backward compatibility)"""
        return self.power_level

    @property
    def total_donated(self) -> float:
        """Alias for total_donations (backward compatibility)"""
        return self.total_donations

    @property
    def level_name(self) -> str:
        """Get level name (backward compatibility)"""
        from .mech_levels import get_level_name
        return get_level_name(self.evolution_level)


@dataclass
class GetMechStateRequest:
    """Legacy request object"""
    include_decimals: bool = False


@dataclass
class MechStateServiceResult:
    """Legacy service result for Web UI compatibility"""
    success: bool
    level: int
    power: float
    total_donated: float
    name: str
    threshold: float
    speed: float
    error: Optional[str] = None


class MechServiceAdapter:
    """
    Adapter that implements the old mech_service interface
    while using the new progress_service internally.
    """

    def __init__(self, mech_id: str = "main"):
        self.mech_id = mech_id
        self.progress_service = get_progress_service(mech_id)
        logger.info(f"Mech Service Adapter initialized for mech_id={mech_id}")

    def _convert_state(self, prog_state: ProgressState) -> MechState:
        """Convert ProgressState to legacy MechState"""
        # Calculate speed level from power (0-100 scale)
        # At max power, speed = 100; at 0 power, speed = 0
        if prog_state.power_max > 0:
            speed_level = min(100, (prog_state.power_current / prog_state.power_max) * 100)
        else:
            speed_level = 0

        # Animation type based on offline status
        animation_type = "rest" if prog_state.is_offline else "walk"

        return MechState(
            evolution_level=prog_state.level,
            power_level=prog_state.power_current,
            is_offline=prog_state.is_offline,
            total_donations=prog_state.total_donated,
            next_evolution_at=prog_state.evo_max,
            evolution_progress=prog_state.evo_percent,
            animation_type=animation_type,
            speed_level=speed_level,
            difficulty_tier=prog_state.difficulty_tier,
            difficulty_bin=prog_state.difficulty_bin,
            member_count=prog_state.member_count
        )

    def get_state(self, request: Optional[GetMechStateRequest] = None) -> MechState:
        """Get current mech state (backward compatible)"""
        prog_state = self.progress_service.get_state()
        return self._convert_state(prog_state)

    def get_power_with_decimals(self) -> float:
        """Get raw power value with decimal places (backward compatibility)"""
        prog_state = self.progress_service.get_state()
        return prog_state.power_current

    def add_donation(self, amount: float, donor: Optional[str] = None,
                    channel_id: Optional[str] = None) -> MechState:
        """Add donation and return updated state"""
        prog_state = self.progress_service.add_donation(amount, donor, channel_id)
        logger.info(f"Donation added via adapter: ${amount:.2f} from {donor}")
        return self._convert_state(prog_state)

    def update_member_count(self, member_count: int) -> None:
        """Update member count for difficulty calculation"""
        self.progress_service.update_member_count(member_count)
        logger.info(f"Member count updated via adapter: {member_count}")

    def tick_decay(self) -> MechState:
        """Trigger decay check"""
        prog_state = self.progress_service.tick_decay()
        return self._convert_state(prog_state)

    def monthly_gift(self, campaign_id: str) -> MechState:
        """Grant monthly gift"""
        prog_state, gift = self.progress_service.monthly_gift(campaign_id)
        if gift:
            logger.info(f"Monthly gift granted via adapter: ${gift:.2f}")
        return self._convert_state(prog_state)

    def get_mech_state_service(self, request: GetMechStateRequest) -> MechStateServiceResult:
        """Get mech state in service result format (for Web UI)"""
        try:
            prog_state = self.progress_service.get_state()
            level_name = get_level_name(prog_state.level)

            return MechStateServiceResult(
                success=True,
                level=prog_state.level,
                power=prog_state.power_current,
                total_donated=prog_state.total_donated,
                name=level_name,
                threshold=prog_state.evo_max,
                speed=min(100, (prog_state.power_current / prog_state.power_max) * 100) if prog_state.power_max > 0 else 0,
                error=None
            )
        except Exception as e:
            logger.error(f"Error getting mech state service: {e}", exc_info=True)
            return MechStateServiceResult(
                success=False,
                level=1,
                power=0.0,
                total_donated=0.0,
                name="Error",
                threshold=0.0,
                speed=0.0,
                error=str(e)
            )

    def _get_evolution_mode(self) -> dict:
        """Get evolution mode info (for backward compatibility)"""
        # New progress service always uses dynamic evolution
        prog_state = self.progress_service.get_state()
        return {
            'use_dynamic': True,
            'difficulty_multiplier': 1.0,  # Multiplier is baked into requirements
            'current_bin': prog_state.difficulty_bin,
            'difficulty_tier': prog_state.difficulty_tier
        }

    async def add_donation_async(self, amount: float, donor: Optional[str] = None,
                                channel_id: Optional[str] = None,
                                guild: Optional['discord.Guild'] = None,
                                member_count: Optional[int] = None) -> MechState:
        """
        Add donation with member count freeze at level-up (Option B).

        The member_count is FROZEN at level-up time and used for the NEXT level's goal.
        This ensures difficulty stays constant during a level progression.
        """
        # Get current state to check if level-up will happen
        current_state = self.progress_service.get_state()

        # Calculate if this donation will trigger level-up
        amount_cents = int(amount * 100)
        will_level_up = (current_state.level < 11 and
                        (current_state.evo_current * 100 + amount_cents) >= current_state.evo_max * 100)

        # OPTION B: Freeze member count ONLY at level-up time
        if will_level_up:
            if member_count is not None:
                # Use the provided channel-specific member count
                logger.info(f"🔒 FREEZING member count at level-up: {member_count} members (channel-specific, bots excluded)")
                self.progress_service.update_member_count(member_count)
            elif guild is not None:
                # Fallback to guild member count if channel count not available
                guild_member_count = guild.member_count
                logger.info(f"🔒 FREEZING member count at level-up: {guild_member_count} members (guild-wide, bots included)")
                self.progress_service.update_member_count(guild_member_count)
            else:
                logger.warning("Level-up without member count - difficulty may be incorrect")

        # Now add the donation
        prog_state = self.progress_service.add_donation(amount, donor, channel_id)
        return self._convert_state(prog_state)


# Global instance
_mech_service_adapter: Optional[MechServiceAdapter] = None


def get_mech_service(mech_id: str = "main") -> MechServiceAdapter:
    """Get the global mech service adapter instance"""
    global _mech_service_adapter
    if _mech_service_adapter is None:
        _mech_service_adapter = MechServiceAdapter(mech_id)
    return _mech_service_adapter
