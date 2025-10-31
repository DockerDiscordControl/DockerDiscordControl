# -*- coding: utf-8 -*-
"""
Dynamic Evolution Service - Provides evolution calculations based on community size.
"""

import logging
from typing import Dict, Any
from .monthly_member_cache import get_monthly_member_cache

logger = logging.getLogger('ddc.dynamic_evolution')

class EvolutionCalculator:
    """Simple evolution calculator based on member count."""

    def __init__(self):
        self.base_thresholds = {
            1: 5, 2: 10, 3: 20, 4: 35, 5: 55, 6: 80, 7: 110, 8: 145, 9: 185, 10: 230, 11: 280
        }

    def calculate_threshold(self, level: int, member_count: int = None) -> int:
        """Calculate threshold for a given level based on member count."""
        if member_count is None:
            try:
                cache = get_monthly_member_cache()
                member_count = cache.get_member_count()
            except:
                member_count = 50

        base = self.base_thresholds.get(level, 50)

        # Simple scaling: smaller communities get reduced thresholds
        if member_count < 25:
            multiplier = 0.7
        elif member_count < 50:
            multiplier = 0.8
        elif member_count < 100:
            multiplier = 0.9
        else:
            multiplier = 1.0

        return max(1, int(base * multiplier))

    def get_all_thresholds(self, member_count: int = None) -> Dict[int, int]:
        """Get all evolution thresholds."""
        return {level: self.calculate_threshold(level, member_count)
                for level in range(1, 12)}

# Global instance
_evolution_calculator_instance = None

def get_evolution_calculator() -> EvolutionCalculator:
    """Get the global evolution calculator instance."""
    global _evolution_calculator_instance
    if _evolution_calculator_instance is None:
        _evolution_calculator_instance = EvolutionCalculator()
    return _evolution_calculator_instance