"""High level UnifiedDonationService implementation."""

from __future__ import annotations

from typing import Optional

from services.donation.unified import events
from services.donation.unified.member_count import resolve_member_context
from services.donation.unified.models import DonationRequest, DonationResult
from services.donation.unified.processors import (
    clear_mech_cache,
    execute_async_donation,
    execute_sync_donation,
)
from services.donation.unified.reset import reset_donations
from services.donation.unified.validation import DonationValidationError, validate_request
from services.infrastructure.event_manager import get_event_manager
from services.mech.mech_service import get_mech_service
from utils.logging_utils import get_module_logger


logger = get_module_logger("unified_donation_service")


class UnifiedDonationService:
    """Centralized service for donation processing."""

    def __init__(self):
        self.mech_service = get_mech_service()
        self.event_manager = get_event_manager()

        logger.info("Unified Donation Service initialized")
        logger.info("Centralized donation processing for Web UI, Discord, Tests, and Admin")

    def process_donation(self, request: DonationRequest) -> DonationResult:
        """Process a donation synchronously."""

        try:
            validate_request(request)
        except DonationValidationError as exc:
            return DonationResult.from_states(
                success=False,
                old_state=None,
                new_state=None,
                error_message=str(exc),
                error_code="VALIDATION_FAILED",
            )

        try:
            old_state = self.mech_service.get_state()
            new_state = execute_sync_donation(self.mech_service, request)

            clear_mech_cache()
            event_id = events.emit_donation_event(
                self.event_manager, request, old_state=old_state, new_state=new_state
            )

            return DonationResult.from_states(
                success=True,
                old_state=old_state,
                new_state=new_state,
                event_emitted=True,
                event_id=event_id,
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Error processing donation: %s", exc, exc_info=True)
            return DonationResult.from_states(
                success=False,
                old_state=None,
                new_state=None,
                error_message=str(exc),
                error_code="PROCESSING_FAILED",
            )

    async def process_donation_async(self, request: DonationRequest) -> DonationResult:
        """Process a donation asynchronously (Discord entry point)."""

        try:
            validate_request(request)
        except DonationValidationError as exc:
            return DonationResult.from_states(
                success=False,
                old_state=None,
                new_state=None,
                error_message=str(exc),
                error_code="VALIDATION_FAILED",
            )

        try:
            old_state = self.mech_service.get_state()
            guild, member_count = await resolve_member_context(
                request.bot_instance,
                request.discord_guild_id,
                use_member_count=request.use_member_count,
            )

            new_state = await execute_async_donation(
                self.mech_service,
                request,
                guild=guild,
                member_count=member_count,
            )

            clear_mech_cache()
            event_id = events.emit_donation_event(
                self.event_manager, request, old_state=old_state, new_state=new_state
            )

            return DonationResult.from_states(
                success=True,
                old_state=old_state,
                new_state=new_state,
                event_emitted=True,
                event_id=event_id,
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Error in async donation processing: %s", exc, exc_info=True)
            return DonationResult.from_states(
                success=False,
                old_state=None,
                new_state=None,
                error_message=str(exc),
                error_code="ASYNC_PROCESSING_FAILED",
            )

    def reset_all_donations(self, *, source: str = "admin") -> DonationResult:
        """Reset all donations via the unified donation flow."""

        return reset_donations(self.mech_service, self.event_manager, source=source)


_unified_donation_service: Optional[UnifiedDonationService] = None


def get_unified_donation_service() -> UnifiedDonationService:
    global _unified_donation_service
    if _unified_donation_service is None:
        _unified_donation_service = UnifiedDonationService()
    return _unified_donation_service


def process_web_ui_donation(donor_name: str, amount: float) -> DonationResult:
    service = get_unified_donation_service()
    request = DonationRequest(
        donor_name=f"WebUI:{donor_name}",
        amount=amount,
        source="web_ui",
    )
    return service.process_donation(request)


async def process_discord_donation(
    discord_username: str,
    amount: float,
    user_id: Optional[str] = None,
    guild_id: Optional[str] = None,
    channel_id: Optional[str] = None,
    bot_instance=None,
) -> DonationResult:
    service = get_unified_donation_service()
    request = DonationRequest(
        donor_name=f"Discord:{discord_username}",
        amount=amount,
        source="discord",
        discord_user_id=user_id,
        discord_guild_id=guild_id,
        discord_channel_id=channel_id,
        bot_instance=bot_instance,
        use_member_count=True,
    )
    return await service.process_donation_async(request)


def process_test_donation(donor_name: str, amount: float) -> DonationResult:
    service = get_unified_donation_service()
    request = DonationRequest(
        donor_name=f"Test:{donor_name}",
        amount=amount,
        source="test",
    )
    return service.process_donation(request)


def reset_all_donations(source: str = "admin") -> DonationResult:
    service = get_unified_donation_service()
    return service.reset_all_donations(source=source)

