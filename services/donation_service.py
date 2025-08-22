# -*- coding: utf-8 -*-
"""
Donation Service - Centralized service for all donation-related functionality
"""

import sys
import os
import logging
from typing import Optional, Dict, Any, List

# Ensure proper imports
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from utils.donation_manager import get_donation_manager
from utils.speed_levels import get_speed_info, get_speed_emoji
from utils.logging_utils import get_module_logger

logger = get_module_logger('donation_service')

class DonationService:
    """Centralized service for donation functionality"""
    
    def __init__(self):
        self.donation_manager = get_donation_manager()
        
    def get_status(self) -> Dict[str, Any]:
        """Get complete donation status including speed info"""
        try:
            status = self.donation_manager.get_status()
            total_amount = status.get('total_amount', 0)
            
            # Add speed information
            description, color = get_speed_info(total_amount)
            level = min(int(total_amount / 10), 101) if total_amount > 0 else 0
            emoji = get_speed_emoji(level)
            
            # Enhanced status with speed info
            enhanced_status = {
                **status,
                'speed': {
                    'level': level,
                    'description': description,
                    'emoji': emoji,
                    'color': color,
                    'formatted_status': description  # No emoji needed
                }
            }
            
            return enhanced_status
            
        except Exception as e:
            logger.error(f"Error getting donation status: {e}")
            return {
                'total_amount': 0,
                'donation_count': 0,
                'last_donation': None,
                'speed': {
                    'level': 0,
                    'description': 'OFFLINE',
                    'emoji': '🔴',
                    'color': '#888888',
                    'formatted_status': '🔴 OFFLINE'
                }
            }
    
    def add_fuel(self, amount: float, donation_type: str = "manual", user_identifier: Optional[str] = None) -> Dict[str, Any]:
        """Add fuel and return updated status"""
        try:
            result = self.donation_manager.add_fuel(amount, donation_type, user_identifier)
            logger.info(f"Added {amount}$ fuel, new total: {result.get('new_fuel', 0)}")
            return result
            
        except Exception as e:
            logger.error(f"Error adding fuel: {e}")
            return {'success': False, 'error': str(e)}
    
    def consume_fuel(self, amount: float = 0.00003472) -> Dict[str, Any]:
        """Consume fuel (default is $0.00003472 for 3-second intervals = $1/day)"""
        try:
            result = self.donation_manager.add_fuel(-amount, 'consumption', 'Automatic')
            return result
            
        except Exception as e:
            logger.error(f"Error consuming fuel: {e}")
            return {'success': False, 'error': str(e)}
    
    def reset_fuel(self) -> Dict[str, Any]:
        """Reset fuel to zero"""
        try:
            result = self.donation_manager.reset_donations()
            logger.info("Fuel reset to $0")
            return {'success': True, 'message': 'Fuel reset to $0'}
            
        except Exception as e:
            logger.error(f"Error resetting fuel: {e}")
            return {'success': False, 'error': str(e)}

# Singleton instance
_donation_service = None

def get_donation_service() -> DonationService:
    """Get or create the singleton donation service"""
    global _donation_service
    if _donation_service is None:
        _donation_service = DonationService()
    return _donation_service