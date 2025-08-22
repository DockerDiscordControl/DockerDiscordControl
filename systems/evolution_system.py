# -*- coding: utf-8 -*-
"""
Evolution System - Manages mech evolution tiers and upgrades

The evolution system determines the mech's visual appearance and capabilities:
- 11 Evolution Levels (1 = SCRAP MECH → 11 = OMEGA MECH)
- Each level requires specific total donation thresholds
- Higher levels unlock better visual effects and capabilities
- Level 11 is a secret ultra-level for true legends

Evolution is based on TOTAL DONATIONS (lifetime achievement), not current fuel.
"""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from enum import IntEnum
import logging
from utils.logging_utils import get_module_logger

logger = get_module_logger('evolution_system')


class EvolutionLevel(IntEnum):
    """Enumeration of all mech evolution levels"""
    SCRAP = 1       # $0 - Barely holding together
    REPAIRED = 2    # $20 - Basic repairs complete
    STANDARD = 3    # $50 - Military-grade chassis
    ENHANCED = 4    # $100 - Reinforced armor
    ADVANCED = 5    # $200 - Advanced targeting
    ELITE = 6       # $400 - Elite combat protocols
    CYBER = 7       # $800 - Cybernetic interface
    PLASMA = 8      # $1500 - Plasma-powered core
    QUANTUM = 9     # $2500 - Quantum entanglement
    DIVINE = 10     # $4000 - Transcendent technology
    OMEGA = 11      # $10000 - Reality-bending war machine (SECRET!)


@dataclass
class EvolutionTier:
    """Complete information about an evolution tier"""
    level: int
    name: str
    description: str
    threshold: float
    color: str
    sprite_filename: str
    
    @property
    def is_secret(self) -> bool:
        """Check if this is a secret evolution level"""
        return self.level >= EvolutionLevel.OMEGA


