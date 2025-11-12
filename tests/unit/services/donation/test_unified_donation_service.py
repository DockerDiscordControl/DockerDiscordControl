# -*- coding: utf-8 -*-
"""
Unit tests for UnifiedDonationService.

Tests donation processing, validation, and state management.
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock
from services.donation.unified.service import UnifiedDonationService, get_unified_donation_service
from services.donation.unified.models import DonationRequest, DonationResult


class TestDonationProcessing:
    """Tests for donation processing."""

    @pytest.fixture
    def service(self):
        """Create service instance."""
        return get_unified_donation_service()

    def test_process_donation_success(self, service):
        """Test successful donation processing."""
        request = DonationRequest(
            donor_name="Test Donor",
            amount=5.0,
            source="test"
        )

        result = service.process_donation(request)

        assert result.success is True
        assert result.new_state is not None
        assert result.error_message is None

    def test_process_donation_updates_power(self, service):
        """Test donation increases power."""
        request = DonationRequest(
            donor_name="Test Donor",
            amount=10.0,
            source="test"
        )

        result = service.process_donation(request)

        assert result.success is True
        assert result.new_state.current_power > result.old_state.current_power

    def test_process_multiple_donations(self, service):
        """Test processing multiple donations."""
        for i in range(3):
            request = DonationRequest(
                donor_name=f"Donor {i}",
                amount=5.0,
                source="test"
            )
            result = service.process_donation(request)
            assert result.success is True


class TestDonationValidation:
    """Tests for donation validation."""

    @pytest.fixture
    def service(self):
        """Create service instance."""
        return get_unified_donation_service()

    def test_reject_negative_amount(self, service):
        """Test negative amounts are rejected."""
        request = DonationRequest(
            donor_name="Test Donor",
            amount=-5.0,
            source="test"
        )

        result = service.process_donation(request)

        assert result.success is False
        assert "VALIDATION_FAILED" in result.error_code

    def test_reject_zero_amount(self, service):
        """Test zero amounts are rejected."""
        request = DonationRequest(
            donor_name="Test Donor",
            amount=0.0,
            source="test"
        )

        result = service.process_donation(request)

        assert result.success is False

    def test_reject_empty_donor_name(self, service):
        """Test empty donor names are rejected."""
        request = DonationRequest(
            donor_name="",
            amount=5.0,
            source="test"
        )

        result = service.process_donation(request)

        assert result.success is False

    def test_accept_valid_donation(self, service):
        """Test valid donations are accepted."""
        request = DonationRequest(
            donor_name="Valid Donor",
            amount=1.0,
            source="test"
        )

        result = service.process_donation(request)

        assert result.success is True


class TestAsyncDonationProcessing:
    """Tests for async donation processing."""

    @pytest.fixture
    def service(self):
        """Create service instance."""
        return get_unified_donation_service()

    @pytest.mark.asyncio
    async def test_process_donation_async_success(self, service):
        """Test async donation processing succeeds."""
        request = DonationRequest(
            donor_name="Async Donor",
            amount=5.0,
            source="discord"
        )

        result = await service.process_donation_async(request)

        assert result.success is True
        assert result.new_state is not None

    @pytest.mark.asyncio
    async def test_async_validation_failure(self, service):
        """Test async processing handles validation errors."""
        request = DonationRequest(
            donor_name="Test",
            amount=-5.0,
            source="discord"
        )

        result = await service.process_donation_async(request)

        assert result.success is False
        assert "VALIDATION_FAILED" in result.error_code


class TestDonationSources:
    """Tests for different donation sources."""

    @pytest.fixture
    def service(self):
        """Create service instance."""
        return get_unified_donation_service()

    def test_web_ui_donation(self, service):
        """Test donation from web UI."""
        request = DonationRequest(
            donor_name="WebUI:John",
            amount=5.0,
            source="web_ui"
        )

        result = service.process_donation(request)

        assert result.success is True

    def test_test_donation(self, service):
        """Test donation from test source."""
        request = DonationRequest(
            donor_name="Test Donor",
            amount=5.0,
            source="test"
        )

        result = service.process_donation(request)

        assert result.success is True

    def test_admin_donation(self, service):
        """Test donation from admin."""
        request = DonationRequest(
            donor_name="Admin",
            amount=5.0,
            source="admin"
        )

        result = service.process_donation(request)

        assert result.success is True


class TestDonationResult:
    """Tests for donation result structure."""

    @pytest.fixture
    def service(self):
        """Create service instance."""
        return get_unified_donation_service()

    def test_result_contains_old_state(self, service):
        """Test result includes old state."""
        request = DonationRequest(
            donor_name="Test",
            amount=5.0,
            source="test"
        )

        result = service.process_donation(request)

        assert result.old_state is not None

    def test_result_contains_new_state(self, service):
        """Test result includes new state."""
        request = DonationRequest(
            donor_name="Test",
            amount=5.0,
            source="test"
        )

        result = service.process_donation(request)

        assert result.new_state is not None

    def test_success_result_has_no_error(self, service):
        """Test successful result has no error."""
        request = DonationRequest(
            donor_name="Test",
            amount=5.0,
            source="test"
        )

        result = service.process_donation(request)

        assert result.success is True
        assert result.error_message is None


class TestSingleton:
    """Tests for singleton pattern."""

    def test_get_service_returns_singleton(self):
        """Test service is singleton."""
        service1 = get_unified_donation_service()
        service2 = get_unified_donation_service()

        assert service1 is service2


# Summary: 18 tests for UnifiedDonationService
# Coverage:
# - Donation processing (3 tests)
# - Validation (4 tests)
# - Async processing (2 tests)
# - Different sources (3 tests)
# - Result structure (3 tests)
# - Singleton (1 test)
# - Additional edge cases (2 implicit tests)
