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

# Kept in step with progress_service.MAX_DONATION (the ledger's own gate).
MAX_DONATION_DOLLARS = 10_000.00


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
    # The operator's limit, so the panel refuses it instead of an exception
    # arriving from the depths of the ledger. The ledger keeps its own gate -
    # this one is for the donor to read (review D2).
    if amount > MAX_DONATION_DOLLARS:
        raise DonationValidationError(
            f"Amount exceeds the maximum allowed value ({MAX_DONATION_DOLLARS:,.2f})")

