# -*- coding: utf-8 -*-
"""
Mech Evolution System - Maps donation amounts to evolution levels
SERVICE FIRST: Unified evolution system replacing evolution_config_manager
"""

import logging
import math
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Dict, Any, Tuple

logger = logging.getLogger(__name__)

@dataclass
class EvolutionLevelInfo:
    """SERVICE FIRST: Evolution level information (replaces evolution_config_manager.EvolutionLevel)"""
    level: int
    name: str
    description: str
    color: str
    base_cost: int
    power_max: int = 100
    decay_per_day: float = 1.0

# SERVICE FIRST: JSON config management (replaces evolution_config_manager functionality)
class EvolutionConfigService:
    """SERVICE FIRST: Unified evolution configuration service."""

    def __init__(self, config_path: str = "services/mech/evolution_config.json"):
        self.config_path = Path(config_path)
        # Use central ConfigService for robust JSON handling
        from services.config.config_service import get_config_service
        self._central_config_service = get_config_service()

    def _load_config(self) -> Dict[str, Any]:
        """Load configuration using central ConfigService (robust, cached, error-handled)."""
        try:
            # Use central ConfigService for robust JSON loading with automatic fallbacks
            config = self._central_config_service._load_json_file(
                self.config_path,
                self._get_fallback_config()
            )
            logger.debug(f"Evolution config loaded via central ConfigService: {self.config_path}")
            return config
        except Exception as e:
            logger.error(f"Error loading evolution config via central service: {e}")
            return self._get_fallback_config()

    def _get_fallback_config(self) -> Dict[str, Any]:
        """Return fallback configuration with hardcoded values."""
        # Hardcoded fallback data (same as JSON config including dynamic decay rates!)
        fallback_data = {
            1: {"name": "SCRAP MECH", "description": "Barely holding together with rust and spare parts", "color": "#444444", "cost": 0, "power_max": 20, "decay_per_day": 1.0},
            2: {"name": "REPAIRED MECH", "description": "Basic repairs complete, systems barely functional", "color": "#666666", "cost": 20, "power_max": 40, "decay_per_day": 1.0},
            3: {"name": "STANDARD MECH", "description": "Standard military-grade combat chassis", "color": "#888888", "cost": 50, "power_max": 60, "decay_per_day": 1.0},
            4: {"name": "ENHANCED MECH", "description": "Reinforced armor plating and enhanced servos", "color": "#0099cc", "cost": 100, "power_max": 80, "decay_per_day": 4.0},  # Fast decay!
            5: {"name": "ADVANCED MECH", "description": "Advanced targeting systems and weapon upgrades", "color": "#00ccff", "cost": 200, "power_max": 100, "decay_per_day": 1.0},
            6: {"name": "ELITE MECH", "description": "Elite combat protocols and titanium armor", "color": "#ffcc00", "cost": 400, "power_max": 120, "decay_per_day": 3.0},  # Moderate-fast decay
            7: {"name": "CYBER MECH", "description": "Cybernetic neural interface and energy shields", "color": "#ff6600", "cost": 800, "power_max": 140, "decay_per_day": 2.0},  # Moderate decay
            8: {"name": "PLASMA MECH", "description": "Plasma-powered core with quantum processors", "color": "#cc00ff", "cost": 1500, "power_max": 160, "decay_per_day": 1.5},  # Slow decay
            9: {"name": "QUANTUM MECH", "description": "Quantum entanglement drive and phase shifting", "color": "#00ffff", "cost": 2500, "power_max": 180, "decay_per_day": 5.0},  # Extreme decay!
            10: {"name": "DIVINE MECH", "description": "Transcendent technology beyond mortal comprehension", "color": "#ffff00", "cost": 4000, "power_max": 200, "decay_per_day": 4.0},  # Fast decay
            11: {"name": "OMEGA MECH", "description": "Reality-bending omnipotent war machine of the gods", "color": "#ff00ff", "cost": 10000, "power_max": 300, "decay_per_day": 0.0}   # IMMORTAL!
        }

        base_costs = {}
        for level, data in fallback_data.items():
            base_costs[str(level)] = data

        return {
            "evolution_settings": {
                "difficulty_multiplier": 1.0,
                "manual_difficulty_override": False,
                "power_decay_per_day": 1.0,
                "min_evolution_cost": 5,
                "max_evolution_cost_level_2": 50,
                "recalculate_on_level_up": True,
                "update_interval_minutes": 10
            },
            "base_evolution_costs": base_costs,
            "community_size_tiers": {
                "MEDIUM": {"min_members": 26, "max_members": 50, "multiplier": 1.0, "description": "Medium community (baseline)"}
            }
        }

    def save_config(self, config: Dict[str, Any]) -> bool:
        """Save configuration using central ConfigService (robust, atomic)."""
        try:
            # Ensure directory exists
            self.config_path.parent.mkdir(parents=True, exist_ok=True)

            # Use central ConfigService for robust JSON saving
            self._central_config_service._save_json_file(self.config_path, config)

            logger.info(f"Evolution config saved via central ConfigService: {self.config_path}")
            return True

        except Exception as e:
            logger.error(f"Error saving evolution config via central service: {e}")
            return False

    def get_difficulty_multiplier(self) -> float:
        """Get current difficulty multiplier setting."""
        config = self._load_config()
        return config.get("evolution_settings", {}).get("difficulty_multiplier", 1.0)

    def set_difficulty_multiplier(self, multiplier: float) -> bool:
        """Set difficulty multiplier (affects all evolution costs)."""
        # Clamp multiplier to ensure Level 2 stays between $5-$50
        # Base cost for Level 2 is $20, so multiplier range is 0.25-2.5
        multiplier = max(0.25, min(2.5, multiplier))

        config = self._load_config()
        evolution_settings = config.setdefault("evolution_settings", {})
        evolution_settings["difficulty_multiplier"] = multiplier
        evolution_settings["manual_difficulty_override"] = True  # Mark as manually set

        return self.save_config(config)

    def is_auto_difficulty(self) -> bool:
        """Check if automatic difficulty adjustment is enabled."""
        config = self._load_config()
        return not config.get("evolution_settings", {}).get("manual_difficulty_override", False)

    def reset_to_auto_difficulty(self) -> bool:
        """Reset difficulty to automatic mode (clears override and sets to 1.0)."""
        config = self._load_config()
        evolution_settings = config.setdefault("evolution_settings", {})
        evolution_settings["difficulty_multiplier"] = 1.0
        evolution_settings["manual_difficulty_override"] = False
        return self.save_config(config)

    def get_community_size_info(self, member_count: int) -> Dict[str, Any]:
        """Get community size tier information for given member count."""
        config = self._load_config()
        tiers = config.get("community_size_tiers", {})

        # Find matching tier
        for tier_name, tier_data in tiers.items():
            min_members = tier_data.get("min_members", 0)
            max_members = tier_data.get("max_members", 999999)

            if min_members <= member_count <= max_members:
                multiplier = tier_data.get("multiplier", 1.0)

                # Apply logarithmic scaling for massive communities
                if tier_name == "MASSIVE" and member_count > 1000:
                    extra_multiplier = 0.5 * math.log2(member_count / 1000)
                    multiplier += extra_multiplier

                return {
                    "tier_name": tier_name,
                    "multiplier": multiplier,
                    "description": tier_data.get("description", ""),
                    "member_count": member_count,
                    "min_members": min_members,
                    "max_members": max_members
                }

        # Default fallback
        return {
            "tier_name": "MEDIUM",
            "multiplier": 1.0,
            "description": "Medium community (baseline)",
            "member_count": member_count,
            "min_members": 26,
            "max_members": 50
        }

