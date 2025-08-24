# -*- coding: utf-8 -*-
"""
Adapter for new MechService to provide backwards compatibility with existing code
"""

import logging
from typing import Dict, Any, Optional
from services.mech_service import get_mech_service, MechState
from utils.logging_utils import get_module_logger

logger = get_module_logger('mech_service_adapter')

class MechServiceAdapter:
    """Adapter to make new MechService compatible with existing donation_manager API"""
    
    def __init__(self):
        self.mech_service = get_mech_service()
    
    def get_status(self) -> Dict[str, Any]:
        """Get current status in old format for backwards compatibility"""
        try:
            state: MechState = self.mech_service.get_state()
            
            # Convert to old format
            status = {
                'total_amount': float(state.fuel),  # current fuel
                'total_donations_received': float(state.total_donated),  # total donations ever
                'speed': {
                    'level': state.glvl,
                    'description': f"Glvl {state.glvl}",
                    'emoji': "⚡",
                    'color': "#00ff00",
                    'formatted_status': f"Glvl {state.glvl}"
                },
                # Extra data for new features
                'mech_level': state.level,
                'mech_level_name': state.level_name,
                'next_level_threshold': state.next_level_threshold,
                'fuel_bar': {
                    'current': state.bars.fuel_current,
                    'max': state.bars.fuel_max_for_level
                },
                'evolution_bar': {
                    'current': state.bars.mech_progress_current, 
                    'max': state.bars.mech_progress_max
                }
            }
            
            logger.debug(f"Converted MechState to old format: fuel={state.fuel}, total={state.total_donated}")
            return status
            
        except Exception as e:
            logger.error(f"Error getting status from new MechService: {e}")
            # Fallback to safe defaults
            return {
                'total_amount': 0.0,
                'total_donations_received': 0.0,
                'speed': {'level': 0, 'description': 'Offline', 'emoji': '⚠️', 'color': '#ff0000'},
                'mech_level': 1,
                'mech_level_name': 'SCRAP MECH',
                'next_level_threshold': 20
            }
    
    def record_donation(self, donation_type: str, user_identifier: Optional[str] = None, amount: Optional[float] = None) -> Dict[str, Any]:
        """Record a donation using the new service"""
        try:
            if amount and amount > 0:
                username = user_identifier or "Anonymous"
                logger.info(f"Recording donation: {username} -> ${amount:.2f}")
                
                # Use new service
                state: MechState = self.mech_service.add_donation(username, int(amount))
                
                # Convert back to old format
                result = {
                    '_evolution_level_up': False,  # TODO: Detect evolution 
                    'total_amount': float(state.fuel),
                    'total_donations_received': float(state.total_donated)
                }
                
                logger.info(f"Donation recorded: new fuel={state.fuel}, total_donations={state.total_donated}")
                return result
            else:
                # No amount - just return current status
                return self.get_status()
                
        except Exception as e:
            logger.error(f"Error recording donation: {e}")
            return self.get_status()


# Singleton instance
_adapter_instance: Optional[MechServiceAdapter] = None

def get_mech_service_adapter() -> MechServiceAdapter:
    """Get or create the singleton adapter instance"""
    global _adapter_instance
    if _adapter_instance is None:
        _adapter_instance = MechServiceAdapter()
    return _adapter_instance