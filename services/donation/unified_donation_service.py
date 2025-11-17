# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Backwards compatible wrapper for the unified donation service."""

from services.donation.unified import (
    DonationRequest,
    DonationResult,
    UnifiedDonationService,
    get_unified_donation_service,
    process_discord_donation,
    process_test_donation,
    process_web_ui_donation,
    reset_all_donations,
)

__all__ = [
    "DonationRequest",
    "DonationResult",
    "UnifiedDonationService",
    "get_unified_donation_service",
    "process_discord_donation",
    "process_test_donation",
    "process_web_ui_donation",
    "reset_all_donations",
]