# Global config service instance
_config_service: Optional[EvolutionConfigService] = None

def get_evolution_config_service() -> EvolutionConfigService:
    """Get the singleton evolution config service instance."""
    global _config_service
    if _config_service is None:
        _config_service = EvolutionConfigService()
    return _config_service

def get_evolution_level(total_donations: float) -> int:
    """
    Calculate evolution level based on total donations.

    Args:
        total_donations: Total donation amount in dollars/euros

    Returns:
        Evolution level (1-11)
    """
    if total_donations < 0:
        return 1  # Minimum is level 1 now

    # Use JSON config as authoritative source
    config_service = get_evolution_config_service()
    config = config_service._load_config()
    base_costs = config.get("base_evolution_costs", {})

    # Find the highest evolution level the donations qualify for
    for level in range(11, 0, -1):  # Check from highest (11) to lowest (1)
        level_data = base_costs.get(str(level))
        if level_data and total_donations >= level_data.get("cost", 0):
            return level

    return 1  # Default to level 1 (SCRAP MECH)

def get_evolution_info(total_donations: float) -> dict:
    """
    Get complete evolution information for given donation amount.

    Args:
        total_donations: Total donation amount in dollars/euros

    Returns:
        Dictionary with level, name, color, next_threshold, descriptions
    """
    level = get_evolution_level(total_donations)

    # Use JSON config as authoritative source
    config_service = get_evolution_config_service()
    config = config_service._load_config()
    base_costs = config.get("base_evolution_costs", {})

    level_data = base_costs.get(str(level), {})
    name = level_data.get("name", f"Level {level}")
    color = level_data.get("color", "#888888")
    description = level_data.get("description", "")
    current_threshold = level_data.get("cost", 0)

    # Calculate next evolution threshold and sneak peek
    next_threshold = None
    next_name = None
    next_description = None
    amount_needed = None

    if level < 11:  # Now goes up to 11
        next_level_data = base_costs.get(str(level + 1), {})
        next_threshold = next_level_data.get("cost")
        if next_threshold is not None:
            next_name = next_level_data.get("name", f"Level {level + 1}")
            next_description = next_level_data.get("description", "")
            amount_needed = next_threshold - total_donations

    return {
        'level': level,
        'name': name,
        'color': color,
        'description': description,
        'current_threshold': current_threshold,
        'next_threshold': next_threshold,
        'next_name': next_name,
        'next_description': next_description,
        'amount_needed': amount_needed,
        'progress_to_next': None if next_threshold is None else min(100, (total_donations - current_threshold) / (next_threshold - current_threshold) * 100)
    }