class EvolutionSystem:
    """
    Core evolution management system for the mech
    
    Responsibilities:
    - Determine current evolution level based on total donations
    - Provide evolution tier information
    - Calculate progress to next evolution
    - Manage evolution thresholds and metadata
    """
    
    # Evolution thresholds in dollars - progressive pattern
    EVOLUTION_THRESHOLDS = {
        EvolutionLevel.SCRAP: 0,        # Starting point
        EvolutionLevel.REPAIRED: 20,    # First upgrade
        EvolutionLevel.STANDARD: 50,    # Standard tier
        EvolutionLevel.ENHANCED: 100,   # Enhanced tier
        EvolutionLevel.ADVANCED: 200,   # Advanced tier
        EvolutionLevel.ELITE: 400,      # Elite tier
        EvolutionLevel.CYBER: 800,      # Cyber tier
        EvolutionLevel.PLASMA: 1500,    # Plasma tier
        EvolutionLevel.QUANTUM: 2500,   # Quantum tier
        EvolutionLevel.DIVINE: 4000,    # Divine tier
        EvolutionLevel.OMEGA: 10000,    # SECRET OMEGA TIER!
    }
    
    EVOLUTION_NAMES = {
        EvolutionLevel.SCRAP: "SCRAP MECH",
        EvolutionLevel.REPAIRED: "REPAIRED MECH",
        EvolutionLevel.STANDARD: "STANDARD MECH",
        EvolutionLevel.ENHANCED: "ENHANCED MECH",
        EvolutionLevel.ADVANCED: "ADVANCED MECH",
        EvolutionLevel.ELITE: "ELITE MECH",
        EvolutionLevel.CYBER: "CYBER MECH",
        EvolutionLevel.PLASMA: "PLASMA MECH",
        EvolutionLevel.QUANTUM: "QUANTUM MECH",
        EvolutionLevel.DIVINE: "DIVINE MECH",
        EvolutionLevel.OMEGA: "OMEGA MECH",  # The legendary final form!
    }
    
    EVOLUTION_DESCRIPTIONS = {
        EvolutionLevel.SCRAP: "Barely holding together with rust and spare parts",
        EvolutionLevel.REPAIRED: "Basic repairs complete, systems barely functional",
        EvolutionLevel.STANDARD: "Standard military-grade combat chassis",
        EvolutionLevel.ENHANCED: "Reinforced armor plating and enhanced servos",
        EvolutionLevel.ADVANCED: "Advanced targeting systems and weapon upgrades",
        EvolutionLevel.ELITE: "Elite combat protocols and titanium armor",
        EvolutionLevel.CYBER: "Cybernetic neural interface and energy shields",
        EvolutionLevel.PLASMA: "Plasma-powered core with quantum processors",
        EvolutionLevel.QUANTUM: "Quantum entanglement drive and phase shifting",
        EvolutionLevel.DIVINE: "Transcendent technology beyond mortal comprehension",
        EvolutionLevel.OMEGA: "Reality-bending omnipotent war machine of the gods",
    }
    
    EVOLUTION_COLORS = {
        EvolutionLevel.SCRAP: "#444444",     # Dark gray
        EvolutionLevel.REPAIRED: "#666666",  # Light gray
        EvolutionLevel.STANDARD: "#888888",  # Steel
        EvolutionLevel.ENHANCED: "#0099cc",  # Blue
        EvolutionLevel.ADVANCED: "#00ccff",  # Cyan
        EvolutionLevel.ELITE: "#ffcc00",     # Gold
        EvolutionLevel.CYBER: "#ff6600",     # Orange
        EvolutionLevel.PLASMA: "#cc00ff",    # Purple
        EvolutionLevel.QUANTUM: "#00ffff",   # Quantum cyan
        EvolutionLevel.DIVINE: "#ffff00",    # Divine gold
        EvolutionLevel.OMEGA: "#ff00ff",     # Omega magenta - Reality itself bends
    }
    
    def __init__(self):
        """Initialize the evolution system"""
        logger.info("Evolution system initialized with 11 tiers")
    
    # ========================================
    # EVOLUTION LEVEL CALCULATION
    # ========================================
    
    def get_evolution_level(self, total_donations: float) -> int:
        """
        Calculate evolution level based on total donations
        
        Args:
            total_donations: Total donation amount in dollars/euros
            
        Returns:
            Evolution level (1-11)
        """
        if total_donations < 0:
            return EvolutionLevel.SCRAP
        
        # Find the highest evolution level the donations qualify for
        for level in range(EvolutionLevel.OMEGA, EvolutionLevel.SCRAP - 1, -1):
            if total_donations >= self.EVOLUTION_THRESHOLDS[level]:
                return level
        
        return EvolutionLevel.SCRAP
    
    def get_evolution_tier(self, total_donations: float) -> EvolutionTier:
        """
        Get complete evolution tier information
        
        Args:
            total_donations: Total donation amount in dollars/euros
            
        Returns:
            EvolutionTier object with complete information
        """
        level = self.get_evolution_level(total_donations)
        
        return EvolutionTier(
            level=level,
            name=self.EVOLUTION_NAMES[level],
            description=self.EVOLUTION_DESCRIPTIONS[level],
            threshold=self.EVOLUTION_THRESHOLDS[level],
            color=self.EVOLUTION_COLORS[level],
            sprite_filename=f"mech_level_{level}.png"
        )
    
    # ========================================
    # EVOLUTION PROGRESS AND NEXT TIER
    # ========================================
    
    def get_next_evolution_info(self, total_donations: float) -> Optional[Dict[str, Any]]:
        """
        Get information about the next evolution tier
        
        Args:
            total_donations: Total donation amount in dollars/euros
            
        Returns:
            Dictionary with next evolution info, or None if max level reached
        """
        current_level = self.get_evolution_level(total_donations)
        
        if current_level >= EvolutionLevel.OMEGA:
            return None  # Max level reached
        
        next_level = current_level + 1
        next_threshold = self.EVOLUTION_THRESHOLDS[next_level]
        amount_needed = next_threshold - total_donations
        
        return {
            'next_level': next_level,
            'next_name': self.EVOLUTION_NAMES[next_level],
            'next_description': self.EVOLUTION_DESCRIPTIONS[next_level],
            'next_threshold': next_threshold,
            'amount_needed': amount_needed,
            'progress_percentage': self.get_evolution_progress(total_donations)
        }
    
    def get_evolution_progress(self, total_donations: float) -> float:
        """
        Calculate progress to next evolution as percentage
        
        Args:
            total_donations: Total donation amount in dollars/euros
            
        Returns:
            Progress percentage (0-100), or 100 if max level reached
        """
        current_level = self.get_evolution_level(total_donations)
        
        if current_level >= EvolutionLevel.OMEGA:
            return 100.0  # Max level reached
        
        current_threshold = self.EVOLUTION_THRESHOLDS[current_level]
        next_threshold = self.EVOLUTION_THRESHOLDS[current_level + 1]
        
        progress_in_tier = total_donations - current_threshold
        tier_range = next_threshold - current_threshold
        
        if tier_range <= 0:
            return 100.0
        
        return min(100.0, (progress_in_tier / tier_range) * 100)
    
    # ========================================
    # EVOLUTION INFORMATION AND UTILITIES
    # ========================================
    
    def get_complete_evolution_info(self, total_donations: float) -> Dict[str, Any]:
        """
        Get comprehensive evolution information
        
        Args:
            total_donations: Total donation amount in dollars/euros
            
        Returns:
            Dictionary with complete evolution status
        """
        current_tier = self.get_evolution_tier(total_donations)
        next_info = self.get_next_evolution_info(total_donations)
        
        return {
            'current': {
                'level': current_tier.level,
                'name': current_tier.name,
                'description': current_tier.description,
                'threshold': current_tier.threshold,
                'color': current_tier.color,
                'is_secret': current_tier.is_secret
            },
            'next': next_info,
            'progress_percentage': self.get_evolution_progress(total_donations),
            'is_max_level': current_tier.level >= EvolutionLevel.OMEGA,
            'total_donations': total_donations
        }
    
    def get_all_evolution_tiers(self, include_secret: bool = False) -> List[EvolutionTier]:
        """
        Get list of all evolution tiers
        
        Args:
            include_secret: Whether to include secret tiers
            
        Returns:
            List of EvolutionTier objects
        """
        tiers = []
        max_level = EvolutionLevel.OMEGA if include_secret else EvolutionLevel.DIVINE
        
        for level in range(EvolutionLevel.SCRAP, max_level + 1):
            tier = EvolutionTier(
                level=level,
                name=self.EVOLUTION_NAMES[level],
                description=self.EVOLUTION_DESCRIPTIONS[level],
                threshold=self.EVOLUTION_THRESHOLDS[level],
                color=self.EVOLUTION_COLORS[level],
                sprite_filename=f"mech_level_{level}.png"
            )
            tiers.append(tier)
        
        return tiers
    
    def is_evolution_upgrade(self, old_donations: float, new_donations: float) -> bool:
        """
        Check if new donation amount triggers an evolution upgrade
        
        Args:
            old_donations: Previous total donations
            new_donations: New total donations
            
        Returns:
            True if evolution level increased
        """
        old_level = self.get_evolution_level(old_donations)
        new_level = self.get_evolution_level(new_donations)
        return new_level > old_level
    
    def get_sprite_filename(self, evolution_level: int) -> str:
        """
        Get sprite filename for specific evolution level
        
        Args:
            evolution_level: Evolution level (1-11)
            
        Returns:
            Filename for the spritesheet
        """
        return f"mech_level_{evolution_level}.png"


# ========================================
# CONVENIENCE FUNCTIONS
# ========================================

def format_evolution_name(level: int, name: str) -> str:
    """Format evolution name for display"""
    return f"Level {level} - {name}"

def get_evolution_emoji(level: int) -> str:
    """Get emoji representation for evolution level"""
    emoji_map = {
        1: "🔩", 2: "🔧", 3: "⚙️", 4: "🛡️", 5: "🎯",
        6: "👑", 7: "🤖", 8: "⚡", 9: "🌌", 10: "✨", 11: "🌟"
    }
    return emoji_map.get(level, "🤖")