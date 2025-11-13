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
from utils.observability import metrics, tracing, get_structured_logger
import time

# Import specific exceptions for better error handling
from services.exceptions import MechServiceError, DonationServiceError


logger = get_module_logger("unified_donation_service")
# Structured logger for enhanced observability
structured_logger = get_structured_logger(__name__, service_name="UnifiedDonationService")


class UnifiedDonationService:
    """Centralized service for donation processing."""

    def __init__(self):
        self.mech_service = get_mech_service()
        self.event_manager = get_event_manager()

        logger.info("Unified Donation Service initialized")
        logger.info("Centralized donation processing for Web UI, Discord, Tests, and Admin")

    def process_donation(self, request: DonationRequest) -> DonationResult:
        """Process a donation synchronously."""
        start_time = time.time()

        # Metrics: Track donation attempt
        metrics.increment("donations.attempts.total", tags={"source": request.source})

        # Tracing: Create span for donation processing
        with tracing.trace("donation.process", attributes={
            "source": request.source,
            "donor": request.donor_name,
        }) as span:
            try:
                validate_request(request)
            except DonationValidationError as exc:
                # Metrics: Track validation failure
                metrics.increment("donations.validation_failed.total")

                # Structured logging: Log validation failure with context
                structured_logger.warning("donation_validation_failed", extra={
                    "donor": request.donor_name,
                    "amount": request.amount,
                    "source": request.source,
                    "error": str(exc),
                    "duration_ms": (time.time() - start_time) * 1000,
                })

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

                # Calculate processing duration
                duration_ms = (time.time() - start_time) * 1000

                # Metrics: Track successful donation
                metrics.increment("donations.total", tags={"source": request.source})
                metrics.histogram("donation.amount", request.amount)
                metrics.histogram("donation.processing_time.duration_ms", duration_ms)

                # Structured logging: Log successful donation with full context
                structured_logger.info("donation_processed", extra={
                    "donor": request.donor_name,
                    "amount": request.amount,
                    "source": request.source,
                    "old_power": old_state.current_power if old_state else None,
                    "new_power": new_state.current_power if new_state else None,
                    "power_gained": (new_state.current_power - old_state.current_power) if (old_state and new_state) else None,
                    "event_id": event_id,
                    "duration_ms": duration_ms,
                })

                # Tracing: Add success attributes to span
                if span:
                    span.set_attribute("success", True)
                    span.set_attribute("amount", request.amount)
                    span.set_attribute("duration_ms", duration_ms)

                return DonationResult.from_states(
                    success=True,
                    old_state=old_state,
                    new_state=new_state,
                    event_emitted=True,
                    event_id=event_id,
                )
            except MechServiceError as exc:
                # Mech service errors (state save/load, power calculations)
                duration_ms = (time.time() - start_time) * 1000
                metrics.increment("donations.mech_error.total")

                logger.error("Mech service error during donation: %s", exc, exc_info=True)
                structured_logger.error("donation_mech_error", extra={
                    "donor": request.donor_name,
                    "amount": request.amount,
                    "source": request.source,
                    "error": str(exc),
                    "error_code": getattr(exc, 'error_code', 'MECH_ERROR'),
                    "duration_ms": duration_ms,
                })

                if span:
                    span.set_attribute("success", False)
                    span.set_attribute("error_type", "MechServiceError")
                    span.set_attribute("error", str(exc))

                return DonationResult.from_states(
                    success=False,
                    old_state=None,
                    new_state=None,
                    error_message=f"Mech service error: {exc}",
                    error_code="MECH_SERVICE_ERROR",
                )
            except (ValueError, TypeError, AttributeError, KeyError) as exc:
                # Data format/structure errors
                duration_ms = (time.time() - start_time) * 1000
                metrics.increment("donations.data_error.total")

                logger.error("Data error during donation: %s", exc, exc_info=True)
                structured_logger.error("donation_data_error", extra={
                    "donor": request.donor_name,
                    "amount": request.amount,
                    "source": request.source,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                    "duration_ms": duration_ms,
                })

                if span:
                    span.set_attribute("success", False)
                    span.set_attribute("error_type", type(exc).__name__)
                    span.set_attribute("error", str(exc))

                return DonationResult.from_states(
                    success=False,
                    old_state=None,
                    new_state=None,
                    error_message=f"Data processing error: {exc}",
                    error_code="DATA_ERROR",
                )
            except (RuntimeError, OSError) as exc:  # pragma: no cover - defensive logging
                # System/runtime errors (file I/O, event emission)
                duration_ms = (time.time() - start_time) * 1000
                metrics.increment("donations.system_error.total")

                logger.error("System error during donation: %s", exc, exc_info=True)
                structured_logger.error("donation_system_error", extra={
                    "donor": request.donor_name,
                    "amount": request.amount,
                    "source": request.source,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                    "duration_ms": duration_ms,
                })

                if span:
                    span.set_attribute("success", False)
                    span.set_attribute("error_type", type(exc).__name__)
                    span.set_attribute("error", str(exc))

                return DonationResult.from_states(
                    success=False,
                    old_state=None,
                    new_state=None,
                    error_message=str(exc),
                    error_code="PROCESSING_FAILED",
                )

    async def process_donation_async(self, request: DonationRequest) -> DonationResult:
        """Process a donation asynchronously (Discord entry point)."""
        start_time = time.time()

        # Metrics: Track async donation attempt
        metrics.increment("donations.async.attempts.total", tags={"source": request.source})

        # Tracing: Create span for async donation processing
        with tracing.trace("donation.process_async", attributes={
            "source": request.source,
            "donor": request.donor_name,
        }) as span:
            try:
                validate_request(request)
            except DonationValidationError as exc:
                # Metrics: Track validation failure
                metrics.increment("donations.async.validation_failed.total")

                # Structured logging: Log validation failure
                structured_logger.warning("donation_async_validation_failed", extra={
                    "donor": request.donor_name,
                    "amount": request.amount,
                    "source": request.source,
                    "error": str(exc),
                    "duration_ms": (time.time() - start_time) * 1000,
                })

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

                # Calculate processing duration
                duration_ms = (time.time() - start_time) * 1000

                # Metrics: Track successful async donation
                metrics.increment("donations.async.total", tags={"source": request.source})
                metrics.histogram("donation.async.amount", request.amount)
                metrics.histogram("donation.async.processing_time.duration_ms", duration_ms)

                # Structured logging: Log successful async donation
                structured_logger.info("donation_async_processed", extra={
                    "donor": request.donor_name,
                    "amount": request.amount,
                    "source": request.source,
                    "guild_id": str(request.discord_guild_id) if request.discord_guild_id else None,
                    "member_count": member_count,
                    "old_power": old_state.current_power if old_state else None,
                    "new_power": new_state.current_power if new_state else None,
                    "power_gained": (new_state.current_power - old_state.current_power) if (old_state and new_state) else None,
                    "event_id": event_id,
                    "duration_ms": duration_ms,
                })

                # Tracing: Add success attributes
                if span:
                    span.set_attribute("success", True)
                    span.set_attribute("amount", request.amount)
                    span.set_attribute("duration_ms", duration_ms)
                    span.set_attribute("member_count", member_count or 0)

                return DonationResult.from_states(
                    success=True,
                    old_state=old_state,
                    new_state=new_state,
                    event_emitted=True,
                    event_id=event_id,
                )
            except MechServiceError as exc:
                # Mech service errors (state save/load, power calculations)
                duration_ms = (time.time() - start_time) * 1000
                metrics.increment("donations.async.mech_error.total")

                logger.error("Mech service error during async donation: %s", exc, exc_info=True)
                structured_logger.error("donation_async_mech_error", extra={
                    "donor": request.donor_name,
                    "amount": request.amount,
                    "source": request.source,
                    "error": str(exc),
                    "error_code": getattr(exc, 'error_code', 'MECH_ERROR'),
                    "duration_ms": duration_ms,
                })

                if span:
                    span.set_attribute("success", False)
                    span.set_attribute("error_type", "MechServiceError")
                    span.set_attribute("error", str(exc))

                return DonationResult.from_states(
                    success=False,
                    old_state=None,
                    new_state=None,
                    error_message=f"Mech service error: {exc}",
                    error_code="MECH_SERVICE_ERROR",
                )
            except (ValueError, TypeError, AttributeError, KeyError) as exc:
                # Data format/structure errors
                duration_ms = (time.time() - start_time) * 1000
                metrics.increment("donations.async.data_error.total")

                logger.error("Data error during async donation: %s", exc, exc_info=True)
                structured_logger.error("donation_async_data_error", extra={
                    "donor": request.donor_name,
                    "amount": request.amount,
                    "source": request.source,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                    "duration_ms": duration_ms,
                })

                if span:
                    span.set_attribute("success", False)
                    span.set_attribute("error_type", type(exc).__name__)
                    span.set_attribute("error", str(exc))

                return DonationResult.from_states(
                    success=False,
                    old_state=None,
                    new_state=None,
                    error_message=f"Data processing error: {exc}",
                    error_code="DATA_ERROR",
                )
            except (RuntimeError, OSError) as exc:  # pragma: no cover - defensive logging
                # System/runtime errors (file I/O, event emission)
                duration_ms = (time.time() - start_time) * 1000
                metrics.increment("donations.async.system_error.total")

                logger.error("System error during async donation: %s", exc, exc_info=True)
                structured_logger.error("donation_async_system_error", extra={
                    "donor": request.donor_name,
                    "amount": request.amount,
                    "source": request.source,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                    "duration_ms": duration_ms,
                })

                if span:
                    span.set_attribute("success", False)
                    span.set_attribute("error_type", type(exc).__name__)
                    span.set_attribute("error", str(exc))

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

