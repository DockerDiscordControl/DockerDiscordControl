# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Validation helpers for the unified donation service."""

from __future__ import annotations

from services.donation.unified.models import DonationRequest


class DonationValidationError(ValueError):
    """Raised when a donation request fails validation checks."""


def validate_request(request: DonationRequest) -> None:
    """Validate a :class:`DonationRequest`.

    Raises:
        DonationValidationError: If the request contains invalid data.
    """

    donor_name = (request.donor_name or "").strip()
    if not donor_name or len(donor_name) > 100:
        raise DonationValidationError("Donor name must be between 1 and 100 characters")

    amount = request.amount
    if not isinstance(amount, (int, float)):
        raise DonationValidationError("Amount must be a positive number")
    if amount <= 0:
        raise DonationValidationError("Amount must be a positive number")
    if amount > 1_000_000:
        raise DonationValidationError("Amount exceeds maximum allowed value (1,000,000)")

