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


@dataclass
class DonationDeletionRequest:
    """Request to delete a specific donation."""
    donation_index: int
    source: str = 'admin'


@dataclass
class DonationDeletionResult:
    """Result of donation deletion."""
    success: bool
    deleted_donation: Optional[Dict[str, Any]] = None
    new_state: Optional[MechState] = None
    error_message: Optional[str] = None


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

            # Emit unified event
            event_id = self._emit_donation_event(request, old_state, new_state)

            # CRITICAL: Clear MechDataStore cache after donation processing (Single Point of Truth)
            try:
                from services.mech.mech_data_store import get_mech_data_store
                data_store = get_mech_data_store()
                data_store.clear_cache()
                logger.debug("MechDataStore cache cleared after donation (Single Point of Truth)")
            except Exception as cache_error:
                logger.warning(f"Failed to clear MechDataStore cache: {cache_error}")

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

        Handles member count updates and other async operations while
        maintaining the same unified behavior and event emission.
        """
        try:
            # For Discord donations with bot integration
            if request.bot_instance and request.use_member_count:
                # Handle async member count update if needed
                try:
                    await self._update_member_count_if_needed(request.bot_instance)
                except Exception as member_error:
                    logger.warning(f"Member count update failed (continuing): {member_error}")

            # Use sync processing for the actual donation
            # This ensures consistent behavior between sync and async paths
            result = await asyncio.get_event_loop().run_in_executor(
                None, self.process_donation, request
            )

            return result

        except Exception as e:
            logger.error(f"Error in async donation processing: {e}")
            return DonationResult(
                success=False,
                error_message=str(e),
                error_code="ASYNC_PROCESSING_FAILED"
            )

    # ========================================================================
    # DONATION DELETION
    # ========================================================================

    def delete_donation(self, request: DonationDeletionRequest) -> DonationDeletionResult:
        """
        Delete a specific donation with proper event emission.

        Replaces the direct store manipulation in donation_management_service
        with a proper SERVICE FIRST approach.
        """
        try:
            # Get current donations
            from services.mech.mech_compatibility_service import get_mech_compatibility_service
            compat_service = get_mech_compatibility_service()

            store_data = compat_service.get_store_data()
            donations = store_data.get("donations", [])

            if request.donation_index < 0 or request.donation_index >= len(donations):
                return DonationDeletionResult(
                    success=False,
                    error_message=f"Invalid donation index: {request.donation_index}"
                )

            # Get old state
            old_state = self.mech_service.get_state()

            # Remove the donation
            deleted_donation = donations.pop(request.donation_index)
            store_data["donations"] = donations

            # Save updated data
            compat_service.save_store_data(store_data)

            # Get new state
            new_state = self.mech_service.get_state()

            # Emit deletion event
            self._emit_deletion_event(deleted_donation, old_state, new_state, request.source)

            # CRITICAL: Clear MechDataStore cache after donation deletion (Single Point of Truth)
            try:
                from services.mech.mech_data_store import get_mech_data_store
                data_store = get_mech_data_store()
                data_store.clear_cache()
                logger.debug("MechDataStore cache cleared after donation deletion (Single Point of Truth)")
            except Exception as cache_error:
                logger.warning(f"Failed to clear MechDataStore cache: {cache_error}")

            logger.info(f"Donation deleted: ${deleted_donation['amount']} from {deleted_donation['username']}")

            return DonationDeletionResult(
                success=True,
                deleted_donation=deleted_donation,
                new_state=new_state
            )

        except Exception as e:
            logger.error(f"Error deleting donation: {e}")
            return DonationDeletionResult(
                success=False,
                error_message=str(e)
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
        # Use the basic add_donation method directly
        # We handle events ourselves, so we don't need the SERVICE FIRST wrapper
        timestamp = request.timestamp or datetime.now().isoformat()

        return self.mech_service.add_donation(
            username=request.donor_name,
            amount=request.amount,
            ts_iso=timestamp
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

    def _emit_deletion_event(self, deleted_donation: Dict, old_state: MechState, new_state: MechState, source: str):
        """Emit donation deletion event."""
        event_data = {
            'action': 'deleted',
            'deleted_donation': deleted_donation,
            'source': source,
            'old_power': float(old_state.Power),
            'new_power': float(new_state.Power),
            'old_level': old_state.level,
            'new_level': new_state.level,
            'level_changed': old_state.level != new_state.level,
            'timestamp': datetime.now().isoformat()
        }

        self.event_manager.emit_event(
            event_type='donation_completed',
            source_service='unified_donations',
            data=event_data
        )

        logger.debug("Donation deletion event emitted")

    async def _update_member_count_if_needed(self, bot_instance):
        """DEPRECATED: No longer needed with SimpleEvolutionService (static costs)."""
        try:
            # No member count updates needed with static evolution costs
            logger.debug("Member count update skipped - using static evolution costs")

        except Exception as e:
            logger.error(f"Error updating member count: {e}")


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

        # Reset donations via compatibility service
        from services.mech.mech_compatibility_service import get_mech_compatibility_service
        compat_service = get_mech_compatibility_service()

        if not compat_service.save_store_data({"donations": []}):
            return DonationResult(
                success=False,
                error_message="Failed to reset store data",
                error_code="RESET_FAILED"
            )

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

        service.event_manager.emit_event(
            event_type='donation_completed',
            source_service='unified_donations',
            data=event_data
        )

        # CRITICAL: Clear MechDataStore cache after donation reset (Single Point of Truth)
        try:
            from services.mech.mech_data_store import get_mech_data_store
            data_store = get_mech_data_store()
            data_store.clear_cache()
            logger.debug("MechDataStore cache cleared after donation reset (Single Point of Truth)")
        except Exception as cache_error:
            logger.warning(f"Failed to clear MechDataStore cache: {cache_error}")

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