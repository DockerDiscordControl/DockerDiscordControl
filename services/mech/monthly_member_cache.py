#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Monthly Member Count Cache System              #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""
Monthly Member Count Cache System

Caches member counts once per month at random times to avoid performance issues.
Only future evolution levels are affected by member count changes.
"""

import json
import logging
import random
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class MemberCountSnapshot:
    """Snapshot of member count at a specific time."""
    member_count: int
    timestamp: str
    month_year: str  # "2025-01" format
    next_update: str  # When to update next
    levels_affected_from: int  # Which levels are affected by this count
    
class MonthlyMemberCache:
    """Manages monthly member count caching for evolution cost calculations."""
    
    def __init__(self, cache_path: str = "services/mech/monthly_member_cache.json"):
        self.cache_path = Path(cache_path)
        self.current_snapshot: Optional[MemberCountSnapshot] = None
        self._load_cache()
        
    def _load_cache(self) -> None:
        """Load cached member count from file."""
        try:
            if self.cache_path.exists():
                with self.cache_path.open('r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                self.current_snapshot = MemberCountSnapshot(
                    member_count=data.get('member_count', 50),
                    timestamp=data.get('timestamp', ''),
                    month_year=data.get('month_year', ''),
                    next_update=data.get('next_update', ''),
                    levels_affected_from=data.get('levels_affected_from', 1)
                )
                logger.info(f"Loaded member cache: {self.current_snapshot.member_count} members from {self.current_snapshot.month_year}")
            else:
                # Initialize with default
                self._create_default_cache()
                
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Error loading member cache: {e}")
            self._create_default_cache()
    
    def _create_default_cache(self) -> None:
        """Create default cache entry."""
        now = datetime.now()
        next_update = self._calculate_next_random_update(now)
        
        self.current_snapshot = MemberCountSnapshot(
            member_count=50,  # Default medium community
            timestamp=now.isoformat(),
            month_year=now.strftime('%Y-%m'),
            next_update=next_update.isoformat(),
            levels_affected_from=1  # All levels initially
        )
        self._save_cache()
        logger.info("Created default member cache with 50 members")
    
    def _save_cache(self) -> None:
        """Save current snapshot to file."""
        try:
            # Ensure directory exists
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            
            data = {
                'member_count': self.current_snapshot.member_count,
                'timestamp': self.current_snapshot.timestamp,
                'month_year': self.current_snapshot.month_year,
                'next_update': self.current_snapshot.next_update,
                'levels_affected_from': self.current_snapshot.levels_affected_from
            }
            
            with self.cache_path.open('w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                
            logger.debug(f"Saved member cache: {self.current_snapshot.member_count} members")
            
        except (IOError, OSError) as e:
            logger.error(f"Error saving member cache: {e}")
    
    def _calculate_next_random_update(self, current_time: datetime) -> datetime:
        """Calculate next random update time (random day/hour in next month)."""
        # Go to next month
        if current_time.month == 12:
            next_month = current_time.replace(year=current_time.year + 1, month=1, day=1)
        else:
            next_month = current_time.replace(month=current_time.month + 1, day=1)
        
        # Random day in next month (1-28 to avoid month-end issues)
        random_day = random.randint(1, 28)
        random_hour = random.randint(0, 23)
        random_minute = random.randint(0, 59)
        
        next_update = next_month.replace(
            day=random_day, 
            hour=random_hour, 
            minute=random_minute, 
            second=0, 
            microsecond=0
        )
        
        return next_update
    
    def should_update_cache(self) -> bool:
        """Check if it's time for a cache update."""
        if not self.current_snapshot:
            return True
            
        try:
            next_update = datetime.fromisoformat(self.current_snapshot.next_update)
            return datetime.now() >= next_update
        except ValueError:
            return True  # If timestamp is invalid, update
    
    async def update_member_count_if_needed(self, bot=None) -> bool:
        """Update member count if it's time, return True if updated."""
        if not self.should_update_cache():
            return False
            
        if not bot:
            logger.warning("No bot available for member count update")
            return False
            
        try:
            # Get fresh member count
            from .dynamic_evolution import get_evolution_calculator
            calculator = get_evolution_calculator()
            
            # Use timeout to prevent hanging
            member_count = await asyncio.wait_for(
                calculator.get_unique_member_count(bot),
                timeout=10.0  # 10 second timeout for monthly update
            )
            
            # Get current mech level to determine what levels are affected
            from .mech_service import get_mech_service
            mech_service = get_mech_service()
            current_state = mech_service.get_state()
            current_level = current_state.level
            
            # Only future levels are affected
            levels_affected_from = current_level + 1
            
            # Create new snapshot
            now = datetime.now()
            next_update = self._calculate_next_random_update(now)
            
            self.current_snapshot = MemberCountSnapshot(
                member_count=member_count,
                timestamp=now.isoformat(),
                month_year=now.strftime('%Y-%m'),
                next_update=next_update.isoformat(),
                levels_affected_from=levels_affected_from
            )
            
            self._save_cache()
            
            logger.info(
                f"Monthly member count updated: {member_count} members "
                f"(affects levels {levels_affected_from}+, next update: {next_update.strftime('%Y-%m-%d %H:%M')})"
            )
            
            return True
            
        except asyncio.TimeoutError:
            logger.error("Monthly member count update timed out")
            # Schedule retry in 1 hour
            retry_time = datetime.now() + timedelta(hours=1)
            if self.current_snapshot:
                self.current_snapshot.next_update = retry_time.isoformat()
                self._save_cache()
            return False
            
        except Exception as e:
            logger.error(f"Error updating monthly member count: {e}")
            return False
    
    def get_member_count_for_level(self, target_level: int) -> int:
        """Get member count for a specific level, respecting the levels_affected_from rule."""
        if not self.current_snapshot:
            return 50  # Default medium community
            
        # If target level is below the affected threshold, use default/cached value
        if target_level < self.current_snapshot.levels_affected_from:
            # For past levels, use a conservative medium value
            return 50
        
        # For future levels, use the cached member count
        return self.current_snapshot.member_count
    
    def get_cache_info(self) -> Dict[str, Any]:
        """Get information about current cache state."""
        if not self.current_snapshot:
            return {'status': 'no_cache'}
            
        try:
            next_update = datetime.fromisoformat(self.current_snapshot.next_update)
            time_until_update = next_update - datetime.now()
            
            return {
                'status': 'active',
                'member_count': self.current_snapshot.member_count,
                'cached_since': self.current_snapshot.timestamp,
                'month_year': self.current_snapshot.month_year,
                'next_update': self.current_snapshot.next_update,
                'days_until_update': max(0, time_until_update.days),
                'levels_affected_from': self.current_snapshot.levels_affected_from,
                'should_update': self.should_update_cache()
            }
        except ValueError:
            return {'status': 'invalid_cache'}

# Global instance
_monthly_cache_instance = None

def get_monthly_member_cache() -> MonthlyMemberCache:
    """Get the singleton monthly member cache instance."""
    global _monthly_cache_instance
    if _monthly_cache_instance is None:
        _monthly_cache_instance = MonthlyMemberCache()
    return _monthly_cache_instance