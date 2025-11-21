#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Donation Tracking Service                      #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""
Donation Tracking Service - Handles donation button click tracking and user identification
"""

import logging
from datetime import datetime, timezone
from typing import Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class DonationClickRequest:
    """Represents a donation click tracking request."""
    donation_type: str
    request_object: object  # Flask request object for user identification


@dataclass
class DonationClickResult:
    """Represents the result of donation click tracking operation."""
    success: bool
    message: str
    timestamp: Optional[str] = None
    error: Optional[str] = None


class DonationTrackingService:
    """Service for handling donation button click tracking."""

    def __init__(self):
        self.logger = logger

    def record_donation_click(self, request: DonationClickRequest) -> DonationClickResult:
        """
        Record a donation button click with comprehensive tracking.

        Args:
            request: DonationClickRequest with donation type and request data

        Returns:
            DonationClickResult with tracking status and details
        """
        try:
            # Step 1: Validate donation type
            validation_result = self._validate_donation_type(request.donation_type)
            if not validation_result['valid']:
                return DonationClickResult(
                    success=False,
                    error=validation_result['error']
                )

            # Step 2: Get user identifier
            user_identifier = self._get_user_identifier(request.request_object)

            # Step 3: Get current timestamp for Matrix Thank You animation
            current_timestamp = self._get_current_timestamp()

            # Step 4: Log the action
            self._log_donation_action(request.donation_type, user_identifier)

            # Step 5: Log for Matrix server integration
            self._log_matrix_server_action(request.donation_type, user_identifier, current_timestamp)

            return DonationClickResult(
                success=True,
                message='Donation button click recorded for Matrix Thank You animation',
                timestamp=current_timestamp
            )

        except (RuntimeError, discord.Forbidden, discord.HTTPException, discord.NotFound) as e:
            self.logger.error(f"Error recording donation click: {e}", exc_info=True)
            return DonationClickResult(
                success=False,
                error=f"Error recording donation click: {str(e)}"
            )

    def _validate_donation_type(self, donation_type: str) -> dict:
        """Validate the donation type."""
        if donation_type not in ['coffee', 'paypal']:
            return {
                'valid': False,
                'error': 'Invalid donation type'
            }

        return {'valid': True}

    def _get_user_identifier(self, request_obj) -> str:
        """Get user identifier from request - tries username first, falls back to IP."""
        user_identifier = "Anonymous User"

        try:
            # Try to get authenticated username
            from app.auth import auth
            authenticated_user = auth.current_user()
            if authenticated_user:
                user_identifier = f"Web User: {authenticated_user}"
            else:
                # Fallback to IP address
                user_identifier = self._get_ip_identifier(request_obj)
        except:
            # Final fallback to IP
            user_identifier = self._get_ip_identifier(request_obj)

        return user_identifier

    def _get_ip_identifier(self, request_obj) -> str:
        """Get IP-based user identifier."""
        try:
            ip_address = request_obj.remote_addr
            if request_obj.headers.get('X-Forwarded-For'):
                ip_address = request_obj.headers.get('X-Forwarded-For').split(',')[0].strip()
            return f"IP: {ip_address}"
        except:
            return "IP: Unknown"

    def _get_current_timestamp(self) -> str:
        """Get current timestamp for Matrix Thank You animation."""
        return datetime.now(timezone.utc).isoformat()

    def _log_donation_action(self, donation_type: str, user_identifier: str) -> None:
        """Log the donation action using action logger."""
        try:
            from services.infrastructure.action_logger import log_user_action
            log_user_action(
                action="DONATION_CLICK",
                target=f"Donation Button ({donation_type})",
                source="Web UI DonationTrackingService",
                details=f"Donation button clicked by: {user_identifier}"
            )
        except (RuntimeError) as e:
            self.logger.warning(f"Failed to log donation action: {e}")

    def _log_matrix_server_action(self, donation_type: str, user_identifier: str, timestamp: str) -> None:
        """Log for Matrix server integration."""
        try:
            self.logger.info(
                f"💰 [MATRIX-SERVER] Donation button ({donation_type}) clicked by {user_identifier} - timestamp: {timestamp}"
            )
        except (RuntimeError) as e:
            self.logger.warning(f"Failed to log Matrix server action: {e}")


# Singleton instance
_donation_tracking_service = None


def get_donation_tracking_service() -> DonationTrackingService:
    """Get the singleton DonationTrackingService instance."""
    global _donation_tracking_service
    if _donation_tracking_service is None:
        _donation_tracking_service = DonationTrackingService()
    return _donation_tracking_service
