#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Simple Evolution Service - Fixed achieved levels + difficulty slider for next level only

This replaces the complex dynamic evolution system with a simple approach:
- Achieved levels are LOCKED and never change
- Only the NEXT level cost is affected by difficulty slider
- Easy Web UI integration with existing slider/buttons
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)

@dataclass
class SimpleLevelInfo:
    """Simple level information."""
    level: int
    cost: int
    achieved: bool
    locked: bool

@dataclass
class SimpleEvolutionState:
    """Simple evolution state."""
    current_level: int
    total_donated: float
    next_level_cost: int
    difficulty: float
    achieved_levels: Dict[int, SimpleLevelInfo]

class SimpleEvolutionService:
    """Simple evolution service with fixed achieved levels."""

    def __init__(self, config_path: str = "config/achieved_levels.json"):
        self.config_path = Path(config_path)
        self.base_costs = {
            1: 0, 2: 20, 3: 50, 4: 100, 5: 200,
            6: 400, 7: 800, 8: 1500, 9: 2500, 10: 4000, 11: 10000
        }

    def get_current_state(self, total_donated: float, difficulty: float = 1.0) -> SimpleEvolutionState:
        """Get current evolution state with locked achieved levels."""
        achieved_data = self._load_achieved_levels()

        # Determine current level from total donated
        current_level = self._calculate_current_level(total_donated, achieved_data, difficulty)

        # Build level info
        achieved_levels = {}
        for level in range(1, 12):
            if level <= current_level:
                # Achieved levels are LOCKED
                achieved_levels[level] = SimpleLevelInfo(
                    level=level,
                    cost=self.base_costs[level],  # Original cost
                    achieved=True,
                    locked=True
                )
            elif level == current_level + 1:
                # NEXT level affected by difficulty
                base_cost = self.base_costs[level]
                adjusted_cost = int(base_cost * difficulty)
                achieved_levels[level] = SimpleLevelInfo(
                    level=level,
                    cost=adjusted_cost,
                    achieved=False,
                    locked=False
                )
            else:
                # Future levels use current difficulty as preview
                base_cost = self.base_costs[level]
                adjusted_cost = int(base_cost * difficulty)
                achieved_levels[level] = SimpleLevelInfo(
                    level=level,
                    cost=adjusted_cost,
                    achieved=False,
                    locked=False
                )

        next_level_cost = achieved_levels[current_level + 1].cost if current_level < 11 else 0

        return SimpleEvolutionState(
            current_level=current_level,
            total_donated=total_donated,
            next_level_cost=next_level_cost,
            difficulty=difficulty,
            achieved_levels=achieved_levels
        )

    def _calculate_current_level(self, total_donated: float, achieved_data: Dict, difficulty: float) -> int:
        """Calculate current level from total donated amount."""
        current_level = 1

        # Check all levels from 1 to 11 to find the highest achievable level
        for level in range(1, 12):
            if level == 1:
                # Level 1 is always achieved with $0
                if total_donated >= 0:
                    current_level = level
            else:
                # Check if enough money for this level
                # Use locked cost if available, otherwise use base cost * difficulty
                achieved_levels = achieved_data.get("achieved_levels", {})
                if str(level) in achieved_levels and achieved_levels[str(level)].get("locked", False):
                    # Use locked cost for achieved levels
                    required_cost = achieved_levels[str(level)].get("cost_paid", self.base_costs[level])
                else:
                    # Use current difficulty for non-achieved levels
                    required_cost = self.base_costs[level] * difficulty

                if total_donated >= required_cost:
                    current_level = level
                else:
                    # Stop at first level we can't afford
                    break

        return current_level

    def _load_achieved_levels(self) -> Dict[str, Any]:
        """Load achieved levels from JSON."""
        try:
            if self.config_path.exists():
                with self.config_path.open('r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.warning(f"Could not load achieved levels: {e}")

        return {"achieved_levels": {}, "current_level": 1}

    def update_achieved_level(self, level: int, total_donated: float) -> None:
        """Update achieved levels when a level is reached."""
        data = self._load_achieved_levels()

        # Add new achieved level
        data["achieved_levels"][str(level)] = {
            "level": level,
            "cost_paid": self.base_costs[level],
            "achieved_at": datetime.now().isoformat(),
            "locked": True
        }

        data["current_level"] = level
        data["last_updated"] = datetime.now().isoformat()

        # Save
        try:
            with self.config_path.open('w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.info(f"Level {level} marked as achieved and locked")
        except Exception as e:
            logger.error(f"Failed to save achieved levels: {e}")

    def get_difficulty_presets(self) -> Dict[str, float]:
        """Get difficulty preset values for Web UI buttons."""
        return {
            "SEHR_EINFACH": 0.3,
            "EINFACH": 0.5,
            "MITTEL_EINFACH": 0.75,
            "STANDARD": 1.0,
            "MITTEL_SCHWER": 1.25,
            "SCHWER": 1.5,
            "SEHR_SCHWER": 2.0
        }

    def get_cost_table(self, difficulty: float = 1.0) -> Dict[int, Dict[str, Any]]:
        """Get simple cost table for Web UI display."""
        table = {}

        for level in range(1, 12):
            base_cost = self.base_costs[level]
            adjusted_cost = int(base_cost * difficulty)

            table[level] = {
                "level": level,
                "base_cost": base_cost,
                "adjusted_cost": adjusted_cost,
                "difficulty": difficulty,
                "savings_vs_standard": base_cost - adjusted_cost
            }

        return table

# Service instance
_simple_evolution_service = None

def get_simple_evolution_service() -> SimpleEvolutionService:
    """Get singleton simple evolution service."""
    global _simple_evolution_service
    if _simple_evolution_service is None:
        _simple_evolution_service = SimpleEvolutionService()
    return _simple_evolution_service