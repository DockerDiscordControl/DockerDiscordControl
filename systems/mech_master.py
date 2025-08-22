# -*- coding: utf-8 -*-
"""
Mech Master System - Orchestrates all mech subsystems

This is the main interface for the DDC Mech System. It coordinates:
- Fuel System: Donation processing and fuel management
- Evolution System: Mech tier progression (1-11)
- Speed System: Speed level calculation (Glvl 0-101)
- Animation System: Visual representation creation

Usage Example:
    mech = MechMaster()
    
    # Process donation
    result = mech.add_donation(50.0, "Donor123")
    
    # Get current status
    status = mech.get_complete_status()
    
    # Create animation
    animation = await mech.create_animation("Donor123", "$50")

This provides a clean, single interface to the entire mech system.
"""

from typing import Dict, Any, Optional
import discord
import logging
from utils.logging_utils import get_module_logger

from .fuel_system import FuelSystem, FuelState
from .evolution_system import EvolutionSystem
from .speed_system import SpeedSystem
from .animation_system import AnimationSystem

logger = get_module_logger('mech_master')


class MechMaster:
    """
    Master orchestrator for the entire mech system
    
    This class provides a unified interface to all mech subsystems.
    It ensures proper coordination between fuel, evolution, speed, and animation.
    
    Key Principles:
    - Evolution is based on TOTAL DONATIONS (lifetime achievement)
    - Speed (Glvl) is based on CURRENT FUEL (operational capacity)
    - Animation reflects both evolution level (sprite) and speed (effects)
    """
    
    def __init__(self):
        """Initialize all mech subsystems"""
        self.fuel_system = FuelSystem()
        self.evolution_system = EvolutionSystem()
        self.speed_system = SpeedSystem()
        self.animation_system = AnimationSystem()
        
        logger.info("Mech Master System initialized - all subsystems ready")
    
    # ========================================
    # DONATION PROCESSING
    # ========================================
    
    def add_donation(self, amount: float, donor_name: str = "Anonymous") -> Dict[str, Any]:
        """
        Process a new donation through the complete mech system
        
        Args:
            amount: Donation amount in dollars/euros
            donor_name: Name of the donor
            
        Returns:
            Complete donation processing results with all system updates
        """
        # Process donation through fuel system
        fuel_result = self.fuel_system.add_donation(amount, donor_name)
        
        if not fuel_result['success']:
            return fuel_result
        
        # Get updated states
        current_fuel = self.fuel_system.current_fuel
        total_donations = self.fuel_system.total_donations
        
        # Calculate all derived values
        evolution_level = self.evolution_system.get_evolution_level(total_donations)
        speed_level = self.speed_system.calculate_speed_level(current_fuel, evolution_level)
        
        # Check for evolution upgrade
        old_evolution = self.evolution_system.get_evolution_level(fuel_result['total_before'])
        evolution_upgraded = evolution_level > old_evolution
        
        # Compile complete result
        result = {
            **fuel_result,  # Include all fuel system results
            'evolution': {
                'current_level': evolution_level,
                'upgraded': evolution_upgraded,
                'old_level': old_evolution if evolution_upgraded else None
            },
            'speed': {
                'current_glvl': speed_level,
                'description': self.speed_system.get_speed_description(speed_level)[0]
            },
            'mech_state': {
                'is_operational': speed_level > 0,
                'is_transcendent': speed_level == 101,
                'current_fuel': current_fuel,
                'total_donations': total_donations
            }
        }
        
        logger.info(f"Donation processed: ${amount:.2f} from {donor_name}. "
                   f"Evolution: {evolution_level}, Glvl: {speed_level}, "
                   f"Evolution upgraded: {evolution_upgraded}")
        
        return result
    
    # ========================================
    # COMPREHENSIVE STATUS METHODS
    # ========================================
    
    def get_complete_status(self) -> Dict[str, Any]:
        """
        Get comprehensive status of the entire mech system
        
        Returns:
            Dictionary with complete mech status from all subsystems
        """
        # Get current fuel state
        fuel_state = self.fuel_system.get_fuel_state()
        current_fuel = fuel_state.current_fuel
        total_donations = fuel_state.total_donations
        
        # Get evolution information
        evolution_info = self.evolution_system.get_complete_evolution_info(total_donations)
        evolution_level = evolution_info['current']['level']
        
        # Get speed information
        speed_info = self.speed_system.get_complete_speed_status(current_fuel, evolution_level)
        
        # Combine everything
        return {
            'fuel': {
                'current': current_fuel,
                'total_donations': total_donations,
                'is_operational': self.fuel_system.is_operational(),
                'last_donation': self.fuel_system.last_donation_info
            },
            'evolution': evolution_info,
            'speed': speed_info,
            'summary': {
                'level': evolution_level,
                'name': evolution_info['current']['name'],
                'glvl': speed_info['glvl'],
                'description': speed_info['description'],
                'is_transcendent': speed_info['is_transcendent'],
                'is_max_evolution': evolution_info['is_max_level'],
                'status_text': self._generate_status_text(evolution_info, speed_info)
            }
        }
    
    def _generate_status_text(self, evolution_info: Dict, speed_info: Dict) -> str:
        """Generate human-readable status text"""
        evo_name = evolution_info['current']['name']
        speed_desc = speed_info['description']
        
        if speed_info['is_transcendent']:
            return f"{evo_name} - ⚡ TRANSCENDENT MODE ACTIVATED! ⚡"
        elif speed_info['glvl'] == 0:
            return f"{evo_name} - OFFLINE (No Fuel)"
        else:
            return f"{evo_name} - {speed_desc} (Glvl {speed_info['glvl']})"
    
    # ========================================
    # ANIMATION CREATION
    # ========================================
    
    async def create_animation(self, donor_name: str = "", amount: str = "") -> discord.File:
        """
        Create mech animation based on current state
        
        Args:
            donor_name: Name of donor (for logging)
            amount: Donation amount (for logging)
            
        Returns:
            Discord file with mech animation
        """
        fuel_state = self.fuel_system.get_fuel_state()
        evolution_level = self.evolution_system.get_evolution_level(fuel_state.total_donations)
        speed_level = self.speed_system.calculate_speed_level(fuel_state.current_fuel, evolution_level)
        
        return await self.animation_system.create_mech_animation(
            evolution_level=evolution_level,
            speed_level=speed_level,
            donor_name=donor_name,
            amount=amount
        )
    
    async def create_donation_animation(self, donor_name: str, amount: str, 
                                      total_donations: float) -> discord.File:
        """
        Create animation for a specific donation context
        
        Args:
            donor_name: Name of the donor
            amount: Donation amount string (for display)
            total_donations: Current total donations for evolution calculation
            
        Returns:
            Discord file with mech animation
        """
        # Use total_donations for evolution, but current fuel for speed
        evolution_level = self.evolution_system.get_evolution_level(total_donations)
        current_fuel = self.fuel_system.current_fuel
        speed_level = self.speed_system.calculate_speed_level(current_fuel, evolution_level)
        
        return await self.animation_system.create_mech_animation(
            evolution_level=evolution_level,
            speed_level=speed_level,
            donor_name=donor_name,
            amount=amount
        )
    
    # ========================================
    # SYSTEM UTILITIES AND MANAGEMENT
    # ========================================
    
    def consume_fuel(self, amount: float, reason: str = "Operation") -> bool:
        """
        Consume fuel for mech operations
        
        Args:
            amount: Amount of fuel to consume
            reason: Reason for consumption
            
        Returns:
            True if fuel was consumed successfully
        """
        return self.fuel_system.consume_fuel(amount, reason)
    
    def get_fuel_status(self) -> Dict[str, Any]:
        """Get just the fuel system status"""
        return self.fuel_system.get_fuel_status()
    
    def get_evolution_status(self) -> Dict[str, Any]:
        """Get just the evolution system status"""
        total_donations = self.fuel_system.total_donations
        return self.evolution_system.get_complete_evolution_info(total_donations)
    
    def get_speed_status(self) -> Dict[str, Any]:
        """Get just the speed system status"""
        fuel_state = self.fuel_system.get_fuel_state()
        evolution_level = self.evolution_system.get_evolution_level(fuel_state.total_donations)
        return self.speed_system.get_complete_speed_status(fuel_state.current_fuel, evolution_level)
    
    def is_evolution_maxed(self) -> bool:
        """Check if mech has reached maximum evolution"""
        total_donations = self.fuel_system.total_donations
        evolution_level = self.evolution_system.get_evolution_level(total_donations)
        return evolution_level >= 11  # OMEGA MECH
    
    def is_transcendent_mode(self) -> bool:
        """Check if mech is in TRANSCENDENT mode (Glvl 101)"""
        fuel_state = self.fuel_system.get_fuel_state()
        evolution_level = self.evolution_system.get_evolution_level(fuel_state.total_donations)
        speed_level = self.speed_system.calculate_speed_level(fuel_state.current_fuel, evolution_level)
        return speed_level == 101
    
    def load_state(self, fuel_state: FuelState):
        """Load mech state from external source"""
        self.fuel_system.load_state(fuel_state)
        logger.info("Mech state loaded from external source")
    
    def reset_fuel(self, keep_total_donations: bool = True):
        """Reset current fuel (for testing or special events)"""
        self.fuel_system.reset_fuel(keep_total_donations)
        logger.info(f"Mech fuel reset, total donations {'preserved' if keep_total_donations else 'reset'}")
    
    # ========================================
    # CONVENIENCE METHODS
    # ========================================
    
    def get_quick_status(self) -> str:
        """Get a quick one-line status string"""
        status = self.get_complete_status()
        return status['summary']['status_text']
    
    def format_fuel_display(self, currency: str = "$") -> str:
        """Get formatted fuel display string"""
        current_fuel = self.fuel_system.current_fuel
        return f"{currency}{current_fuel:.2f}"
    
    def format_total_donations_display(self, currency: str = "$") -> str:
        """Get formatted total donations display string"""
        total_donations = self.fuel_system.total_donations
        return f"{currency}{total_donations:.2f}"


# ========================================
# CONVENIENCE FUNCTIONS FOR EXTERNAL USE
# ========================================

# Global instance for easy access (if needed)
_mech_master_instance = None

def get_mech_master() -> MechMaster:
    """Get global MechMaster instance (creates if doesn't exist)"""
    global _mech_master_instance
    if _mech_master_instance is None:
        _mech_master_instance = MechMaster()
    return _mech_master_instance

def reset_mech_master():
    """Reset global MechMaster instance"""
    global _mech_master_instance
    _mech_master_instance = None