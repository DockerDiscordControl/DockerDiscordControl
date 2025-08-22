# -*- coding: utf-8 -*-
"""
Speed System (Glvl) - Calculates speed levels based on fuel and evolution

The speed system determines how fast the mech operates based on:
- Current fuel amount (not total donations!)
- Current evolution level (affects how fuel translates to speed)
- Special speed calculation rules per evolution tier

Speed Levels (Glvl) range from 0-101:
- 0 = OFFLINE (no fuel)
- 1-100 = Normal operation speeds
- 101 = TRANSCENDENT (OMEGA MECH at max fuel only!)

Different evolution levels use different fuel-to-speed formulas:
- Levels 1-4: Direct 1:1 mapping (1$ = 1 Glvl, max 100)
- Levels 5-10: Dynamic scaling within evolution tier range
- Level 11: Special OMEGA calculation with Glvl 101 possibility
"""

from typing import Dict, Any, Tuple
from dataclasses import dataclass
import logging
from utils.logging_utils import get_module_logger

logger = get_module_logger('speed_system')


@dataclass
class SpeedLevel:
    """Represents a speed level with its properties"""
    glvl: int                    # Speed level (0-101)
    description: str             # Human-readable description
    color: str                   # Color code for UI
    is_transcendent: bool = False  # Special flag for Glvl 101
    
    @property
    def is_operational(self) -> bool:
        """Check if mech is operational at this speed"""
        return self.glvl > 0


