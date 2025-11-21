# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Donation Management Service Tests              #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Unit tests for the Donation Management Service.
Tests all donation-related functionality including history, stats, and deletion.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from services.donation.donation_management_service import (
    DonationManagementService,
    DonationStats,
    ServiceResult
)


class TestDonationManagementService:
    """Test suite for DonationManagementService."""

    def setup_method(self):
        """Setup test fixtures for each test method."""
        self.service = DonationManagementService()

    def test_service_initialization(self):
        """Test that the service initializes correctly."""
        assert self.service is not None
        assert isinstance(self.service, DonationManagementService)

    @patch('services.donation.donation_management_service.get_mech_service')
    def test_get_donation_history_success(self, mock_get_mech_service):
        """Test successful retrieval of donation history."""
        # Mock mech service and state
        mock_mech_service = Mock()
        mock_state = Mock()
        mock_state.total_donated = 250.75
        mock_mech_service.get_state.return_value = mock_state

        # Mock store data
        mock_store_data = {
            'donations': [
                {'username': 'Alice', 'amount': 50.0, 'ts': '2025-01-01T10:00:00Z'},
                {'username': 'Bob', 'amount': 100.25, 'ts': '2025-01-01T11:00:00Z'},
                {'username': 'Charlie', 'amount': 25.50, 'ts': '2025-01-01T12:00:00Z'},
            ]
        }
        mock_mech_service.store.load.return_value = mock_store_data
        mock_get_mech_service.return_value = mock_mech_service

        # Test the method
        result = self.service.get_donation_history(limit=10)

        # Assertions
        assert result.success is True
        assert result.data is not None
        assert 'donations' in result.data
        assert 'stats' in result.data

        donations = result.data['donations']
        stats = result.data['stats']

        # Check donations are returned in reverse order (newest first)
        assert len(donations) == 3
        assert donations[0]['donor_name'] == 'Charlie'  # Most recent
        assert donations[1]['donor_name'] == 'Bob'
        assert donations[2]['donor_name'] == 'Alice'    # Oldest

        # Check stats
        assert stats.total_power == 250.75
        assert stats.total_donations == 3
        assert stats.average_donation == 250.75 / 3

    @patch('services.donation.donation_management_service.get_mech_service')
    def test_get_donation_history_empty(self, mock_get_mech_service):
        """Test donation history retrieval with no donations."""
        # Mock empty mech service
        mock_mech_service = Mock()
        mock_state = Mock()
        mock_state.total_donated = 0.0
        mock_mech_service.get_state.return_value = mock_state
        mock_mech_service.store.load.return_value = {'donations': []}
        mock_get_mech_service.return_value = mock_mech_service

        result = self.service.get_donation_history()

        assert result.success is True
        assert len(result.data['donations']) == 0
        assert result.data['stats'].total_power == 0.0
        assert result.data['stats'].total_donations == 0
        assert result.data['stats'].average_donation == 0.0

    @patch('services.donation.donation_management_service.get_mech_service')
    def test_get_donation_history_limit(self, mock_get_mech_service):
        """Test donation history retrieval with limit parameter."""
        mock_mech_service = Mock()
        mock_state = Mock()
        mock_state.total_donated = 500.0
        mock_mech_service.get_state.return_value = mock_state

        # Mock 10 donations
        donations = [
            {'username': f'User{i}', 'amount': 50.0, 'ts': f'2025-01-01T{i:02d}:00:00Z'}
            for i in range(10)
        ]
        mock_mech_service.store.load.return_value = {'donations': donations}
        mock_get_mech_service.return_value = mock_mech_service

        # Test with limit of 5
        result = self.service.get_donation_history(limit=5)

        assert result.success is True
        assert len(result.data['donations']) == 5
        # Should get the last 5 donations (newest first)
        assert result.data['donations'][0]['donor_name'] == 'User9'
        assert result.data['donations'][4]['donor_name'] == 'User5'

    @patch('services.donation.donation_management_service.get_mech_service')
    def test_delete_donation_success(self, mock_get_mech_service):
        """Test successful deletion of a donation."""
        mock_mech_service = Mock()
        donations = [
            {'username': 'Alice', 'amount': 50.0, 'ts': '2025-01-01T10:00:00Z'},
            {'username': 'Bob', 'amount': 100.0, 'ts': '2025-01-01T11:00:00Z'},
            {'username': 'Charlie', 'amount': 25.0, 'ts': '2025-01-01T12:00:00Z'},
        ]
        mock_store_data = {'donations': donations.copy()}
        mock_mech_service.store.load.return_value = mock_store_data
        mock_get_mech_service.return_value = mock_mech_service

        # Delete index 0 (should be Charlie - newest first in display)
        result = self.service.delete_donation(0)

        assert result.success is True
        assert result.data['donor_name'] == 'Charlie'
        assert result.data['amount'] == 25.0
        assert result.data['index'] == 0

        # Verify save was called with updated data
        mock_mech_service.store.save.assert_called_once()
        saved_data = mock_mech_service.store.save.call_args[0][0]
        assert len(saved_data['donations']) == 2
        # Charlie (last item) should be removed
        assert saved_data['donations'][-1]['username'] != 'Charlie'

    @patch('services.donation.donation_management_service.get_mech_service')
    def test_delete_donation_invalid_index(self, mock_get_mech_service):
        """Test deletion with invalid index."""
        mock_mech_service = Mock()
        donations = [{'username': 'Alice', 'amount': 50.0, 'ts': '2025-01-01T10:00:00Z'}]
        mock_mech_service.store.load.return_value = {'donations': donations}
        mock_get_mech_service.return_value = mock_mech_service

        # Try to delete index 5 when only 1 donation exists
        result = self.service.delete_donation(5)

        assert result.success is False
        assert "Invalid donation index" in result.error

    @patch('services.donation.donation_management_service.get_mech_service')
    def test_get_donation_stats(self, mock_get_mech_service):
        """Test donation statistics retrieval."""
        mock_mech_service = Mock()
        mock_state = Mock()
        mock_state.total_donated = 175.0
        mock_mech_service.get_state.return_value = mock_state

        donations = [
            {'username': 'User1', 'amount': 75.0},
            {'username': 'User2', 'amount': 100.0}
        ]
        mock_mech_service.store.load.return_value = {'donations': donations}
        mock_get_mech_service.return_value = mock_mech_service

        result = self.service.get_donation_stats()

        assert result.success is True
        stats = result.data
        assert stats.total_power == 175.0
        assert stats.total_donations == 2
        assert stats.average_donation == 87.5

    @patch('services.donation.donation_management_service.get_mech_service')
    def test_service_exception_handling(self, mock_get_mech_service):
        """Test that service handles exceptions gracefully."""
        # Make mech service raise an exception
        mock_get_mech_service.side_effect = Exception("Mech service error")

        result = self.service.get_donation_history()

        assert result.success is False
        assert "Error retrieving donation history" in result.error
        assert "Mech service error" in result.error


