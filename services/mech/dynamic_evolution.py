#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Dynamic Evolution Cost System                   #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""
Dynamic Evolution Cost System based on unique Discord members in status channels.

This system adjusts evolution costs based on community size:
- Small communities (1-10 members): Base cost * 0.5
- Medium communities (11-50 members): Base cost * 1.0
- Large communities (51-200 members): Base cost * 1.5
- Huge communities (200+ members): Base cost * 2.0+
"""

import logging
from typing import Dict, List, Set, Optional, Tuple
from dataclasses import dataclass
import math
from .evolution_config_manager import get_evolution_config_manager

logger = logging.getLogger(__name__)

# Legacy costs - now loaded from JSON config
# Kept for backward compatibility
BASE_EVOLUTION_COSTS = {
    1: 0, 2: 20, 3: 50, 4: 100, 5: 200, 6: 400, 7: 800, 8: 1500, 9: 2500, 10: 4000, 11: 10000
}

@dataclass
class CommunitySize:
    """Represents the size of a community based on unique members."""
    unique_members: int
    multiplier: float
    tier_name: str
    
    @classmethod
    def from_member_count(cls, member_count: int) -> 'CommunitySize':
        """Determine community size tier from member count using JSON config."""
        config_manager = get_evolution_config_manager()
        community_info = config_manager.get_community_size_info(member_count)
        
        return cls(
            unique_members=member_count,
            multiplier=community_info["multiplier"],
            tier_name=community_info["tier_name"]
        )


class DynamicEvolutionCalculator:
    """Calculates dynamic evolution costs based on community size."""
    
    def __init__(self):
        self.cached_member_count: Optional[int] = None
        self.cached_multiplier: Optional[float] = None
        self.cache_timestamp: Optional[float] = None
        self.cache_ttl_seconds: int = 300  # 5 minutes cache
        
    async def get_unique_member_count(self, bot) -> int:
        """
        Get the count of unique members across all status channels.
        
        Args:
            bot: The Discord bot instance
            
        Returns:
            Number of unique Discord members in status channels
        """
        import time
        
        # Check cache first (5 minute TTL for performance)
        current_time = time.time()
        if (self.cached_member_count is not None and 
            self.cache_timestamp is not None and 
            current_time - self.cache_timestamp < self.cache_ttl_seconds):
            
            logger.debug(f"Using cached member count: {self.cached_member_count} (age: {current_time - self.cache_timestamp:.1f}s)")
            return self.cached_member_count
        
        try:
            from services.config.config_service import load_config
            config = load_config()
            
            if not config or not bot:
                return 0
                
            unique_members: Set[int] = set()
            
            # Get all channels with serverstatus permission
            channels = config.get('channel_permissions', {})
            
            for channel_id, permissions in channels.items():
                # Only count members in status channels, not control channels
                if permissions.get('commands', {}).get('serverstatus', False):
                    try:
                        channel = bot.get_channel(int(channel_id))
                        if channel and hasattr(channel, 'members'):
                            # Add all member IDs to the set (automatically handles duplicates)
                            for member in channel.members:
                                if not member.bot:  # Don't count bots
                                    unique_members.add(member.id)
                    except Exception as e:
                        logger.debug(f"Could not get members for channel {channel_id}: {e}")
                        continue
            
            member_count = len(unique_members)
            logger.info(f"Dynamic Evolution: Found {member_count} unique members across status channels")
            
            # Update cache with timestamp
            import time
            self.cached_member_count = member_count
            self.cache_timestamp = time.time()
            
            return member_count
            
        except Exception as e:
            logger.error(f"Error getting unique member count: {e}")
            # Return cached value or conservative default
            return self.cached_member_count or 50  # Default to medium community
    
    def calculate_evolution_cost(self, level: int, member_count: int) -> Tuple[int, float, str]:
        """
        Calculate the dynamic evolution cost for a specific level using JSON config.
        
        Args:
            level: The target mech level (2-11)
            member_count: Number of unique members in status channels
            
        Returns:
            Tuple of (adjusted_cost, multiplier, tier_name)
        """
        if level == 1:
            return 0, 1.0, "N/A"
            
        config_manager = get_evolution_config_manager()
        community_info = config_manager.get_community_size_info(member_count)
        
        # Calculate dynamic cost using config manager
        adjusted_cost, effective_multiplier = config_manager.calculate_dynamic_cost(
            level, member_count, community_info["multiplier"]
        )
        
        logger.debug(
            f"Evolution cost for level {level}: "
            f"${adjusted_cost} (multiplier: {effective_multiplier:.2f}, "
            f"tier: {community_info['tier_name']})"
        )
        
        return adjusted_cost, effective_multiplier, community_info["tier_name"]
    
    def get_all_evolution_costs(self, member_count: int) -> Dict[int, Dict]:
        """
        Get all evolution costs for a given member count using JSON config.
        
        Returns:
            Dict mapping level to cost information
        """
        config_manager = get_evolution_config_manager()
        costs = {}
        
        for level in range(2, 12):  # Levels 2-11 have evolution costs
            evolution_level = config_manager.get_evolution_level(level)
            if not evolution_level:
                continue
                
            cost, multiplier, tier = self.calculate_evolution_cost(level, member_count)
            costs[level] = {
                'base_cost': evolution_level.base_cost,
                'adjusted_cost': cost,
                'multiplier': multiplier,
                'tier': tier,
                'difference': cost - evolution_level.base_cost,
                'name': evolution_level.name,
                'color': evolution_level.color
            }
        return costs


# Global instance
_calculator_instance = None

def get_evolution_calculator() -> DynamicEvolutionCalculator:
    """Get the singleton evolution calculator instance."""
    global _calculator_instance
    if _calculator_instance is None:
        _calculator_instance = DynamicEvolutionCalculator()
    return _calculator_instance