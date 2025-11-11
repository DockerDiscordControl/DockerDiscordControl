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

            # Get donations AND deletions directly from Progress Service Event Log
            import json
            from pathlib import Path

            all_events = []
            event_log = Path("config/progress/events.jsonl")

            if event_log.exists():
                with open(event_log, 'r', encoding='utf-8') as f:
                    for line in f:
                        if not line.strip():
                            continue
                        event = json.loads(line)
                        # Include ALL donation types for transparency
                        if event.get('type') in ['DonationAdded', 'DonationDeleted', 'PowerGiftGranted', 'SystemDonationAdded', 'ExactHitBonusGranted']:
                            all_events.append(event)

            # Build nested structure: Donations with their deletion events
            donations_map = {}  # seq -> donation data
            deletions_map = {}  # deleted_seq -> deletion event

            for event in all_events:
                event_type = event.get('type')

                if event_type == 'DonationAdded':
                    seq = event.get('seq')
                    payload = event.get('payload', {})
                    donations_map[seq] = {
                        'seq': seq,
                        'donor_name': payload.get('donor', 'Anonymous'),
                        'amount': payload.get('units', 0) / 100.0,  # cents → dollars
                        'timestamp': event.get('ts', ''),
                        'donation_type': 'manual',
                        'is_deleted': False,
                        'deletion_events': []  # List of deletion events for this donation
                    }
                elif event_type == 'PowerGiftGranted':
                    seq = event.get('seq')
                    payload = event.get('payload', {})
                    campaign = payload.get('campaign_id', '')
                    # Show appropriate name based on campaign
                    if 'startup' in campaign.lower():
                        gift_name = '🎁 Welcome Gift'
                    else:
                        gift_name = '🎁 Power Gift'
                    donations_map[seq] = {
                        'seq': seq,
                        'donor_name': gift_name,
                        'amount': payload.get('power_units', 0) / 100.0,  # cents → dollars
                        'timestamp': event.get('ts', ''),
                        'donation_type': 'power_gift',
                        'is_deleted': False,
                        'deletion_events': []
                    }
                elif event_type == 'SystemDonationAdded':
                    seq = event.get('seq')
                    payload = event.get('payload', {})
                    donations_map[seq] = {
                        'seq': seq,
                        'donor_name': f"🤖 {payload.get('event_name', 'System Event')}",
                        'amount': payload.get('power_units', 0) / 100.0,  # cents → dollars
                        'timestamp': event.get('ts', ''),
                        'donation_type': 'system',
                        'is_deleted': False,
                        'deletion_events': []
                    }
                elif event_type == 'ExactHitBonusGranted':
                    seq = event.get('seq')
                    payload = event.get('payload', {})
                    from_level = payload.get('from_level', '?')
                    to_level = payload.get('to_level', '?')
                    donations_map[seq] = {
                        'seq': seq,
                        'donor_name': f"🎯 Exact Hit Bonus (Level {from_level} → {to_level})",
                        'amount': payload.get('power_units', 0) / 100.0,  # cents → dollars
                        'timestamp': event.get('ts', ''),
                        'donation_type': 'exact_hit_bonus',
                        'is_deleted': False,
                        'deletion_events': []
                    }
                elif event.get('type') == 'DonationDeleted':
                    deleted_seq = event.get('payload', {}).get('deleted_seq')
                    if deleted_seq:
                        deletion_event = {
                            'seq': event.get('seq'),
                            'deleted_seq': deleted_seq,
                            'donor_name': event.get('payload', {}).get('donor', 'Unknown'),
                            'amount': event.get('payload', {}).get('units', 0) / 100.0,
                            'timestamp': event.get('ts', ''),
                            'reason': event.get('payload', {}).get('reason', 'admin_deletion'),
                            'donation_type': 'deletion',
                            'is_deletion': True
                        }
                        # Track deletion by deleted_seq
                        if deleted_seq not in deletions_map:
                            deletions_map[deleted_seq] = []
                        deletions_map[deleted_seq].append(deletion_event)

            # Mark deleted donations and attach deletion events
            for deleted_seq, deletion_events in deletions_map.items():
                if deleted_seq in donations_map:
                    donations_map[deleted_seq]['is_deleted'] = True
                    donations_map[deleted_seq]['deletion_events'] = deletion_events

            # Convert to flat list for display (newest first, with nested deletions)
            donations = []
            for seq in reversed(sorted(donations_map.keys())):  # Newest first
                donation = donations_map[seq]
                donations.append(donation)
                # Add deletion events right after the donation (indented)
                for deletion in donation['deletion_events']:
                    donations.append(deletion)

            # Calculate total power from ALL events (including PowerGift, ExactHitBonus, etc.)
            total_power = 0.0
            for donation in donations_map.values():
                if not donation.get('is_deleted', False):
                    total_power += donation['amount']

            total_count = len(donations_map)  # Only count actual donations, not deletions

            # Create stats with power calculated from ALL donation types
            stats = DonationStats(
                total_power=total_power,
                total_donations=total_count,
                average_donation=total_power / total_count if total_count > 0 else 0.0
            )
            
            result_data = {
                'donations': donations,
                'stats': stats
            }

            logger.debug(f"Retrieved {len(donations)} donations with total power: ${total_power:.2f}")
            return ServiceResult(success=True, data=result_data)
            
        except Exception as e:
            error_msg = f"Error retrieving donation history from MechService: {e}"
            logger.error(error_msg, exc_info=True)
            return ServiceResult(success=False, error=error_msg)
    
    def delete_donation(self, index: int) -> ServiceResult:
        """
        Delete a donation OR restore a deleted donation using Event Sourcing compensation events.

        This is EVENT SOURCING COMPLIANT:
        - For DonationAdded: Adds a DonationDeleted event (marks donation as deleted)
        - For DonationDeleted: Adds another DonationDeleted event (restores original donation!)
        - Rebuilds snapshot from scratch, applying all active events
        - All level-ups and costs recalculate correctly

        Args:
            index: The index in the DISPLAY list (includes both donations and deletions, 0-based, newest first)

        Returns:
            ServiceResult with success status
        """
        try:
            # Get ALL events from event log (same logic as list_donations to get matching indices)
            import json
            from pathlib import Path

            all_events = []
            event_log = Path("config/progress/events.jsonl")

            if not event_log.exists():
                return ServiceResult(success=False, error="Event log not found")

            with open(event_log, 'r', encoding='utf-8') as f:
                for line in f:
                    if not line.strip():
                        continue
                    event = json.loads(line)
                    if event.get('type') in ['DonationAdded', 'DonationDeleted']:
                        all_events.append(event)

            # Build the same nested structure as list_donations
            donations_map = {}
            deletions_map = {}

            for event in all_events:
                if event.get('type') == 'DonationAdded':
                    seq = event.get('seq')
                    donations_map[seq] = {
                        'seq': seq,
                        'type': 'DonationAdded',
                        'deletion_events': []
                    }
                elif event.get('type') == 'DonationDeleted':
                    deleted_seq = event.get('payload', {}).get('deleted_seq')
                    if deleted_seq:
                        deletion_event = {
                            'seq': event.get('seq'),
                            'deleted_seq': deleted_seq,
                            'type': 'DonationDeleted'
                        }
                        if deleted_seq not in deletions_map:
                            deletions_map[deleted_seq] = []
                        deletions_map[deleted_seq].append(deletion_event)

            # Attach deletion events to donations
            for deleted_seq, deletion_events in deletions_map.items():
                if deleted_seq in donations_map:
                    donations_map[deleted_seq]['deletion_events'] = deletion_events

            # Build flat display list (same as UI)
            display_list = []
            for seq in reversed(sorted(donations_map.keys())):
                display_list.append(donations_map[seq])
                for deletion in donations_map[seq]['deletion_events']:
                    display_list.append(deletion)

            # Check if index is valid
            if index < 0 or index >= len(display_list):
                return ServiceResult(success=False, error=f"Invalid index: {index}")

            item = display_list[index]
            item_seq = item['seq']
            item_type = item['type']

            # Call progress service to delete
            from services.mech.progress_service import get_progress_service
            progress_service = get_progress_service()

            # Delete event (adds compensation event and rebuilds)
            progress_service.delete_donation(item_seq)

            action = "Deleted" if item_type == 'DonationAdded' else "Restored"
            logger.info(f"{action} event at index {index} (seq {item_seq}, type {item_type})")

            return ServiceResult(
                success=True,
                data={
                    'deleted_seq': item_seq,
                    'action': action,
                    'type': item_type
                }
            )

        except ValueError as e:
            error_msg = str(e)
            logger.error(f"Validation error deleting donation: {error_msg}")
            return ServiceResult(success=False, error=error_msg)
        except Exception as e:
            error_msg = f"Error deleting donation: {e}"
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

            # Get ALL donations directly from Progress Service Event Log
            import json
            from pathlib import Path

            donations_map = {}
            deletions_map = {}
            event_log = Path("config/progress/events.jsonl")

            if event_log.exists():
                with open(event_log, 'r', encoding='utf-8') as f:
                    for line in f:
                        if not line.strip():
                            continue
                        event = json.loads(line)
                        event_type = event.get('type')

                        # Include ALL donation types
                        if event_type in ['DonationAdded', 'PowerGiftGranted', 'SystemDonationAdded', 'ExactHitBonusGranted']:
                            seq = event.get('seq')
                            payload = event.get('payload', {})
                            amount_key = 'units' if event_type == 'DonationAdded' else 'power_units'
                            donations_map[seq] = {
                                'amount': payload.get(amount_key, 0) / 100.0,
                                'is_deleted': False
                            }
                        elif event_type == 'DonationDeleted':
                            deleted_seq = event.get('payload', {}).get('deleted_seq')
                            if deleted_seq:
                                deletions_map[deleted_seq] = True

            # Mark deleted donations
            for deleted_seq in deletions_map:
                if deleted_seq in donations_map:
                    donations_map[deleted_seq]['is_deleted'] = True

            # Calculate total power from ALL event types (excluding deleted)
            total_power = sum(d['amount'] for d in donations_map.values() if not d['is_deleted'])
            total_count = sum(1 for d in donations_map.values() if not d['is_deleted'])

            stats = DonationStats(
                total_power=total_power,
                total_donations=total_count,
                average_donation=total_power / total_count if total_count > 0 else 0.0
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