class TestDonationStats:
    """Test suite for DonationStats data class."""

    def test_donation_stats_creation(self):
        """Test DonationStats creation and properties."""
        stats = DonationStats(
            total_power=250.0,
            total_donations=10,
            average_donation=25.0
        )

        assert stats.total_power == 250.0
        assert stats.total_donations == 10
        assert stats.average_donation == 25.0

    def test_donation_stats_from_data(self):
        """Test DonationStats.from_data class method."""
        donations = [
            {'amount': 50.0}, {'amount': 75.0}, {'amount': 25.0}
        ]
        total_power = 150.0

        stats = DonationStats.from_data(donations, total_power)

        assert stats.total_power == 150.0
        assert stats.total_donations == 3
        assert stats.average_donation == 50.0

    def test_donation_stats_from_empty_data(self):
        """Test DonationStats.from_data with empty donations."""
        stats = DonationStats.from_data([], 0.0)

        assert stats.total_power == 0.0
        assert stats.total_donations == 0
        assert stats.average_donation == 0.0


# Integration test with real service (but mocked dependencies)
@pytest.mark.integration
class TestDonationManagementServiceIntegration:
    """Integration tests for donation management service."""

    @patch('services.donation.donation_management_service.get_mech_service')
    def test_full_donation_workflow(self, mock_get_mech_service):
        """Test a complete donation management workflow."""
        service = DonationManagementService()

        # Setup mock with initial data
        mock_mech_service = Mock()
        mock_state = Mock()
        mock_state.total_donated = 300.0
        mock_mech_service.get_state.return_value = mock_state

        initial_donations = [
            {'username': 'Alice', 'amount': 100.0, 'ts': '2025-01-01T10:00:00Z'},
            {'username': 'Bob', 'amount': 200.0, 'ts': '2025-01-01T11:00:00Z'},
        ]
        mock_store_data = {'donations': initial_donations.copy()}
        mock_mech_service.store.load.return_value = mock_store_data
        mock_get_mech_service.return_value = mock_mech_service

        # 1. Get initial donation history
        history_result = service.get_donation_history()
        assert history_result.success is True
        assert len(history_result.data['donations']) == 2

        # 2. Get stats
        stats_result = service.get_donation_stats()
        assert stats_result.success is True
        assert stats_result.data.total_donated == 300.0

        # 3. Delete a donation
        delete_result = service.delete_donation(0)  # Delete newest (Bob)
        assert delete_result.success is True
        assert delete_result.data['donor_name'] == 'Bob'

        # Verify the store was updated
        mock_mech_service.store.save.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
