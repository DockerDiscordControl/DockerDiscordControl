# -*- coding: utf-8 -*-
"""
Integration tests for donation flow.

Tests end-to-end donation processing with real service integration.
"""

import pytest
from services.donation.unified.service import get_unified_donation_service
from services.donation.unified.models import DonationRequest
from services.mech.mech_service import get_mech_service


class TestDonationFlowIntegration:
    """Integration tests for complete donation flow."""

    @pytest.fixture(autouse=True)
    def setup_and_teardown(self):
        """Setup and teardown for each test."""
        # Setup
        self.donation_service = get_unified_donation_service()
        self.mech_service = get_mech_service()

        # Get initial state
        self.initial_state = self.mech_service.get_state()

        yield

        # Teardown (cleanup is automatic)

    def test_donation_updates_mech_state(self):
        """Test donation updates mech service state."""
        # Process donation
        request = DonationRequest(
            donor_name="Integration Test Donor",
            amount=10.0,
            source="test"
        )

        result = self.donation_service.process_donation(request)

        assert result.success is True

        # Verify mech state updated
        new_state = self.mech_service.get_state()
        assert new_state.current_power > self.initial_state.current_power

    def test_multiple_donations_cumulative_effect(self):
        """Test multiple donations have cumulative effect."""
        initial_power = self.mech_service.get_state().current_power

        # Process 3 donations
        for i in range(3):
            request = DonationRequest(
                donor_name=f"Donor {i}",
                amount=5.0,
                source="test"
            )
            result = self.donation_service.process_donation(request)
            assert result.success is True

        # Power should have increased by 15
        final_power = self.mech_service.get_state().current_power
        assert final_power >= initial_power + 15.0

    def test_donation_result_contains_power_change(self):
        """Test donation result shows power change."""
        request = DonationRequest(
            donor_name="Test Donor",
            amount=5.0,
            source="test"
        )

        result = self.donation_service.process_donation(request)

        assert result.success is True
        assert result.old_state is not None
        assert result.new_state is not None
        assert result.new_state.current_power > result.old_state.current_power

    @pytest.mark.asyncio
    async def test_async_donation_integrates_with_mech_service(self):
        """Test async donation integrates with mech service."""
        initial_power = self.mech_service.get_state().current_power

        request = DonationRequest(
            donor_name="Async Donor",
            amount=7.5,
            source="discord"
        )

        result = await self.donation_service.process_donation_async(request)

        assert result.success is True

        final_power = self.mech_service.get_state().current_power
        assert final_power > initial_power

    def test_failed_donation_does_not_update_state(self):
        """Test failed donation doesn't change state."""
        initial_power = self.mech_service.get_state().current_power

        # Invalid donation (negative amount)
        request = DonationRequest(
            donor_name="Test",
            amount=-5.0,
            source="test"
        )

        result = self.donation_service.process_donation(request)

        assert result.success is False

        # Power should not have changed
        final_power = self.mech_service.get_state().current_power
        assert final_power == initial_power


# Summary: 6 integration tests for donation flow
# Tests complete integration between DonationService and MechService
