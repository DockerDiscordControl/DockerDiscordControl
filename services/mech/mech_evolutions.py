# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""
Mech Evolution System - Maps donation amounts to evolution levels
SERVICE FIRST: Unified evolution system replacing evolution_config_manager
"""

import json
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

    def __init__(self, config_path: str = None):
        if config_path:
            self.config_path = Path(config_path)
        else:
            # Robust default path relative to project root
            self.config_path = Path(__file__).parents[2] / "config" / "mech" / "evolution.json"
            
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
        except (ImportError, AttributeError, RuntimeError) as e:
            # Service dependency errors (config service unavailable)
            logger.error(f"Service dependency error loading evolution config: {e}", exc_info=True)
            return self._get_fallback_config()
        except (IOError, OSError) as e:
            # File I/O errors (config file access)
            logger.error(f"File I/O error loading evolution config: {e}", exc_info=True)
            return self._get_fallback_config()
        except json.JSONDecodeError as e:
            # JSON parsing errors (corrupted config)
            logger.error(f"JSON parsing error loading evolution config: {e}", exc_info=True)
            return self._get_fallback_config()

    def _get_fallback_config(self) -> Dict[str, Any]:
        """Return fallback configuration with hardcoded values."""
        # Hardcoded fallback data (REALISTIC PRICING - matches evolution_config.json)
        fallback_data = {
            1: {"name": "The Rustborn Husk", "description": "Once a glorious war machine, now a corroded ruin. Rust gnaws through its joints, hydraulic fluids drip from torn plating, and its reactor sputters faintly. Barely able to move, it staggers like a dying beast.", "color": "#444444", "cost": 0, "power_max": 20, "decay_per_day": 1.0},
            2: {"name": "The Battle-Scarred Survivor", "description": "A patched-up wreck, limping forward with mismatched armor and screeching servos. Every step is agony, but its core refuses to shut down. It is stubborn survival embodied in steel.", "color": "#666666", "cost": 10, "power_max": 10, "decay_per_day": 1.0},
            3: {"name": "The Corewalker Standard", "description": "The dependable backbone of every mechanized army. Neither rusted ruin nor experimental prototype, but the perfected baseline. Mass-produced, balanced in offense and defense, its sturdy frame and reliable core make it the soldier's choice—the mech that wins wars through sheer numbers and unshakable consistency.", "color": "#888888", "cost": 15, "power_max": 15, "decay_per_day": 1.0},
            4: {"name": "The Titanframe", "description": "Augmented with bulked plating and spiked enhancements, this mech becomes a juggernaut of intimidation. Every movement resonates with power, built to crush resistance head-on.", "color": "#0099cc", "cost": 20, "power_max": 20, "decay_per_day": 1.0},
            5: {"name": "The Pulseforged Guardian", "description": "Energy channels glow across its reinforced body, pulsing like living veins. Its reactor hums with controlled plasma output, a perfected synthesis of raw strength and engineered balance.", "color": "#00ccff", "cost": 25, "power_max": 25, "decay_per_day": 1.0},
            6: {"name": "The Abyss Engine", "description": "A dark branch of evolution, tainted by void-tech. Corruption twists its frame, reactor howls like a collapsing star. It moves with unnatural spasms—unstable, terrifying, yet overwhelmingly powerful.", "color": "#ffcc00", "cost": 30, "power_max": 30, "decay_per_day": 1.0},
            7: {"name": "The Rift Strider", "description": "Mastery from chaos: sleek, fast, and armed with rift engines. It phases in and out of existence, striking enemies with energy blades before they can react. A predator between dimensions.", "color": "#ff6600", "cost": 35, "power_max": 35, "decay_per_day": 1.0},
            8: {"name": "The Radiant Bastion", "description": "A glowing fortress of shields and radiant plating. Built to withstand orbital bombardments, this mech inspires entire armies with its unyielding defense and brilliant aura.", "color": "#cc00ff", "cost": 40, "power_max": 40, "decay_per_day": 1.0},
            9: {"name": "The Overlord Ascendant", "description": "Elevated above the battlefield, carried and revered by lesser frames. Wreathed in fire and cloaked in command systems, it has become both warlord and deity of steel.", "color": "#00ffff", "cost": 45, "power_max": 45, "decay_per_day": 1.0},
            10: {"name": "The Celestial Exarch", "description": "The final transcendence. No longer merely a machine, it radiates with cosmic energy, haloed in starlight. A godlike protector forged from centuries of steel and sacrifice.", "color": "#ffff00", "cost": 50, "power_max": 50, "decay_per_day": 1.0},
            11: {"name": "OMEGA MECH", "description": "The final scream of a burning universe, forged into indestructible form. Its steps tear the fabric of existence, its pulse synchronizes with the heartbeat of dead gods. Finality in metal form.", "color": "#ff00ff", "cost": 100, "power_max": 100, "decay_per_day": 0.0}   # IMMORTAL!
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

        except (IOError, OSError) as e:
            # File I/O errors (file write, directory creation)
            logger.error(f"File I/O error saving evolution config: {e}", exc_info=True)
            return False
        except RuntimeError as e:
            # Service operation errors (config service save failure)
            logger.error(f"Service error saving evolution config: {e}", exc_info=True)
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

    # Load decay from separate config file (config/mech/decay.json)
    # This ensures consistency with progress_service logic
    decay_val = level_data.get("decay_per_day", 1.0)
    try:
        # Robust absolute path relative to project root
        decay_path = Path(__file__).parents[2] / "config" / "mech" / "decay.json"
        if decay_path.exists():
            with open(decay_path, "r") as f:
                d_cfg = json.load(f)
                # Value is in cents, convert to dollars
                decay_cents = d_cfg.get("levels", {}).get(str(level))
                if decay_cents is None:
                    decay_cents = d_cfg.get("default", 100)
                decay_val = float(decay_cents) / 100.0
    except Exception as e:
        logger.error(f"Error loading decay config in evolutions: {e}")

    return EvolutionLevelInfo(
        level=level,
        name=level_data.get("name", f"Level {level}"),
        description=level_data.get("description", ""),
        color=level_data.get("color", "#888888"),
        base_cost=level_data.get("cost", 0),
        power_max=level_data.get("power_max", 100),
        decay_per_day=decay_val
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