class SpeedSystem:
    """
    Core speed calculation system for the mech
    
    Responsibilities:
    - Calculate speed level (Glvl) based on fuel and evolution
    - Provide speed descriptions and visual properties
    - Handle special cases (TRANSCENDENT mode, offline state)
    - Manage speed-related animations and effects
    """
    
    # Speed descriptions for each Glvl (0-101)
    SPEED_DESCRIPTIONS = {
        0: ("OFFLINE", "#888888"),
        1: ("Motionless", "#4a4a4a"),
        2: ("Barely perceptible", "#525252"),
        3: ("Extremely sluggish", "#5a5a5a"),
        4: ("Painfully hesitant", "#626262"),
        5: ("Excruciatingly lethargic", "#6a6a6a"),
        6: ("Ultra-slow", "#727272"),
        7: ("Almost crawling", "#7a7a7a"),
        8: ("Truly crawling", "#828282"),
        9: ("Snail-paced", "#8a8a8a"),
        10: ("Glacially slow", "#929292"),
        11: ("Heavy-footed", "#9a9a9a"),
        12: ("Weary plodding", "#a2a2a2"),
        13: ("Drearily trudging", "#aaaaaa"),
        14: ("Stumbling forward", "#b2b2b2"),
        15: ("Faltering pace", "#bababa"),
        16: ("Limping along", "#c2c2c2"),
        17: ("Dragging feet", "#cacaca"),
        18: ("Reluctant stride", "#d2d2d2"),
        19: ("Sluggish shuffling", "#dadada"),
        20: ("Slow but continuous", "#e2e2e2"),
        21: ("Leisurely relaxed", "#cc6600"),
        22: ("Casual and easy", "#cc7700"),
        23: ("Moderately steady", "#cc8800"),
        24: ("Comfortable stride", "#cc9900"),
        25: ("Measured walking", "#ccaa00"),
        26: ("Balanced and even", "#ccbb00"),
        27: ("Mildly brisk", "#bbcc00"),
        28: ("Purposeful steady", "#aacc00"),
        29: ("Clearly brisker", "#99cc00"),
        30: ("Decisive stride", "#88cc00"),
        31: ("Quickened step", "#77cc00"),
        32: ("Energetic pace", "#66cc00"),
        33: ("Noticeably brisk", "#55cc00"),
        34: ("Sharply focused", "#44cc00"),
        35: ("Fast stride", "#33cc00"),
        36: ("Strong and firm", "#22cc00"),
        37: ("Forcefully brisk", "#11cc00"),
        38: ("Rapid walking", "#00cc00"),
        39: ("Swift step", "#00cc11"),
        40: ("Quick-paced", "#00cc22"),
        41: ("Very brisk", "#00cc33"),
        42: ("Clearly fast", "#00cc44"),
        43: ("Forcefully rapid", "#00cc55"),
        44: ("Rushing forward", "#00cc66"),
        45: ("Hurrying intensely", "#00cc77"),
        46: ("Lively fast", "#00cc88"),
        47: ("Speedy motion", "#00cc99"),
        48: ("Snappy fast", "#00ccaa"),
        49: ("Nimble quick", "#00ccbb"),
        50: ("Sharply swift", "#00cccc"),
        51: ("Fast and urgent", "#00bbcc"),
        52: ("Highly accelerated", "#00aacc"),
        53: ("Energetically quick", "#0099cc"),
        54: ("Spirited dash", "#0088cc"),
        55: ("Racing step", "#0077cc"),
        56: ("Storming forward", "#0066cc"),
        57: ("Rapidly urgent", "#0055cc"),
        58: ("Extremely swift", "#0044cc"),
        59: ("Desperately fast", "#0033cc"),
        60: ("Almost running", "#0022cc"),
        61: ("Slow jogging", "#0011cc"),
        62: ("Light jogging", "#0000cc"),
        63: ("Steady jogging", "#1100cc"),
        64: ("Quick jogging", "#2200cc"),
        65: ("Fast jogging", "#3300cc"),
        66: ("Easy running", "#4400cc"),
        67: ("Moderate running", "#5500cc"),
        68: ("Strong running", "#6600cc"),
        69: ("Swift running", "#7700cc"),
        70: ("Rapid running", "#8800cc"),
        71: ("Intense running", "#9900cc"),
        72: ("Very fast running", "#aa00cc"),
        73: ("Furious running", "#bb00cc"),
        74: ("Blazing sprint", "#cc00cc"),
        75: ("Relentless sprint", "#cc00bb"),
        76: ("Explosive sprint", "#cc00aa"),
        77: ("Overpowering sprint", "#cc0099"),
        78: ("Jet-fast sprint", "#cc0088"),
        79: ("Blisteringly fast", "#cc0077"),
        80: ("Supersonic pace", "#cc0066"),
        81: ("Hypersonic burst", "#cc0055"),
        82: ("Blazing meteor-fast", "#cc0044"),
        83: ("Comet-like rushing", "#cc0033"),
        84: ("Blindingly swift", "#cc0022"),
        85: ("Breakneck velocity", "#cc0011"),
        86: ("Rocket-speed", "#cc0000"),
        87: ("Stellar velocity", "#ff0000"),
        88: ("Asteroid-surge", "#ff1100"),
        89: ("Planet-crossing speed", "#ff2200"),
        90: ("Star-chasing speed", "#ff3300"),
        91: ("Relativistic rush", "#ff4400"),
        92: ("Near-photonic speed", "#ff5500"),
        93: ("Photon-paced", "#ff6600"),
        94: ("Warp-level 1", "#ff7700"),
        95: ("Warp-level 5", "#ff8800"),
        96: ("Warp-level 9", "#ff9900"),
        97: ("Transwarp surge", "#ffaa00"),
        98: ("Nearly lightspeed", "#ffbb00"),
        99: ("True lightspeed", "#ffcc00"),
        100: ("Beyond-lightspeed", "#ffdd00"),
        101: ("REALITY-BENDING OMNISPEED", "#ff00ff")  # OMEGA MECH TRANSCENDENT!
    }
    
    def __init__(self):
        """Initialize the speed system"""
        logger.info("Speed system initialized with Glvl 0-101 range")
    
    # ========================================
    # SPEED LEVEL CALCULATION
    # ========================================
    
    def calculate_speed_level(self, current_fuel: float, evolution_level: int) -> int:
        """
        Calculate speed level (Glvl) based on fuel and evolution
        
        Args:
            current_fuel: Current available fuel amount
            evolution_level: Current mech evolution level (1-11)
            
        Returns:
            Speed level (Glvl) from 0-101
        """
        if current_fuel <= 0:
            return 0  # OFFLINE
        
        # Import evolution system for thresholds
        from systems.evolution_system import EvolutionSystem
        evolution_sys = EvolutionSystem()
        
        # SPECIAL CASE: Level 11 (OMEGA MECH) can reach Glvl 101!
        if evolution_level == 11:
            return self._calculate_omega_speed(current_fuel, evolution_sys)
        
        # For levels 1-4: Direct 1:1 mapping (1$ = 1 Glvl)
        if evolution_level <= 4:
            return min(int(current_fuel), 100)
        
        # For levels 5-10: Dynamic distribution across 100 levels
        return self._calculate_dynamic_speed(current_fuel, evolution_level, evolution_sys)
    
    def _calculate_omega_speed(self, current_fuel: float, evolution_sys) -> int:
        """Calculate speed for OMEGA MECH (Level 11) with Glvl 101 possibility"""
        omega_threshold = evolution_sys.EVOLUTION_THRESHOLDS[11]  # $10,000
        theoretical_max = 20000  # $20,000 for TRANSCENDENT mode
        
        if current_fuel >= theoretical_max:
            return 101  # TRANSCENDENT MODE ACTIVATED!
        
        fuel_in_omega = current_fuel - omega_threshold
        if fuel_in_omega <= 0:
            return 1  # Just reached OMEGA level
        
        omega_range = theoretical_max - omega_threshold  # $10,000 range
        glvl = int((fuel_in_omega / omega_range) * 100)
        return min(max(1, glvl), 100)
    
    def _calculate_dynamic_speed(self, current_fuel: float, evolution_level: int, evolution_sys) -> int:
        """Calculate speed for levels 5-10 using dynamic scaling"""
        current_threshold = evolution_sys.EVOLUTION_THRESHOLDS[evolution_level]
        
        # Get next level threshold (or estimate if max evolution level)
        if evolution_level < 11:
            next_threshold = evolution_sys.EVOLUTION_THRESHOLDS[evolution_level + 1]
        else:
            next_threshold = current_threshold * 2  # Fallback estimation
        
        fuel_in_level = current_fuel - current_threshold
        if fuel_in_level <= 0:
            return 1  # Just reached this evolution level
        
        max_fuel_for_level = next_threshold - current_threshold
        if max_fuel_for_level <= 0:
            return 100
        
        glvl = int((fuel_in_level / max_fuel_for_level) * 100)
        return min(max(1, glvl), 100)
    
    # ========================================
    # SPEED INFORMATION AND PROPERTIES
    # ========================================
    
    def get_speed_level_info(self, current_fuel: float, evolution_level: int) -> SpeedLevel:
        """
        Get complete speed level information
        
        Args:
            current_fuel: Current available fuel amount
            evolution_level: Current mech evolution level
            
        Returns:
            SpeedLevel object with complete information
        """
        glvl = self.calculate_speed_level(current_fuel, evolution_level)
        description, color = self.SPEED_DESCRIPTIONS.get(glvl, ("Unknown", "#ffffff"))
        
        return SpeedLevel(
            glvl=glvl,
            description=description,
            color=color,
            is_transcendent=(glvl == 101)
        )
    
    def get_speed_description(self, glvl: int) -> Tuple[str, str]:
        """
        Get description and color for a specific Glvl
        
        Args:
            glvl: Speed level (0-101)
            
        Returns:
            Tuple of (description, color)
        """
        return self.SPEED_DESCRIPTIONS.get(glvl, ("Unknown", "#ffffff"))
    
    def get_animation_duration(self, glvl: int) -> int:
        """
        Get animation duration in milliseconds based on speed level
        
        Args:
            glvl: Speed level (0-101)
            
        Returns:
            Animation duration in milliseconds
        """
        if glvl <= 0:
            return 800  # Very slow for offline
        elif glvl == 101:
            return 25   # TRANSCENDENT - Reality cannot keep up!
        else:
            # Map Glvl 1-100 to duration 600ms-50ms
            return max(50, 600 - (glvl * 5.5))
    
    # ========================================
    # SPEED EFFECTS AND VISUAL PROPERTIES
    # ========================================
    
    def get_visual_effects_level(self, glvl: int) -> str:
        """
        Determine what visual effects should be active
        
        Args:
            glvl: Speed level (0-101)
            
        Returns:
            Effect level name
        """
        if glvl == 101:
            return "transcendent"
        elif glvl >= 100:
            return "divine_glow"
        elif glvl >= 90:
            return "lightning"
        elif glvl >= 70:
            return "purple_glow"
        elif glvl >= 50:
            return "cyan_glow"
        elif glvl >= 30:
            return "speed_lines"
        elif glvl > 0:
            return "basic"
        else:
            return "offline"
    
    def should_show_glow_effect(self, glvl: int) -> bool:
        """Check if glow effects should be displayed"""
        return glvl >= 50
    
    def should_show_speed_lines(self, glvl: int) -> bool:
        """Check if speed lines should be displayed"""
        return glvl >= 30
    
    def should_show_lightning(self, glvl: int) -> bool:
        """Check if lightning effects should be displayed"""
        return glvl >= 90
    
    def is_transcendent_mode(self, glvl: int) -> bool:
        """Check if in TRANSCENDENT mode (Glvl 101)"""
        return glvl == 101
    
    # ========================================
    # COMPREHENSIVE STATUS METHODS
    # ========================================
    
    def get_complete_speed_status(self, current_fuel: float, evolution_level: int) -> Dict[str, Any]:
        """
        Get comprehensive speed status information
        
        Args:
            current_fuel: Current available fuel amount
            evolution_level: Current mech evolution level
            
        Returns:
            Dictionary with complete speed status
        """
        speed_info = self.get_speed_level_info(current_fuel, evolution_level)
        
        return {
            'glvl': speed_info.glvl,
            'description': speed_info.description,
            'color': speed_info.color,
            'is_operational': speed_info.is_operational,
            'is_transcendent': speed_info.is_transcendent,
            'animation_duration': self.get_animation_duration(speed_info.glvl),
            'visual_effects': {
                'level': self.get_visual_effects_level(speed_info.glvl),
                'show_glow': self.should_show_glow_effect(speed_info.glvl),
                'show_speed_lines': self.should_show_speed_lines(speed_info.glvl),
                'show_lightning': self.should_show_lightning(speed_info.glvl),
                'is_transcendent': self.is_transcendent_mode(speed_info.glvl)
            },
            'fuel_info': {
                'current_fuel': current_fuel,
                'evolution_level': evolution_level
            }
        }


# ========================================
# CONVENIENCE FUNCTIONS
# ========================================

def format_speed_level(glvl: int) -> str:
    """Format speed level for display"""
    if glvl == 101:
        return "Glvl 101 ⚡ TRANSCENDENT"
    elif glvl == 0:
        return "OFFLINE"
    else:
        return f"Glvl {glvl}"

def get_speed_emoji(glvl: int) -> str:
    """Get emoji representation for speed level"""
    if glvl == 101:
        return "⚡"
    elif glvl >= 90:
        return "🚀"
    elif glvl >= 70:
        return "💨"
    elif glvl >= 50:
        return "🏃"
    elif glvl >= 30:
        return "🚶"
    elif glvl > 0:
        return "🐌"
    else:
        return "⚫"