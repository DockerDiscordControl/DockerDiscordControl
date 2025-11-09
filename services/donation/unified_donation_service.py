# -*- coding: utf-8 -*-
"""
Unified Donation Service - Centralized donation processing for ALL use cases

This service replaces the chaotic multiple donation processing paths with a single,
unified approach that guarantees event emission and consistent behavior across:
- Web UI donations
- Discord bot donations
- Test/admin donations
- Donation deletions

SERVICE FIRST: All methods use Request/Result patterns with automatic event emission.
"""

import logging
import asyncio
from dataclasses import dataclass
from typing import Optional, Union, Dict, Any
from datetime import datetime

from services.mech.mech_service import get_mech_service, MechState
from services.infrastructure.event_manager import get_event_manager
from utils.logging_utils import get_module_logger

logger = get_module_logger('unified_donation_service')

# ============================================================================
# SERVICE FIRST REQUEST/RESULT PATTERNS
# ============================================================================

@dataclass
class DonationRequest:
    """Unified donation request for all donation types."""
    donor_name: str
    amount: int  # Dollars as integer
    source: str  # 'web_ui', 'discord', 'test', etc.

    # Optional fields
    discord_user_id: Optional[str] = None
    discord_guild_id: Optional[str] = None
    discord_channel_id: Optional[str] = None
    timestamp: Optional[str] = None

    # Bot integration (for Discord)
    bot_instance: Optional[Any] = None
    use_member_count: bool = False


@dataclass
class DonationResult:
    """Unified donation result with complete state information."""
    success: bool
    new_state: Optional[MechState] = None

    # State change information
    old_level: Optional[int] = None
    new_level: Optional[int] = None
    old_power: Optional[float] = None
    new_power: Optional[float] = None
    level_changed: bool = False

    # Event information
    event_emitted: bool = False
    event_id: Optional[str] = None

    # Error information
    error_message: Optional[str] = None
    error_code: Optional[str] = None


# Donation deletion classes removed - incompatible with Event Sourcing

# ============================================================================
# UNIFIED DONATION SERVICE
# ============================================================================

