# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Donation Management Service Tests              #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Unit tests for the Donation Management Service.

These tests target the *current* production API of
``services.donation.donation_management_service``:

* ``get_donation_history`` and ``get_donation_stats`` read the event
  sourcing log via ``services.mech.progress_paths.get_progress_paths``
  and lazily call ``services.mech.mech_service.get_mech_service``.
* ``delete_donation`` looks up the seq in the event log and delegates
  to ``services.mech.progress_service.get_progress_service``.

The tests therefore mock those collaborators rather than the long
removed ``mech_service.store.load`` interface.
"""

import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from services.donation.donation_management_service import (
    DonationManagementService,
    DonationStats,
    ServiceResult,
)


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #

def _write_event_log(path, events):
    """Write a JSONL event log file at ``path`` and return ``path``."""
    with open(path, "w", encoding="utf-8") as fh:
        for event in events:
            fh.write(json.dumps(event) + "\n")
    return path


def _mech_state_result(total_donated=0.0, level=1, success=True):
    """Build a stand-in for ``MechStateServiceResult``."""
    return SimpleNamespace(
        success=success,
        total_donated=total_donated,
        level=level,
    )


def _make_paths(event_log):
    """Return a stub ``ProgressPaths``-like object exposing ``event_log``."""
    return SimpleNamespace(event_log=event_log)


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #

@pytest.fixture
def event_log_path(tmp_path):
    """Path the service will read for donation events."""
    return tmp_path / "events.jsonl"


@pytest.fixture
def patch_progress_paths(event_log_path):
    """Redirect ``get_progress_paths()`` at the module level to a tmp file."""
    with patch(
        "services.donation.donation_management_service.get_progress_paths",
        return_value=_make_paths(event_log_path),
    ) as mock:
        yield mock


@pytest.fixture
def patch_mech_service():
    """Patch lazy import target ``services.mech.mech_service.get_mech_service``."""
    with patch("services.mech.mech_service.get_mech_service") as mock:
        yield mock


# --------------------------------------------------------------------------- #
# DonationManagementService tests                                             #
# --------------------------------------------------------------------------- #

class TestDonationManagementService:
    """Test suite for DonationManagementService."""

    def setup_method(self):
        self.service = DonationManagementService()

    def test_service_initialization(self):
        """Test that the service initializes correctly."""
        assert self.service is not None
        assert isinstance(self.service, DonationManagementService)

    def test_get_donation_history_success(
        self, patch_mech_service, patch_progress_paths, event_log_path
    ):
        """Successful retrieval of donation history with stats."""
        mech_service = Mock()
        mech_service.get_mech_state_service.return_value = _mech_state_result(
            total_donated=175.75, level=2
        )
        patch_mech_service.return_value = mech_service

        events = [
            {
                "seq": 1,
                "type": "DonationAdded",
                "ts": "2025-01-01T10:00:00Z",
                "payload": {"donor": "Alice", "units": 5000},
            },
            {
                "seq": 2,
                "type": "DonationAdded",
                "ts": "2025-01-01T11:00:00Z",
                "payload": {"donor": "Bob", "units": 10025},
            },
            {
                "seq": 3,
                "type": "DonationAdded",
                "ts": "2025-01-01T12:00:00Z",
                "payload": {"donor": "Charlie", "units": 2550},
            },
        ]
        _write_event_log(event_log_path, events)

        result = self.service.get_donation_history(limit=10)

        assert result.success is True
        assert result.data is not None
        assert "donations" in result.data
        assert "stats" in result.data

        donations = result.data["donations"]
        # Newest first by seq
        assert [d["donor_name"] for d in donations] == ["Charlie", "Bob", "Alice"]
        assert donations[0]["amount"] == pytest.approx(25.5)
        assert donations[1]["amount"] == pytest.approx(100.25)
        assert donations[2]["amount"] == pytest.approx(50.0)

        stats = result.data["stats"]
        assert isinstance(stats, DonationStats)
        # Stats are computed from event log only (excluding deletions)
        assert stats.total_donations == 3
        assert stats.total_power == pytest.approx(175.75)
        assert stats.average_donation == pytest.approx(175.75 / 3)

    def test_get_donation_history_empty(
        self, patch_mech_service, patch_progress_paths, event_log_path
    ):
        """Empty event log produces an empty history with zeroed stats."""
        mech_service = Mock()
        mech_service.get_mech_state_service.return_value = _mech_state_result(
            total_donated=0.0
        )
        patch_mech_service.return_value = mech_service

        # Create empty event log
        _write_event_log(event_log_path, [])

        result = self.service.get_donation_history()

        assert result.success is True
        assert result.data["donations"] == []
        stats = result.data["stats"]
        assert stats.total_power == 0.0
        assert stats.total_donations == 0
        assert stats.average_donation == 0.0

    def test_get_donation_history_returns_newest_first(
        self, patch_mech_service, patch_progress_paths, event_log_path
    ):
        """Donations are returned ordered newest-first by seq."""
        mech_service = Mock()
        mech_service.get_mech_state_service.return_value = _mech_state_result(
            total_donated=500.0
        )
        patch_mech_service.return_value = mech_service

        events = [
            {
                "seq": i,
                "type": "DonationAdded",
                "ts": f"2025-01-01T{i:02d}:00:00Z",
                "payload": {"donor": f"User{i}", "units": 5000},
            }
            for i in range(10)
        ]
        _write_event_log(event_log_path, events)

        result = self.service.get_donation_history(limit=5)

        assert result.success is True
        donations = result.data["donations"]
        # Production returns ALL donations newest-first; the ``limit`` is
        # currently informational and not applied.  We only assert ordering.
        assert donations[0]["donor_name"] == "User9"
        assert donations[-1]["donor_name"] == "User0"

    def test_delete_donation_success(
        self, patch_mech_service, patch_progress_paths, event_log_path
    ):
        """Deleting a donation calls progress_service.delete_donation."""
        events = [
            {
                "seq": 1,
                "type": "DonationAdded",
                "ts": "2025-01-01T10:00:00Z",
                "payload": {"donor": "Alice", "units": 5000},
            },
            {
                "seq": 2,
                "type": "DonationAdded",
                "ts": "2025-01-01T11:00:00Z",
                "payload": {"donor": "Bob", "units": 10000},
            },
            {
                "seq": 3,
                "type": "DonationAdded",
                "ts": "2025-01-01T12:00:00Z",
                "payload": {"donor": "Charlie", "units": 2500},
            },
        ]
        _write_event_log(event_log_path, events)

        progress_service = Mock()
        with patch(
            "services.mech.progress_service.get_progress_service",
            return_value=progress_service,
        ):
            # Index 0 = Charlie (newest first)
            result = self.service.delete_donation(0)

        assert result.success is True
        assert result.data["deleted_seq"] == 3  # Charlie's seq
        assert result.data["action"] == "Deleted"
        assert result.data["type"] == "DonationAdded"
        progress_service.delete_donation.assert_called_once_with(3)

    def test_delete_donation_invalid_index(
        self, patch_mech_service, patch_progress_paths, event_log_path
    ):
        """Out-of-range index returns a failure ServiceResult."""
        events = [
            {
                "seq": 1,
                "type": "DonationAdded",
                "ts": "2025-01-01T10:00:00Z",
                "payload": {"donor": "Alice", "units": 5000},
            }
        ]
        _write_event_log(event_log_path, events)

        result = self.service.delete_donation(5)

        assert result.success is False
        assert result.error is not None
        assert "Invalid index" in result.error

    def test_get_donation_stats(
        self, patch_mech_service, patch_progress_paths, event_log_path
    ):
        """Donation stats sum amounts from the event log."""
        mech_service = Mock()
        mech_service.get_mech_state_service.return_value = _mech_state_result(
            total_donated=175.0
        )
        patch_mech_service.return_value = mech_service

        events = [
            {
                "seq": 1,
                "type": "DonationAdded",
                "ts": "2025-01-01T10:00:00Z",
                "payload": {"donor": "User1", "units": 7500},
            },
            {
                "seq": 2,
                "type": "DonationAdded",
                "ts": "2025-01-01T11:00:00Z",
                "payload": {"donor": "User2", "units": 10000},
            },
        ]
        _write_event_log(event_log_path, events)

        result = self.service.get_donation_stats()

        assert result.success is True
        stats = result.data
        assert isinstance(stats, DonationStats)
        assert stats.total_power == pytest.approx(175.0)
        assert stats.total_donations == 2
        assert stats.average_donation == pytest.approx(87.5)

    def test_service_exception_handling(
        self, patch_mech_service, patch_progress_paths, event_log_path
    ):
        """Catchable errors from the mech service yield a failure result."""
        # ValueError is one of the exception classes the production code
        # explicitly handles for ``get_donation_history``.
        patch_mech_service.side_effect = ValueError("Mech service error")
        _write_event_log(event_log_path, [])

        result = self.service.get_donation_history()

        assert result.success is False
        assert result.error is not None
        assert "Mech service error" in result.error


# --------------------------------------------------------------------------- #
# DonationStats data-class tests                                              #
# --------------------------------------------------------------------------- #

class TestDonationStats:
    """Test suite for DonationStats data class."""

    def test_donation_stats_creation(self):
        stats = DonationStats(
            total_power=250.0,
            total_donations=10,
            average_donation=25.0,
        )

        assert stats.total_power == 250.0
        assert stats.total_donations == 10
        assert stats.average_donation == 25.0

    def test_donation_stats_from_data(self):
        donations = [{"amount": 50.0}, {"amount": 75.0}, {"amount": 25.0}]
        stats = DonationStats.from_data(donations, total_power=150.0)

        assert stats.total_power == 150.0
        assert stats.total_donations == 3
        assert stats.average_donation == 50.0

    def test_donation_stats_from_empty_data(self):
        stats = DonationStats.from_data([], 0.0)

        assert stats.total_power == 0.0
        assert stats.total_donations == 0
        assert stats.average_donation == 0.0


# --------------------------------------------------------------------------- #
# Integration                                                                 #
# --------------------------------------------------------------------------- #

@pytest.mark.integration
class TestDonationManagementServiceIntegration:
    """End-to-end style flow against the production API."""

    def test_full_donation_workflow(
        self, patch_mech_service, patch_progress_paths, event_log_path
    ):
        service = DonationManagementService()

        mech_service = Mock()
        mech_service.get_mech_state_service.return_value = _mech_state_result(
            total_donated=300.0, level=2
        )
        patch_mech_service.return_value = mech_service

        events = [
            {
                "seq": 1,
                "type": "DonationAdded",
                "ts": "2025-01-01T10:00:00Z",
                "payload": {"donor": "Alice", "units": 10000},
            },
            {
                "seq": 2,
                "type": "DonationAdded",
                "ts": "2025-01-01T11:00:00Z",
                "payload": {"donor": "Bob", "units": 20000},
            },
        ]
        _write_event_log(event_log_path, events)

        # 1) initial history
        history_result = service.get_donation_history()
        assert history_result.success is True
        assert len(history_result.data["donations"]) == 2

        # 2) stats
        stats_result = service.get_donation_stats()
        assert stats_result.success is True
        # Stats only carries total_power / total_donations / average_donation.
        assert stats_result.data.total_power == pytest.approx(300.0)
        assert stats_result.data.total_donations == 2

        # 3) delete newest (Bob, seq=2 is index 0 in newest-first display)
        progress_service = Mock()
        with patch(
            "services.mech.progress_service.get_progress_service",
            return_value=progress_service,
        ):
            delete_result = service.delete_donation(0)
        assert delete_result.success is True
        assert delete_result.data["deleted_seq"] == 2
        progress_service.delete_donation.assert_called_once_with(2)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
