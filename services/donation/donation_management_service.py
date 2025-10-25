# -*- coding: utf-8 -*-
"""
Donation Management Service - Clean service architecture for donation administration
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from utils.logging_utils import get_module_logger

logger = get_module_logger('donation_management_service')

@dataclass(frozen=True)
class ServiceResult:
    """Standard service result wrapper."""
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None

@dataclass(frozen=True)
class DonationStats:
    """Immutable donation statistics data structure."""
    total_power: float
    total_donations: int
    average_donation: float
    
    @classmethod
    def from_data(cls, donations: List[Dict[str, Any]], total_power: float) -> 'DonationStats':
        """Create DonationStats from donation data."""
        total_donations = len(donations)
        average_donation = total_power / total_donations if total_donations > 0 else 0.0
        
        return cls(
            total_power=total_power,
            total_donations=total_donations,
            average_donation=average_donation
        )

class DonationManagementService:
    """Clean service for managing donation administration with proper separation of concerns."""
    
    def __init__(self):
        """Initialize the donation management service."""
        logger.info("Donation management service initialized")
    
    def get_donation_history(self, limit: int = 100) -> ServiceResult:
        """Get donation history with statistics using MechService.
        
        Args:
            limit: Maximum number of donations to return
            
        Returns:
            ServiceResult with donation data and stats
        """
        try:
            from services.mech.mech_service import get_mech_service, GetMechStateRequest
            mech_service = get_mech_service()

            # SERVICE FIRST: Get mech state with donation data
            mech_state_request = GetMechStateRequest(include_decimals=False)
            mech_state_result = mech_service.get_mech_state_service(mech_state_request)
            if not mech_state_result.success:
                return DonationListResult(
                    success=False,
                    error="Failed to get mech state",
                    donations=[]
                )

            # Create compatibility object for existing code
            class MechStateCompat:
                def __init__(self, result):
                    self.total_donated = result.total_donated
                    self.level = result.level
            mech_state = MechStateCompat(mech_state_result)

            # Get raw donations from mech service store
            # Use SERVICE FIRST compatibility layer for store access
            from services.mech.mech_compatibility_service import get_mech_compatibility_service
            compat_service = get_mech_compatibility_service()
            store_data = compat_service.get_store_data()
            raw_donations = store_data.get('donations', [])
            
            # Convert to format expected by frontend (limit results)
            donations = []
            for i, donation in enumerate(reversed(raw_donations[-limit:])):  # Get latest donations first
                donations.append({
                    'donor_name': donation.get('username', 'Anonymous'),
                    'amount': donation.get('amount', 0.0),
                    'timestamp': donation.get('ts', ''),
                    'donation_type': 'mech_system'
                })
            
            # Calculate correct stats using MechService data
            total_donated = mech_state.total_donated
            total_count = len(raw_donations)
            
            # Create stats with correct calculations
            stats = DonationStats.from_data(donations, total_donated)
            # Override with correct total count from all donations
            stats = DonationStats(
                total_power=total_donated,
                total_donations=total_count,
                average_donation=total_donated / total_count if total_count > 0 else 0.0
            )
            
            result_data = {
                'donations': donations,
                'stats': stats
            }
            
            logger.debug(f"Retrieved {len(donations)} donations from MechService with total donated: ${total_donated:.2f}")
            return ServiceResult(success=True, data=result_data)
            
        except Exception as e:
            error_msg = f"Error retrieving donation history from MechService: {e}"
            logger.error(error_msg, exc_info=True)
            return ServiceResult(success=False, error=error_msg)
    
    def delete_donation(self, index: int) -> ServiceResult:
        """Delete a donation by index using Unified Donation Service.

        Args:
            index: Index of donation to delete (0-based, from latest to oldest)

        Returns:
            ServiceResult with deletion details
        """
        try:
            # UNIFIED DONATION SERVICE: Clean deletion with automatic events
            from services.donation.unified_donation_service import get_unified_donation_service, DonationDeletionRequest

            # Get current donations to validate index and convert display order to storage order
            from services.mech.mech_compatibility_service import get_mech_compatibility_service
            compat_service = get_mech_compatibility_service()
            store_data = compat_service.get_store_data()
            raw_donations = store_data.get('donations', [])

            # Convert index (we display newest first, but store is oldest first)
            total_donations = len(raw_donations)
            if not (0 <= index < total_donations):
                error_msg = f"Invalid donation index: {index}"
                logger.warning(error_msg)
                return ServiceResult(success=False, error=error_msg)

            # Convert display index to storage index
            storage_index = total_donations - 1 - index

            # Use unified service for deletion with automatic events
            unified_service = get_unified_donation_service()
            deletion_request = DonationDeletionRequest(
                donation_index=storage_index,
                source='web_ui_admin'
            )

            deletion_result = unified_service.delete_donation(deletion_request)

            if not deletion_result.success:
                return ServiceResult(success=False, error=deletion_result.error_message)

            # Extract donation info for response
            deleted_donation = deletion_result.deleted_donation
            donor_name = deleted_donation.get('username', 'Anonymous')
            amount = deleted_donation.get('amount', 0.0)

            logger.info(f"Donation deleted via unified service: {donor_name} - ${amount:.2f}")

            # Return success with donation details (Web UI compatible format)
            result_data = {
                'donor_name': donor_name,  # Web UI expects this
                'amount': amount,          # Web UI expects this
                'deleted_donation': deleted_donation,
                'remaining_count': total_donations - 1,
                'new_state': {
                    'level': deletion_result.new_state.level,
                    'power': float(deletion_result.new_state.Power)
                },
                'index': index  # For backwards compatibility
            }

            return ServiceResult(success=True, data=result_data)
                
        except Exception as e:
            error_msg = f"Error deleting donation from MechService: {e}"
            logger.error(error_msg, exc_info=True)
            return ServiceResult(success=False, error=error_msg)
    
    def get_donation_stats(self) -> ServiceResult:
        """Get donation statistics only using MechService.
        
        Returns:
            ServiceResult with DonationStats
        """
        try:
            from services.mech.mech_service import get_mech_service, GetMechStateRequest
            mech_service = get_mech_service()

            # SERVICE FIRST: Get mech state and raw donations
            mech_state_request = GetMechStateRequest(include_decimals=False)
            mech_state_result = mech_service.get_mech_state_service(mech_state_request)
            if not mech_state_result.success:
                return DonationStatsResult(
                    success=False,
                    error="Failed to get mech state",
                    stats=None
                )

            # Use SERVICE FIRST compatibility layer for store access
            from services.mech.mech_compatibility_service import get_mech_compatibility_service
            compat_service = get_mech_compatibility_service()
            store_data = compat_service.get_store_data()
            raw_donations = store_data.get('donations', [])

            # Calculate stats using MechService data
            total_donated = mech_state_result.total_donated
            total_count = len(raw_donations)
            
            stats = DonationStats(
                total_power=total_donated,
                total_donations=total_count,
                average_donation=total_donated / total_count if total_count > 0 else 0.0
            )
            
            logger.debug(f"Generated MechService donation stats: {stats}")
            return ServiceResult(success=True, data=stats)
            
        except Exception as e:
            error_msg = f"Error getting donation stats from MechService: {e}"
            logger.error(error_msg, exc_info=True)
            return ServiceResult(success=False, error=error_msg)

# Singleton instance
_donation_management_service = None

def get_donation_management_service() -> DonationManagementService:
    """Get the global donation management service instance.
    
    Returns:
        DonationManagementService instance
    """
    global _donation_management_service
    if _donation_management_service is None:
        _donation_management_service = DonationManagementService()
    return _donation_management_service