def get_mech_filename(evolution_level: int) -> str:
    """
    Get filename for mech evolution spritesheet.
    
    Args:
        evolution_level: Evolution level (1-11)
        
    Returns:
        Filename for the spritesheet
    """
    return f"mech_level_{evolution_level}.png"

def get_evolution_level_info(level: int) -> Optional[EvolutionLevelInfo]:
    """
    SERVICE FIRST: Get evolution level information (replaces evolution_config_manager.get_evolution_level)

    Args:
        level: Evolution level (1-11)

    Returns:
        EvolutionLevelInfo or None if level doesn't exist
    """
    # Use JSON config as authoritative source
    config_service = get_evolution_config_service()
    config = config_service._load_config()
    level_data = config.get("base_evolution_costs", {}).get(str(level))

    if not level_data:
        return None

    return EvolutionLevelInfo(
        level=level,
        name=level_data.get("name", f"Level {level}"),
        description=level_data.get("description", ""),
        color=level_data.get("color", "#888888"),
        base_cost=level_data.get("cost", 0),
        power_max=level_data.get("power_max", 100),
        decay_per_day=level_data.get("decay_per_day", 1.0)
    )

def calculate_dynamic_cost(level: int, member_count: int, community_multiplier: float = None) -> Tuple[int, float]:
    """
    SERVICE FIRST: Calculate dynamic evolution cost for a specific level.

    Args:
        level: Target evolution level
        member_count: Number of unique Discord members
        community_multiplier: Optional override for community multiplier

    Returns:
        Tuple of (final_cost, effective_multiplier)
    """
    evolution_level = get_evolution_level_info(level)
    if not evolution_level or level == 1:
        return 0, 1.0

    # Get config service
    config_service = get_evolution_config_service()

    # Get base cost and apply difficulty multiplier
    difficulty_mult = config_service.get_difficulty_multiplier()
    base_cost = evolution_level.base_cost

    # Get community multiplier if not provided
    if community_multiplier is None:
        community_info = config_service.get_community_size_info(member_count)
        community_multiplier = community_info["multiplier"]

    # Apply difficulty and community multipliers
    effective_multiplier = difficulty_mult * community_multiplier
    final_cost = int(base_cost * effective_multiplier)

    # Ensure progressive minimum cost constraints
    config = config_service._load_config()
    base_min_cost = config.get("evolution_settings", {}).get("min_evolution_cost", 5)

    if level > 1:
        # Each level must cost at least $2 more than the previous minimum
        progressive_min_cost = base_min_cost + ((level - 2) * 2)
        final_cost = max(progressive_min_cost, final_cost)

    logger.debug(
        f"Dynamic cost for Level {level}: "
        f"Base ${base_cost} × {difficulty_mult:.2f} (difficulty) × {community_multiplier:.2f} (community) "
        f"= ${final_cost}"
    )

    return final_cost, effective_multiplier

# SERVICE FIRST: Additional helper functions

def get_all_evolution_levels() -> Dict[int, EvolutionLevelInfo]:
    """SERVICE FIRST: Get all evolution levels from JSON config."""
    config_service = get_evolution_config_service()
    config = config_service._load_config()
    levels = {}

    for level_str, level_data in config.get("base_evolution_costs", {}).items():
        try:
            level = int(level_str)
            levels[level] = EvolutionLevelInfo(
                level=level,
                name=level_data.get("name", f"Level {level}"),
                description=level_data.get("description", ""),
                color=level_data.get("color", "#888888"),
                base_cost=level_data.get("cost", 0),
                power_max=level_data.get("power_max", 100),
                decay_per_day=level_data.get("decay_per_day", 1.0)
            )
        except ValueError:
            logger.warning(f"Invalid level number in config: {level_str}")
            continue

    return levels