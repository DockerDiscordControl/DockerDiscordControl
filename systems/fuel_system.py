# -*- coding: utf-8 -*-
"""
Fuel System - Manages donation amounts and fuel calculations

The fuel system is the foundation of the mech system. It tracks:
- Current fuel level (how much money is available for mech operation)
- Total donations received (lifetime achievement tracking)
- Fuel consumption and management

Fuel is measured in dollars/euros and determines mech operation capability.
"""

from typing import Dict, Any, Optional
from dataclasses import dataclass
import logging
from datetime import datetime, timezone
from utils.logging_utils import get_module_logger

logger = get_module_logger('fuel_system')


@dataclass
class FuelState:
    """Represents the current fuel state of the mech"""
    current_fuel: float = 0.0          # Current available fuel for operation
    total_donations: float = 0.0       # Lifetime total donations received
    last_donation: float = 0.0         # Amount of last donation
    last_donor: str = ""               # Name of last donor
    
    def __post_init__(self):
        """Validate fuel state after initialization"""
        if self.current_fuel < 0:
            self.current_fuel = 0.0
        if self.total_donations < 0:
            self.total_donations = 0.0


class FuelSystem:
    """
    Core fuel management system for the mech
    
    Responsibilities:
    - Track current fuel levels
    - Process new donations
    - Validate fuel amounts
    - Provide fuel status information
    """
    
    def __init__(self):
        """Initialize the fuel system"""
        self._state = FuelState()
        self._donation_manager = None
        logger.info("Fuel system initialized")
    
    def connect_to_donation_manager(self):
        """Connect to persistent donation manager for data storage"""
        try:
            from utils.donation_manager import get_donation_manager
            self._donation_manager = get_donation_manager()
            
            # Load current state from persistent storage
            self._sync_from_persistent_storage()
            logger.info("✅ Connected to donation_manager for persistent storage")
            return True
        except ImportError:
            logger.warning("⚠️ donation_manager not available - using in-memory storage only")
            return False
        except Exception as e:
            logger.error(f"❌ Failed to connect to donation_manager: {e}")
            return False
    
    def _sync_from_persistent_storage(self):
        """Sync current state from persistent donation_manager data"""
        if not self._donation_manager:
            return
            
        try:
            data = self._donation_manager.load_data()
            fuel_data = data.get('fuel_data', {})
            
            # Map donation_manager data to FuelState
            self._state = FuelState(
                current_fuel=fuel_data.get('current_fuel', 0.0),
                total_donations=fuel_data.get('total_received_permanent', 0.0),
                last_donation=0.0,  # Not stored in donation_manager
                last_donor=""       # Not stored in donation_manager
            )
            
            logger.debug(f"Synced from persistent storage: ${self._state.current_fuel:.2f} fuel, "
                        f"${self._state.total_donations:.2f} total donations")
        except Exception as e:
            logger.error(f"Error syncing from persistent storage: {e}")
    
    def _sync_to_persistent_storage(self):
        """Sync current state to persistent donation_manager data"""
        if not self._donation_manager:
            return False
            
        try:
            data = self._donation_manager.load_data()
            
            # Update fuel_data in donation_manager format
            fuel_data = data.get('fuel_data', {})
            fuel_data['current_fuel'] = self._state.current_fuel
            fuel_data['total_received_permanent'] = self._state.total_donations
            fuel_data['last_update'] = datetime.now(timezone.utc).isoformat()
            
            data['fuel_data'] = fuel_data
            data['total_donations'] = self._state.total_donations
            
            success = self._donation_manager.save_data(data, silent=True)
            if success:
                logger.debug(f"Synced to persistent storage: ${self._state.current_fuel:.2f} fuel")
            return success
        except Exception as e:
            logger.error(f"Error syncing to persistent storage: {e}")
            return False
    
    # ========================================
    # FUEL STATE MANAGEMENT
    # ========================================
    
    @property
    def current_fuel(self) -> float:
        """Get current available fuel amount"""
        return self._state.current_fuel
    
    @property
    def total_donations(self) -> float:
        """Get total lifetime donations received"""
        return self._state.total_donations
    
    @property
    def last_donation_info(self) -> Dict[str, Any]:
        """Get information about the last donation"""
        return {
            'amount': self._state.last_donation,
            'donor': self._state.last_donor
        }
    
    def get_fuel_state(self) -> FuelState:
        """Get complete fuel state (immutable copy)"""
        return FuelState(
            current_fuel=self._state.current_fuel,
            total_donations=self._state.total_donations,
            last_donation=self._state.last_donation,
            last_donor=self._state.last_donor
        )
    
    # ========================================
    # DONATION PROCESSING
    # ========================================
    
    def add_donation(self, amount: float, donor_name: str = "Anonymous") -> Dict[str, Any]:
        """
        Process a new donation and add fuel
        
        Args:
            amount: Donation amount in dollars/euros
            donor_name: Name of the donor
            
        Returns:
            Dictionary with donation processing results
        """
        if amount <= 0:
            logger.warning(f"Invalid donation amount: {amount}")
            return {
                'success': False,
                'error': 'Donation amount must be positive',
                'fuel_before': self._state.current_fuel,
                'fuel_after': self._state.current_fuel
            }
        
        # Store previous state
        fuel_before = self._state.current_fuel
        total_before = self._state.total_donations
        
        # Update fuel state
        self._state.current_fuel += amount
        self._state.total_donations += amount
        self._state.last_donation = amount
        self._state.last_donor = donor_name
        
        logger.info(f"Donation processed: ${amount:.2f} from {donor_name}. "
                   f"Fuel: ${fuel_before:.2f} -> ${self._state.current_fuel:.2f}")
        
        # Sync to persistent storage if connected
        self._sync_to_persistent_storage()
        
        return {
            'success': True,
            'amount': amount,
            'donor': donor_name,
            'fuel_before': fuel_before,
            'fuel_after': self._state.current_fuel,
            'total_before': total_before,
            'total_after': self._state.total_donations
        }
    
    def consume_fuel(self, amount: float, reason: str = "Operation") -> bool:
        """
        Consume fuel for mech operations
        
        Args:
            amount: Amount of fuel to consume
            reason: Reason for fuel consumption
            
        Returns:
            True if fuel was consumed, False if insufficient fuel
        """
        if amount <= 0:
            return True  # No fuel needed
            
        if self._state.current_fuel >= amount:
            fuel_before = self._state.current_fuel
            self._state.current_fuel -= amount
            logger.info(f"Fuel consumed: ${amount:.2f} for {reason}. "
                       f"Fuel: ${fuel_before:.2f} -> ${self._state.current_fuel:.2f}")
            
            # Sync to persistent storage if connected
            self._sync_to_persistent_storage()
            return True
        else:
            logger.warning(f"Insufficient fuel for {reason}. "
                          f"Needed: ${amount:.2f}, Available: ${self._state.current_fuel:.2f}")
            return False
    
    # ========================================
    # FUEL STATUS AND VALIDATION
    # ========================================
    
    def is_operational(self) -> bool:
        """Check if mech has fuel to operate"""
        return self._state.current_fuel > 0
    
    def get_fuel_percentage(self, max_fuel: float) -> float:
        """
        Get fuel as percentage of maximum
        
        Args:
            max_fuel: Maximum fuel capacity for current level
            
        Returns:
            Percentage (0-100)
        """
        if max_fuel <= 0:
            return 0.0
        return min(100.0, (self._state.current_fuel / max_fuel) * 100)
    
    def get_fuel_status(self) -> Dict[str, Any]:
        """
        Get comprehensive fuel status information
        
        Returns:
            Dictionary with all fuel status data
        """
        return {
            'current_fuel': self._state.current_fuel,
            'total_donations': self._state.total_donations,
            'is_operational': self.is_operational(),
            'last_donation': {
                'amount': self._state.last_donation,
                'donor': self._state.last_donor
            },
            'fuel_state': 'operational' if self.is_operational() else 'offline'
        }
    
    # ========================================
    # SYSTEM MANAGEMENT
    # ========================================
    
    def reset_fuel(self, keep_total_donations: bool = True):
        """
        Reset current fuel (for testing or special events)
        
        Args:
            keep_total_donations: Whether to preserve total donation history
        """
        fuel_before = self._state.current_fuel
        total_before = self._state.total_donations
        
        self._state.current_fuel = 0.0
        if not keep_total_donations:
            self._state.total_donations = 0.0
            
        logger.info(f"Fuel system reset. Fuel: ${fuel_before:.2f} -> $0.00. "
                   f"Total donations: {'preserved' if keep_total_donations else 'reset'}")
        
        # Sync to persistent storage if connected
        self._sync_to_persistent_storage()
    
    def load_state(self, fuel_state: FuelState):
        """Load fuel state from external source"""
        self._state = FuelState(
            current_fuel=max(0.0, fuel_state.current_fuel),
            total_donations=max(0.0, fuel_state.total_donations),
            last_donation=fuel_state.last_donation,
            last_donor=fuel_state.last_donor
        )
        logger.info(f"Fuel state loaded: ${self._state.current_fuel:.2f} fuel, "
                   f"${self._state.total_donations:.2f} total donations")
        
        # Sync to persistent storage if connected
        self._sync_to_persistent_storage()


# ========================================
# CONVENIENCE FUNCTIONS
# ========================================

def validate_fuel_amount(amount: float) -> bool:
    """Validate if a fuel amount is valid"""
    return isinstance(amount, (int, float)) and amount >= 0

def format_fuel_amount(amount: float, currency: str = "$") -> str:
    """Format fuel amount for display"""
    return f"{currency}{amount:.2f}"