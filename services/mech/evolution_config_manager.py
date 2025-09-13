#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Evolution Configuration Manager                #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""
Evolution Configuration Manager - Handles JSON-based evolution settings
"""

import json
import logging
import math
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class EvolutionLevel:
    """Represents a single evolution level configuration."""
    level: int
    name: str
    description: str
    color: str
    base_cost: int
    power_max: int

class EvolutionConfigManager:
    """Manages evolution configuration from JSON file."""
    
    def __init__(self, config_path: str = "services/mech/evolution_config.json"):
        self.config_path = Path(config_path)
        self._config_cache: Optional[Dict[str, Any]] = None
        self._last_modified = None
        
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from JSON file with caching."""
        try:
            # Check if file was modified since last load
            if self.config_path.exists():
                current_modified = self.config_path.stat().st_mtime
                if self._config_cache is not None and self._last_modified == current_modified:
                    return self._config_cache
                
                # Load fresh config
                with self.config_path.open('r', encoding='utf-8') as f:
                    config = json.load(f)
                    
                self._config_cache = config
                self._last_modified = current_modified
                logger.debug(f"Evolution config loaded from {self.config_path}")
                return config
            else:
                logger.warning(f"Evolution config file not found: {self.config_path}")
                return self._get_default_config()
                
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Error loading evolution config: {e}")
            return self._get_default_config()
    
    def _get_default_config(self) -> Dict[str, Any]:
        """Return default configuration as fallback."""
        return {
            "evolution_settings": {
                "difficulty_multiplier": 1.0,
                "power_decay_per_day": 1.0,
                "min_evolution_cost": 5,
                "max_evolution_cost_level_2": 50,
                "recalculate_on_level_up": True,
                "update_interval_minutes": 10
            },
            "base_evolution_costs": {
                "1": {"name": "SCRAP MECH", "cost": 0, "power_max": 20, "color": "#444444"},
                "2": {"name": "REPAIRED MECH", "cost": 20, "power_max": 30, "color": "#666666"},
                "3": {"name": "STANDARD MECH", "cost": 50, "power_max": 50, "color": "#888888"},
                "4": {"name": "ENHANCED MECH", "cost": 100, "power_max": 100, "color": "#0099cc"},
                "5": {"name": "ADVANCED MECH", "cost": 200, "power_max": 200, "color": "#00ccff"},
                "6": {"name": "ELITE MECH", "cost": 400, "power_max": 400, "color": "#ffcc00"},
                "7": {"name": "CYBER MECH", "cost": 800, "power_max": 800, "color": "#ff6600"},
                "8": {"name": "PLASMA MECH", "cost": 1500, "power_max": 1500, "color": "#cc00ff"},
                "9": {"name": "QUANTUM MECH", "cost": 2500, "power_max": 2500, "color": "#00ffff"},
                "10": {"name": "DIVINE MECH", "cost": 4000, "power_max": 4000, "color": "#ffff00"},
                "11": {"name": "OMEGA MECH", "cost": 10000, "power_max": 10000, "color": "#ff00ff"}
            },
            "community_size_tiers": {
                "MEDIUM": {"min_members": 26, "max_members": 50, "multiplier": 1.0}
            }
        }
    
    def save_config(self, config: Dict[str, Any]) -> bool:
        """Save configuration to JSON file."""
        try:
            # Ensure directory exists
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Write with atomic operation using temp file
            temp_path = self.config_path.with_suffix('.tmp')
            with temp_path.open('w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            
            # Atomic replace
            temp_path.replace(self.config_path)
            
            # Clear cache to force reload
            self._config_cache = None
            self._last_modified = None
            
            logger.info(f"Evolution config saved to {self.config_path}")
            return True
            
        except (IOError, OSError) as e:
            logger.error(f"Error saving evolution config: {e}")
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
        config.setdefault("evolution_settings", {})["difficulty_multiplier"] = multiplier
        
        return self.save_config(config)
    
    def get_evolution_level(self, level: int) -> Optional[EvolutionLevel]:
        """Get evolution level configuration."""
        config = self._load_config()
        level_data = config.get("base_evolution_costs", {}).get(str(level))
        
        if not level_data:
            return None
            
        return EvolutionLevel(
            level=level,
            name=level_data.get("name", f"Level {level}"),
            description=level_data.get("description", ""),
            color=level_data.get("color", "#888888"),
            base_cost=level_data.get("cost", 0),
            power_max=level_data.get("power_max", 100)
        )
    
    def get_all_evolution_levels(self) -> Dict[int, EvolutionLevel]:
        """Get all evolution levels."""
        config = self._load_config()
        levels = {}
        
        for level_str, level_data in config.get("base_evolution_costs", {}).items():
            try:
                level = int(level_str)
                levels[level] = EvolutionLevel(
                    level=level,
                    name=level_data.get("name", f"Level {level}"),
                    description=level_data.get("description", ""),
                    color=level_data.get("color", "#888888"),
                    base_cost=level_data.get("cost", 0),
                    power_max=level_data.get("power_max", 100)
                )
            except ValueError:
                logger.warning(f"Invalid level number in config: {level_str}")
                continue
                
        return levels
    
    def calculate_dynamic_cost(self, level: int, member_count: int, community_multiplier: float) -> Tuple[int, float]:
        """
        Calculate dynamic evolution cost for a specific level.
        
        Args:
            level: Target evolution level
            member_count: Number of unique Discord members
            community_multiplier: Community size multiplier
            
        Returns:
            Tuple of (final_cost, effective_multiplier)
        """
        evolution_level = self.get_evolution_level(level)
        if not evolution_level or level == 1:
            return 0, 1.0
            
        # Get base cost and apply difficulty multiplier
        difficulty_mult = self.get_difficulty_multiplier()
        base_cost = evolution_level.base_cost
        
        # Apply difficulty and community multipliers
        effective_multiplier = difficulty_mult * community_multiplier
        final_cost = int(base_cost * effective_multiplier)
        
        # Ensure progressive minimum cost constraints
        config = self._load_config()
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

# Global instance
_config_manager_instance = None

def get_evolution_config_manager() -> EvolutionConfigManager:
    """Get the singleton evolution config manager instance."""
    global _config_manager_instance
    if _config_manager_instance is None:
        _config_manager_instance = EvolutionConfigManager()
    return _config_manager_instance