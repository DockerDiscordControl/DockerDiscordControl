#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Donation Service                               #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""
Donation Service - Handles donation processing, validation, and notifications
"""

from utils.logging_utils import get_module_logger
import os
import time
import json
import re
import unicodedata
import logging
from datetime import datetime
from typing import Dict, Any, Tuple, Optional
from dataclasses import dataclass

from utils.atomic_io import atomic_write_json

from services.donation.donation_utils import donation_is_already_recorded
from services.donation.unified.validation import MAX_DONATION_DOLLARS

logger = get_module_logger('donation_service')


@dataclass
class DonationRequest:
    """Represents a donation request with all parameters."""
    amount: float
    donor_name: str
    publish_to_discord: bool = True
    source: str = 'web_ui_manual'
    # The browser's token; a retry carries the same one. SPEC.md Z4.
    idempotency_key: Optional[str] = None


@dataclass
class DonationResult:
    """Represents the result of a donation processing."""
    success: bool
    message: str = ""
    donation_info: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    status_code: int = 200  # 400 = invalid input (message is safe to show), 500 = processing error


class DonationService:
    """Service for processing donations with validation, sanitization, and notifications."""

    # Business rules constants.
    # ONE number, taken from the ledger's own gate. There used to be a second,
    # 999999.0, so $50,000 passed the panel, was refused by validate_request
    # with a sentence written to be read - "Amount exceeds the maximum allowed
    # value (10,000.00)" - and came back to the operator as a bare 500 saying
    # "Failed to process donation". Two ways to say the same thing always
    # drift; this pair had drifted by a factor of a hundred.
    MAX_DONATION_AMOUNT = MAX_DONATION_DOLLARS
    MAX_DONOR_NAME_LENGTH = 50
    # Letters of ANY alphabet, not just ASCII. The old pattern was
    # r'[^a-zA-Z0-9\s\-_\.]', which turned Mueller written with an umlaut into
    # "Mller" and a Japanese name into "Anonymous" - silently, into a payload
    # that is append-only and replayed on every rebuild. The strip is not what
    # makes a name safe to show: the panel writes it with textContent and a
    # Discord embed is markdown, not HTML. What a name must not carry is a line
    # break (it would break the embed layout) and the invisible characters that
    # make text read backwards or hide inside another name - those are removed
    # by _CONTROL_CHARACTERS below, before this pattern is applied.
    DONOR_NAME_PATTERN = r'[^\w\s\-_\.]'
    # None = the config directory via utils/config_paths.py (DDC_CONFIG_DIR).
    # Was hard-wired to "/app/config": blind to the variable, and outside the
    # container creating it failed and the announcement was lost. Kept as a
    # settable attribute - tests redirect it per instance.
    NOTIFICATION_DIR = None

    def __init__(self):
        self.logger = logger

    def process_donation(self, request: DonationRequest) -> DonationResult:
        """
        Process a donation request with full validation, sanitization, and business logic.

        Args:
            request: DonationRequest object with donation details

        Returns:
            DonationResult with success status and details
        """
        try:
            # Step 1: Validate and sanitize input
            validation_result = self._validate_and_sanitize_request(request)
            if not validation_result.success:
                return validation_result

            # Step 2: Process donation through MechService
            mech_result = self._process_mech_donation(request)
            if not mech_result['success']:
                return DonationResult(
                    success=False,
                    message="Donation processing failed",
                    error=mech_result['error'],
                    status_code=500
                )

            # The ledger DEDUPES a retry (Z4) and answers it as an ordinary
            # success, so nothing below could tell the two apart: a donor whose
            # answer was lost and who pressed the button again got a second
            # announcement in every channel and a second line in the action log
            # for one payment. Only a booking that really happened is announced.
            if donation_is_already_recorded(request.idempotency_key):
                self.logger.info(
                    "Donation already in the ledger under this key - booked once, "
                    "announced once; this submission is a repeat")
                return self._build_donation_response(request, mech_result, False)

            # Step 3: Handle Discord notifications
            discord_success = self._handle_discord_notification(request)

            # Step 4: Log the action
            self._log_donation_action(request, discord_success)

            # Step 5: Build response
            return self._build_donation_response(request, mech_result, discord_success)

        except (ImportError, AttributeError, RuntimeError) as e:
            self.logger.error(f"Service error processing donation: {e}", exc_info=True)
            return DonationResult(
                success=False,
                message="Donation processing failed",
                error=f"Service error: {str(e)}"
            )
        except (ValueError, TypeError, KeyError) as e:
            self.logger.error(f"Data error processing donation: {e}", exc_info=True)
            return DonationResult(
                success=False,
                message="Donation processing failed",
                error=f"Data validation error: {str(e)}"
            )

    def _validate_and_sanitize_request(self, request: DonationRequest) -> DonationResult:
        """Validate and sanitize donation request data."""
        # Validate amount
        if not isinstance(request.amount, (int, float)) or request.amount <= 0:
            return DonationResult(success=False, message='Invalid donation amount',
                                  error='Invalid donation amount', status_code=400)

        if request.amount > self.MAX_DONATION_AMOUNT:
            max_msg = f'Maximum donation amount is ${self.MAX_DONATION_AMOUNT:,.0f}'
            return DonationResult(success=False, message=max_msg, error=max_msg, status_code=400)

        # Round to 2 decimal places to prevent floating point issues
        request.amount = round(float(request.amount), 2)
        if request.amount <= 0:
            # Positive but below one cent
            return DonationResult(success=False, message='Invalid donation amount',
                                  error='Invalid donation amount', status_code=400)

        # Validate and sanitize donor name
        if not isinstance(request.donor_name, str):
            request.donor_name = 'Anonymous'

        request.donor_name = request.donor_name.strip() or 'Anonymous'

        # NFC first, so a letter written as "u" plus a combining umlaut counts
        # as one character and survives the filter as one.
        request.donor_name = unicodedata.normalize('NFC', request.donor_name)
        # Control and format characters (Unicode category C) go first and
        # unconditionally: line breaks, NUL, escape sequences, the
        # right-to-left override and the zero-width space.
        request.donor_name = ''.join(
            ch for ch in request.donor_name if unicodedata.category(ch)[0] != 'C')
        # Then anything that is not a letter, a digit, a space or - _ .
        request.donor_name = re.sub(self.DONOR_NAME_PATTERN, '', request.donor_name)
        request.donor_name = request.donor_name[:self.MAX_DONOR_NAME_LENGTH]

        # Final check - if empty after sanitization, use Anonymous
        if not request.donor_name.strip():
            request.donor_name = 'Anonymous'

        return DonationResult(success=True, message='Validation passed')

    def _process_mech_donation(self, request: DonationRequest) -> Dict[str, Any]:
        """Process donation through MechService.

        The line below `donation_result.success` is the one that matters: above
        it nothing has been booked, below it the money has moved. Reading the
        new state back used to sit on the wrong side of that line, so an
        unreadable state turned a BOOKED donation into "Donation processing
        failed", 500 - and the donor, reasonably, donated again (review C26).
        """
        try:
            # UNIFIED DONATION SERVICE: Centralized processing with guaranteed events
            from services.donation.unified_donation_service import process_web_ui_donation

            donation_result = process_web_ui_donation(
                donor_name=request.donor_name,
                amount=request.amount,  # already rounded to cents; int() dropped them ($10.75 -> $10)
                idempotency_key=request.idempotency_key,
            )
        except (ImportError, AttributeError) as e:
            self.logger.error(f"Mech service import error: {e}", exc_info=True)
            return {
                'success': False,
                'error': f'Mech service unavailable: {str(e)}'
            }
        except (RuntimeError, ValueError, TypeError) as e:
            self.logger.error(f"Mech service processing error: {e}", exc_info=True)
            return {
                'success': False,
                'error': f'Failed to process donation: {str(e)}'
            }

        if not donation_result.success:
            self.logger.error(f"Donation refused: {donation_result.error_message}")
            return {
                'success': False,
                'error': f'Failed to process donation: {donation_result.error_message}'
            }

        # ---- Booked. Nothing below may report this donation as a failure. ----
        try:
            result_state = donation_result.new_state
        except Exception as e:  # noqa: BLE001 - see the docstring
            self.logger.error(
                f"Donation booked but the new mech state could not be read: {e}",
                exc_info=True)
            result_state = None

        self.logger.info(f"Manual donation processed: ${request.amount} from {request.donor_name}")

        return {
            'success': True,
            'mech_state': result_state
        }

    def _handle_discord_notification(self, request: DonationRequest) -> bool:
        """Handle Discord notification publishing."""
        if not request.publish_to_discord:
            return False

        try:
            # Create notification data
            notification = {
                "type": "donation",
                "donor": request.donor_name,
                "amount": request.amount,
                "timestamp": datetime.now().isoformat()
            }

            # Write notification file that bot can pick up
            from utils.config_paths import get_config_dir
            notification_dir = self.NOTIFICATION_DIR or str(get_config_dir())
            os.makedirs(notification_dir, exist_ok=True)
            # One file per announcement, the write time in the name. With a
            # single fixed name, two donations booked inside the bot's 30
            # second poll (cogs/docker_control.py, check_donation_notifications)
            # left one file: the first announcement was gone, silently.
            # time_ns and the pid keep two writers apart; the reader takes them
            # in name order, which is age order.
            notification_file = (f"{notification_dir}/donation_notification_"
                                 f"{time.time_ns()}_{os.getpid()}.json")

            # Write atomically, not with open(..., "w"): this file has a
            # CONCURRENT reader. services/donation/notification_service.py:26
            # reads it, cogs/docker_control.py:5152 polls it every 30 seconds,
            # and both halves run in the same process (web UI in a background
            # thread, bot in the main thread).
            #
            # open(..., "w") truncates on open, and json.dump writes as a stream.
            # Measured: if serialisation fails, a HALF record that starts validly
            # is left behind ('{"type": "donation", "donor": "Bob", "amount": ').
            # The reader then raises JSONDecodeError and DELETES the file
            # (notification_service.py:56-64) - the donation announcement is gone
            # for good, reported only by a logger.error line.
            #
            # atomic_write_json serialises BEFORE opening (utils/atomic_io.py:66-69)
            # and replaces via os.replace: the file appears whole or not at all.
            atomic_write_json(notification_file, notification)

            self.logger.info(f"🔔 Discord notification created: {notification_file}")
            self.logger.info(f"🔔 Notification: {request.donor_name} donated ${request.amount}")

            return True

        except (IOError, OSError, PermissionError) as e:
            self.logger.error(f"Discord notification file I/O error: {e}", exc_info=True)
            return False
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            self.logger.error(f"Discord notification JSON error: {e}", exc_info=True)
            return False

    def _log_donation_action(self, request: DonationRequest, discord_success: bool) -> None:
        """Log donation action for audit trail."""
        try:
            from services.infrastructure.action_logger import log_user_action

            log_user_action(
                action="MANUAL_DONATION",
                target=f"${request.amount} from {request.donor_name}",
                source="Web UI Modal",
                details=f"Amount: ${request.amount}, Donor: {request.donor_name}, Discord: {discord_success}, Source: {request.source}"
            )
        except (ImportError, AttributeError) as e:
            self.logger.warning(f"Action logger service unavailable: {e}")
        except (RuntimeError, ValueError, TypeError) as e:
            self.logger.warning(f"Failed to log donation action: {e}")

    def _build_donation_response(self, request: DonationRequest, mech_result: Dict[str, Any], discord_success: bool) -> DonationResult:
        """Build final donation response with all details."""
        mech_state = mech_result.get('mech_state')

        # None, not 0 / 1 / "SCRAP MECH". When the state could not be read, the
        # donation still happened - but nobody measured these numbers, and
        # filling the donor's screen with them would be the same invention that
        # review C1 removed from the container stats (review C26).
        new_power = mech_state.Power if mech_state else None
        total_donations = mech_state.total_donated if mech_state else None
        mech_level = mech_state.level if mech_state else None
        mech_level_name = mech_state.level_name if mech_state else None

        # Log evolution detection
        if mech_state and hasattr(mech_state, 'level') and mech_state.level > 1:
            self.logger.info(f"Donation may have triggered evolution - current level: {mech_state.level}")

        donation_info = {
            'amount': request.amount,
            'donor_name': request.donor_name,
            'published_to_discord': discord_success,
            'new_Power': new_power,
            'total_donations': total_donations,
            'mech_level': mech_level,
            'mech_level_name': mech_level_name
        }

        message = f'Donation of ${request.amount} from {request.donor_name} processed successfully!'
        if mech_state is None:
            message += ' The new mech state could not be read - the donation itself went through.'

        return DonationResult(
            success=True,
            message=message,
            donation_info=donation_info
        )


# Singleton instance
_donation_service = None


def get_donation_service() -> DonationService:
    """Get the singleton DonationService instance."""
    global _donation_service
    if _donation_service is None:
        _donation_service = DonationService()
    return _donation_service
