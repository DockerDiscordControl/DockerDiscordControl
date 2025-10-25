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

import os
import json
import re
import logging
from datetime import datetime
from typing import Dict, Any, Tuple, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class DonationRequest:
    """Represents a donation request with all parameters."""
    amount: float
    donor_name: str
    publish_to_discord: bool = True
    source: str = 'web_ui_manual'


@dataclass
class DonationResult:
    """Represents the result of a donation processing."""
    success: bool
    message: str
    donation_info: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class DonationService:
    """Service for processing donations with validation, sanitization, and notifications."""

    # Business rules constants
    MAX_DONATION_AMOUNT = 999999.0
    MAX_DONOR_NAME_LENGTH = 50
    DONOR_NAME_PATTERN = r'[^a-zA-Z0-9\s\-_\.]'  # Remove anything not alphanumeric, space, dash, underscore, dot
    NOTIFICATION_DIR = "/app/config"

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
                    error=mech_result['error']
                )

            # Step 3: Handle Discord notifications
            discord_success = self._handle_discord_notification(request)

            # Step 4: Log the action
            self._log_donation_action(request, discord_success)

            # Step 5: Build response
            return self._build_donation_response(request, mech_result, discord_success)

        except Exception as e:
            self.logger.error(f"Error processing donation: {e}", exc_info=True)
            return DonationResult(
                success=False,
                error=f"Error processing donation: {str(e)}"
            )

    def _validate_and_sanitize_request(self, request: DonationRequest) -> DonationResult:
        """Validate and sanitize donation request data."""
        # Validate amount
        if not isinstance(request.amount, (int, float)) or request.amount <= 0:
            return DonationResult(success=False, error='Invalid donation amount')

        if request.amount > self.MAX_DONATION_AMOUNT:
            return DonationResult(success=False, error=f'Maximum donation amount is ${self.MAX_DONATION_AMOUNT:,.0f}')

        # Round to 2 decimal places to prevent floating point issues
        request.amount = round(float(request.amount), 2)

        # Validate and sanitize donor name
        if not isinstance(request.donor_name, str):
            request.donor_name = 'Anonymous'

        request.donor_name = request.donor_name.strip() or 'Anonymous'

        # Remove potentially dangerous characters (HTML, scripts, etc.)
        request.donor_name = re.sub(self.DONOR_NAME_PATTERN, '', request.donor_name)
        request.donor_name = request.donor_name[:self.MAX_DONOR_NAME_LENGTH]

        # Final check - if empty after sanitization, use Anonymous
        if not request.donor_name.strip():
            request.donor_name = 'Anonymous'

        return DonationResult(success=True, message='Validation passed')

    def _process_mech_donation(self, request: DonationRequest) -> Dict[str, Any]:
        """Process donation through MechService."""
        try:
            # UNIFIED DONATION SERVICE: Centralized processing with guaranteed events
            from services.donation.unified_donation_service import process_web_ui_donation

            donation_result = process_web_ui_donation(
                donor_name=request.donor_name,
                amount=int(request.amount)
            )

            if not donation_result.success:
                raise Exception(f"Donation failed: {donation_result.error_message}")

            result_state = donation_result.new_state

            self.logger.info(f"Manual donation processed: ${request.amount} from {request.donor_name}")

            return {
                'success': True,
                'mech_state': result_state
            }

        except Exception as e:
            self.logger.error(f"Error adding donation to mech service: {e}")
            return {
                'success': False,
                'error': 'Failed to process donation through mech system'
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
            os.makedirs(self.NOTIFICATION_DIR, exist_ok=True)
            notification_file = f"{self.NOTIFICATION_DIR}/donation_notification.json"

            with open(notification_file, "w") as f:
                json.dump(notification, f)

            self.logger.info(f"🔔 Discord notification created: {notification_file}")
            self.logger.info(f"🔔 Notification: {request.donor_name} donated ${request.amount}")

            return True

        except Exception as e:
            self.logger.error(f"Discord notification failed: {e}")
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
        except Exception as e:
            self.logger.warning(f"Failed to log donation action: {e}")

    def _build_donation_response(self, request: DonationRequest, mech_result: Dict[str, Any], discord_success: bool) -> DonationResult:
        """Build final donation response with all details."""
        mech_state = mech_result.get('mech_state')

        # Extract mech state information
        new_power = mech_state.Power if mech_state else 0
        total_donations = mech_state.total_donated if mech_state else 0
        mech_level = mech_state.level if mech_state else 1
        mech_level_name = mech_state.level_name if mech_state else 'SCRAP MECH'

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

        return DonationResult(
            success=True,
            message=f'Donation of ${request.amount} from {request.donor_name} processed successfully!',
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