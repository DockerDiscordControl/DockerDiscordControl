# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""
Monthly Member Cache Service - Provides member count data for dynamic evolution calculations.
"""

import os
import json
import logging
from typing import Dict, Any

logger = logging.getLogger('ddc.monthly_member_cache')

class MonthlyMemberCache:
    """Simple wrapper for monthly member cache data."""

    def __init__(self):
        self.cache_file = os.path.join(os.path.dirname(__file__), 'monthly_member_cache.json')
        self._cache_data = None

    def _load_cache(self) -> Dict[str, Any]:
        """Load cache data from JSON file."""
        if self._cache_data is not None:
            return self._cache_data

        try:
            if os.path.exists(self.cache_file):
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    self._cache_data = json.load(f)
            else:
                self._cache_data = {"member_count": 50, "timestamp": "2025-09-12T13:56:30", "month_year": "2025-09"}
        except (IOError, OSError) as e:
            # File I/O errors (cache file access)
            logger.error(f"File I/O error loading monthly member cache: {e}", exc_info=True)
            self._cache_data = {"member_count": 50, "timestamp": "2025-09-12T13:56:30", "month_year": "2025-09"}
        except json.JSONDecodeError as e:
            # JSON parsing errors (corrupted cache file)
            logger.error(f"JSON parsing error loading monthly member cache: {e}", exc_info=True)
            self._cache_data = {"member_count": 50, "timestamp": "2025-09-12T13:56:30", "month_year": "2025-09"}
        except (KeyError, ValueError, TypeError) as e:
            # Data structure errors (missing keys, invalid values)
            logger.error(f"Data error loading monthly member cache: {e}", exc_info=True)
            self._cache_data = {"member_count": 50, "timestamp": "2025-09-12T13:56:30", "month_year": "2025-09"}

        return self._cache_data

    def get_cache_info(self) -> Dict[str, Any]:
        """Get cache information."""
        data = self._load_cache()
        return {
            "total_members": data.get("member_count", 50),
            "last_updated": data.get("timestamp", "Unknown"),
            "month_year": data.get("month_year", "2025-09")
        }

    def get_member_count(self) -> int:
        """Get current member count."""
        data = self._load_cache()
        return data.get("member_count", 50)

    def get_member_count_for_level(self, level: int) -> int:
        """Get member count for a specific level (compatibility method)."""
        return self.get_member_count()  # Same count for all levels in simple implementation

# Global instance
_monthly_cache_instance = None

def get_monthly_member_cache() -> MonthlyMemberCache:
    """Get the global monthly member cache instance."""
    global _monthly_cache_instance
    if _monthly_cache_instance is None:
        _monthly_cache_instance = MonthlyMemberCache()
    return _monthly_cache_instance