class UnifiedDonationService:
    """
    Centralized service for ALL donation processing.

    Replaces the chaotic multiple donation paths with a single, consistent
    approach that guarantees event emission and proper state management.
    """

    def __init__(self):
        self.mech_service = get_mech_service()
        self.event_manager = get_event_manager()

        logger.info("Unified Donation Service initialized")
        logger.info("Centralized donation processing for Web UI, Discord, Tests, and Admin")

    # ========================================================================
    # SYNC DONATION PROCESSING
    # ========================================================================

    def process_donation(self, request: DonationRequest) -> DonationResult:
        """
        Process a donation synchronously with guaranteed event emission.

        This is the main entry point for all donation processing.
        Supports all donation types: Web UI, Discord, Tests, Admin.
        """
        try:
            # Validate request
            validation_result = self._validate_donation_request(request)
            if not validation_result.success:
                return DonationResult(
                    success=False,
                    error_message=validation_result.error_message,
                    error_code="VALIDATION_FAILED"
                )

            # Get old state for comparison
            old_state = self.mech_service.get_state()
            old_level = old_state.level
            old_power = float(old_state.Power)

            logger.info(f"Processing {request.source} donation: ${request.amount} from {request.donor_name}")

            # Process the donation via MechService
            new_state = self._execute_donation(request)

            # Calculate state changes
            new_level = new_state.level
            new_power = float(new_state.Power)
            level_changed = old_level != new_level

            # CRITICAL: Clear MechDataStore cache BEFORE event emission (prevent race condition)
            try:
                from services.mech.mech_data_store import get_mech_data_store
                data_store = get_mech_data_store()
                data_store.clear_cache()
                logger.debug("MechDataStore cache cleared before event emission (prevents race condition)")
            except Exception as cache_error:
                logger.warning(f"Failed to clear MechDataStore cache: {cache_error}")

            # Emit unified event (animation service will now get fresh data)
            event_id = self._emit_donation_event(request, old_state, new_state)

            logger.info(f"Donation processed successfully: {old_level}→{new_level}, {old_power:.2f}→{new_power:.2f}")

            return DonationResult(
                success=True,
                new_state=new_state,
                old_level=old_level,
                new_level=new_level,
                old_power=old_power,
                new_power=new_power,
                level_changed=level_changed,
                event_emitted=True,
                event_id=event_id
            )

        except Exception as e:
            logger.error(f"Error processing donation: {e}")
            return DonationResult(
                success=False,
                error_message=str(e),
                error_code="PROCESSING_FAILED"
            )

    # ========================================================================
    # ASYNC DONATION PROCESSING (for Discord)
    # ========================================================================

    async def process_donation_async(self, request: DonationRequest) -> DonationResult:
        """
        Process a donation asynchronously for Discord bot integration.

        Handles member count updates via add_donation_async which fetches
        the member count before level-up to freeze difficulty.
        """
        try:
            # Validate request
            validation_result = self._validate_donation_request(request)
            if not validation_result.success:
                return DonationResult(
                    success=False,
                    error_message=validation_result.error_message,
                    error_code="VALIDATION_FAILED"
                )

            # Get old state for comparison
            old_state = self.mech_service.get_state()
            old_level = old_state.level
            old_power = float(old_state.Power)

            logger.info(f"Processing {request.source} donation (async): ${request.amount} from {request.donor_name}")

            # Process the donation with async method (handles member count)
            new_state = await self._execute_donation_async(request)

            # Calculate state changes
            new_level = new_state.level
            new_power = float(new_state.Power)
            level_changed = old_level != new_level

            # CRITICAL: Clear MechDataStore cache BEFORE event emission (prevent race condition)
            try:
                from services.mech.mech_data_store import get_mech_data_store
                data_store = get_mech_data_store()
                data_store.clear_cache()
                logger.debug("MechDataStore cache cleared before event emission (prevents race condition)")
            except Exception as cache_error:
                logger.warning(f"Failed to clear MechDataStore cache: {cache_error}")

            # Emit unified event (animation service will now get fresh data)
            event_id = self._emit_donation_event(request, old_state, new_state)

            logger.info(f"Donation processed successfully (async): {old_level}→{new_level}, {old_power:.2f}→{new_power:.2f}")

            return DonationResult(
                success=True,
                new_state=new_state,
                old_level=old_level,
                new_level=new_level,
                old_power=old_power,
                new_power=new_power,
                level_changed=level_changed,
                event_emitted=True,
                event_id=event_id
            )

        except Exception as e:
            logger.error(f"Error in async donation processing: {e}", exc_info=True)
            return DonationResult(
                success=False,
                error_message=str(e),
                error_code="ASYNC_PROCESSING_FAILED"
            )

    # ========================================================================
    # INTERNAL HELPER METHODS
    # ========================================================================

    def _validate_donation_request(self, request: DonationRequest) -> DonationResult:
        """Validate donation request parameters."""
        if not request.donor_name or len(request.donor_name) > 100:
            return DonationResult(
                success=False,
                error_message="Donor name must be between 1 and 100 characters"
            )

        if not isinstance(request.amount, int) or request.amount <= 0:
            return DonationResult(
                success=False,
                error_message="Amount must be a positive integer"
            )

        if request.amount > 1000000:
            return DonationResult(
                success=False,
                error_message="Amount exceeds maximum allowed value (1,000,000)"
            )

        return DonationResult(success=True)

    def _execute_donation(self, request: DonationRequest) -> MechState:
        """Execute the actual donation via MechService."""
        # Use the adapter's add_donation method with correct parameter names
        return self.mech_service.add_donation(
            amount=float(request.amount),
            donor=request.donor_name,
            channel_id=request.discord_guild_id
        )

    async def _execute_donation_async(self, request: DonationRequest) -> MechState:
        """Execute donation asynchronously with channel member count fetch."""
        # Use the async version with guild parameter for member count fetch
        guild = None
        channel = None

        if request.bot_instance and request.use_member_count:
            try:
                # Get the specific guild and channel by ID
                if request.discord_guild_id:
                    guild_id = int(request.discord_guild_id)
                    guild = request.bot_instance.get_guild(guild_id)

                    if guild and request.discord_channel_id:
                        channel_id = int(request.discord_channel_id)
                        channel = guild.get_channel(channel_id)

                        if channel:
                            logger.info(f"Using channel for member count: #{channel.name} in {guild.name}")
                            # Update member count for dynamic difficulty calculation (channel-specific!)
                            await self._update_member_count_if_needed(request.bot_instance, channel)
                        else:
                            logger.warning(f"Could not find channel with ID {channel_id} in guild {guild.name}")
                    elif guild:
                        logger.warning(f"No channel_id provided, falling back to guild member count")
                        # Fallback to guild member count if no channel specified
                        await self._update_member_count_if_needed(request.bot_instance, None)
                    else:
                        logger.warning(f"Could not find guild with ID {guild_id}")
            except Exception as e:
                logger.warning(f"Could not get guild/channel from bot: {e}")

        return await self.mech_service.add_donation_async(
            amount=float(request.amount),
            donor=request.donor_name,
            channel_id=request.discord_guild_id,
            guild=guild
        )

    def _emit_donation_event(self, request: DonationRequest, old_state: MechState, new_state: MechState) -> str:
        """Emit unified donation completed event."""
        old_power = float(old_state.Power)
        new_power = float(new_state.Power)

        event_data = {
            'amount': request.amount,
            'username': request.donor_name,
            'source': request.source,
            'old_power': old_power,
            'new_power': new_power,
            'old_level': old_state.level,
            'new_level': new_state.level,
            'level_changed': old_state.level != new_state.level,
            'timestamp': datetime.now().isoformat()
        }

        # Add Discord-specific data if available
        if request.discord_user_id:
            event_data['discord_user_id'] = request.discord_user_id
        if request.discord_guild_id:
            event_data['discord_guild_id'] = request.discord_guild_id

        # Emit event with unified source
        event_id = f"donation_{datetime.now().timestamp()}"
        self.event_manager.emit_event(
            event_type='donation_completed',
            source_service='unified_donations',  # Single unified source!
            data=event_data
        )

        logger.debug(f"Donation event emitted: {event_id}")
        return event_id

    # _emit_deletion_event removed - donation deletion not supported in Event Sourcing

    async def _update_member_count_if_needed(self, bot_instance, channel=None):
        """
        Update member count for dynamic difficulty calculation.

        This is called during donation processing to ensure the mech evolution
        costs reflect the current Discord community size (dynamic difficulty).

        Args:
            bot_instance: The Discord bot instance
            channel: Optional Discord channel object - if provided, counts only members who can see this channel
                    (requires Members Intent). If None, falls back to guild member count.
        """
        try:
            if bot_instance is None:
                logger.debug("Bot instance not provided, skipping member count update")
                return

            member_count = 1  # Default fallback

            if channel is not None:
                # CHANNEL-SPECIFIC COUNT: Only members who can see this channel
                # This requires Members Intent to be enabled!
                try:
                    # Count members who can see this channel
                    # channel.members returns members who have permissions to see the channel
                    visible_members = [m for m in channel.members if not m.bot]  # Exclude bots
                    member_count = len(visible_members)
                    logger.info(f"Channel-specific member count for #{channel.name}: {member_count} members (bots excluded)")
                except AttributeError:
                    # Fallback if channel.members not available
                    logger.warning(f"channel.members not available (Members Intent required), falling back to guild count")
                    guild = channel.guild if hasattr(channel, 'guild') else None
                    if guild:
                        member_count = guild.member_count if guild.member_count else 1
            else:
                # GUILD-WIDE COUNT: All server members (fallback)
                guild = None
                if hasattr(bot_instance, 'guild'):
                    guild = bot_instance.guild
                elif hasattr(bot_instance, 'guilds') and bot_instance.guilds:
                    guild = bot_instance.guilds[0]  # Use first guild

                if guild is None:
                    logger.warning("No guild found, cannot update member count")
                    return

                member_count = guild.member_count if guild.member_count else 1
                logger.info(f"Guild-wide member count: {member_count} members (total including bots)")

            # Update progress service with current member count
            from services.mech.progress_service import get_progress_service
            progress_service = get_progress_service()
            progress_service.update_member_count(member_count)

            logger.debug(f"Member count updated successfully: {member_count}")

        except Exception as e:
            logger.error(f"Error updating member count: {e}", exc_info=True)


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_unified_donation_service: Optional[UnifiedDonationService] = None

