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
            store_data = mech_service.store.load()
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
        """Delete a donation by index using MechService.
        
        Args:
            index: Index of donation to delete (0-based, from latest to oldest)
            
        Returns:
            ServiceResult with deletion details
        """
        try:
            from services.mech.mech_service import get_mech_service
            mech_service = get_mech_service()
            
            # Get raw donations from mech service store
            store_data = mech_service.store.load()
            raw_donations = store_data.get('donations', [])
            
            # Convert index (we display newest first, but store is oldest first)
            total_donations = len(raw_donations)
            if not (0 <= index < total_donations):
                error_msg = f"Invalid donation index: {index}"
                logger.warning(error_msg)
                return ServiceResult(success=False, error=error_msg)
            
            # Get the actual index in the stored array (reverse order)
            actual_index = total_donations - 1 - index
            
            # Get donation info before deletion
            donation = raw_donations[actual_index]
            donor_name = donation.get('username', 'Anonymous')
            amount = donation.get('amount', 0.0)
            
            # Delete the donation from the store
            raw_donations.pop(actual_index)
            
            # Save updated data back to store
            updated_data = store_data.copy()
            updated_data['donations'] = raw_donations
            mech_service.store.save(updated_data)
            
            logger.info(f"MechService donation deleted: {donor_name} - ${amount:.2f}")
            
            result_data = {
                'donor_name': donor_name,
                'amount': amount,
                'index': index
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

            store_data = mech_service.store.load()
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