def get_unified_donation_service() -> UnifiedDonationService:
    """Get the singleton unified donation service instance."""
    global _unified_donation_service
    if _unified_donation_service is None:
        _unified_donation_service = UnifiedDonationService()
    return _unified_donation_service


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

def process_web_ui_donation(donor_name: str, amount: int) -> DonationResult:
    """Convenience function for Web UI donations."""
    service = get_unified_donation_service()
    request = DonationRequest(
        donor_name=f"WebUI:{donor_name}",
        amount=amount,
        source='web_ui'
    )
    return service.process_donation(request)


async def process_discord_donation(
    discord_username: str,
    amount: int,
    user_id: str = None,
    guild_id: str = None,
    channel_id: str = None,
    bot_instance = None
) -> DonationResult:
    """Convenience function for Discord donations."""
    service = get_unified_donation_service()
    request = DonationRequest(
        donor_name=f"Discord:{discord_username}",
        amount=amount,
        source='discord',
        discord_user_id=user_id,
        discord_guild_id=guild_id,
        discord_channel_id=channel_id,
        bot_instance=bot_instance,
        use_member_count=True
    )
    return await service.process_donation_async(request)


def process_test_donation(donor_name: str, amount: int) -> DonationResult:
    """Convenience function for test/admin donations."""
    service = get_unified_donation_service()
    request = DonationRequest(
        donor_name=f"Test:{donor_name}",
        amount=amount,
        source='test'
    )
    return service.process_donation(request)


def reset_all_donations(source: str = 'admin') -> DonationResult:
    """Reset all donations with proper event emission."""
    service = get_unified_donation_service()
    try:
        # Get old state
        old_state = service.mech_service.get_state()
        old_power = float(old_state.Power)
        old_level = old_state.level

        # Reset Progress Service directly
        from pathlib import Path
        import json

        # Clear event log
        event_log = Path("config/progress/events.jsonl")
        if event_log.exists():
            event_log.write_text("")

        # Reset sequence counter
        seq_file = Path("config/progress/last_seq.txt")
        seq_file.write_text("0")

        # Reset snapshot to Level 1
        snapshot_file = Path("config/progress/snapshots/main.json")
        fresh_snapshot = {
            'mech_id': 'main',
            'level': 1,
            'evo_acc': 0,
            'power_acc': 0,
            'goal_requirement': 400,
            'difficulty_bin': 1,
            'goal_started_at': datetime.now().isoformat(),
            'last_decay_day': datetime.now().date().isoformat(),
            'power_decay_per_day': 100,
            'version': 0,
            'last_event_seq': 0,
            'mech_type': 'default',
            'last_user_count_sample': 0,
            'cumulative_donations_cents': 0
        }
        with open(snapshot_file, 'w', encoding='utf-8') as f:
            json.dump(fresh_snapshot, f, indent=2)

        # Get new state
        new_state = service.mech_service.get_state()
        new_power = float(new_state.Power)
        new_level = new_state.level

        # Emit reset event
        event_data = {
            'action': 'reset',
            'source': source,
            'old_power': old_power,
            'new_power': new_power,
            'old_level': old_level,
            'new_level': new_level,
            'level_changed': old_level != new_level,
            'timestamp': datetime.now().isoformat()
        }

        # CRITICAL: Clear MechDataStore cache BEFORE event emission (prevent race condition)
        try:
            from services.mech.mech_data_store import get_mech_data_store
            data_store = get_mech_data_store()
            data_store.clear_cache()
            logger.debug("MechDataStore cache cleared before reset event emission (prevents race condition)")
        except Exception as cache_error:
            logger.warning(f"Failed to clear MechDataStore cache: {cache_error}")

        # Emit reset event (animation service will now get fresh data)
        service.event_manager.emit_event(
            event_type='donation_completed',
            source_service='unified_donations',
            data=event_data
        )

        logger.info(f"All donations reset: {old_level}→{new_level}, {old_power:.2f}→{new_power:.2f}")

        return DonationResult(
            success=True,
            new_state=new_state,
            old_level=old_level,
            new_level=new_level,
            old_power=old_power,
            new_power=new_power,
            level_changed=old_level != new_level,
            event_emitted=True
        )

    except Exception as e:
        logger.error(f"Error resetting donations: {e}")
        return DonationResult(
            success=False,
            error_message=str(e),
            error_code="RESET_ERROR"
        )