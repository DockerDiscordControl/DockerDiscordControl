#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Mech Data Store Service                        #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""
MechDataStore - Centralized Single Source of Truth for ALL Mech Data

This service consolidates all mech-related data queries into a single,
consistent, cached interface. Instead of multiple services calculating
the same data independently, everything flows through this data store.

Architecture:
- Single Point of Truth: Uses donation history as primary data source
- Intelligent Caching: Reduces redundant calculations
- SERVICE FIRST: Clean Request/Result patterns
- Comprehensive API: All mech data queries in one place

Usage:
    store = get_mech_data_store()
    data = store.get_comprehensive_data(request)
    level = data.current_level
    power = data.current_power
"""

import logging
import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class BarsCompat:
    """Legacy compatibility object for bars data."""
    Power_current: float = 0.0  # Support decimal power values (e.g. 0.99)
    Power_max_for_level: int = 100
    mech_progress_current: float = 0.0  # Changed to float for decimal values
    mech_progress_max: float = 20.0  # Changed to float for decimal values


# ============================================================================ #
#                              REQUEST DATACLASSES                            #
# ============================================================================ #

@dataclass(frozen=True)
class MechDataRequest:
    """Comprehensive request for mech data with various options."""
    include_decimals: bool = False
    force_refresh: bool = False
    include_projections: bool = False
    language: str = "en"
    projection_hours: float = 24.0

@dataclass(frozen=True)
class LevelDataRequest:
    """Request for level-specific data only."""
    force_refresh: bool = False

@dataclass(frozen=True)
class PowerDataRequest:
    """Request for power-specific data only."""
    include_decimals: bool = False
    force_refresh: bool = False

@dataclass(frozen=True)
class EvolutionDataRequest:
    """Request for evolution-specific data only."""
    force_refresh: bool = False
    language: str = "en"

@dataclass(frozen=True)
class SpeedDataRequest:
    """Request for speed-specific data only."""
    force_refresh: bool = False
    language: str = "en"

@dataclass(frozen=True)
class DecayDataRequest:
    """Request for decay-specific data only."""
    force_refresh: bool = False

@dataclass(frozen=True)
class ProjectionDataRequest:
    """Request for power projection data."""
    hours_ahead: float = 24.0
    force_refresh: bool = False

# ============================================================================ #
#                              RESULT DATACLASSES                             #
# ============================================================================ #

@dataclass(frozen=True)
class MechDataResult:
    """Comprehensive result containing all mech data."""
    success: bool

    # Core data
    current_level: int = 1
    current_power: float = 0.0
    total_donated: float = 0.0

    # Evolution data
    level_name: str = ""
    next_level: int = 2
    next_level_name: str = ""
    next_threshold: float = 20.0
    next_level_threshold: float = 20.0  # Alias for compatibility
    amount_needed: float = 20.0

    # Speed data
    speed_level: int = 0
    speed_description: str = "OFFLINE"
    speed_color: str = "#888888"

    # Decay data
    decay_rate: float = 1.0
    decay_per_hour: float = 0.041666
    is_immortal: bool = False

    # Progression data
    progress_current: int = 0
    progress_max: int = 20
    progress_percentage: float = 0.0

    # Technical data
    evolution_mode: str = "dynamic"  # "dynamic" or "static"
    difficulty_multiplier: float = 1.0
    cache_timestamp: Optional[float] = None

    # Optional projection data
    projections: Optional[Dict[str, Any]] = None

    # Legacy compatibility
    bars: Optional[Any] = None

    # Error handling
    error: Optional[str] = None

@dataclass(frozen=True)
class LevelDataResult:
    """Result containing level-specific data only."""
    success: bool
    current_level: int = 1
    level_name: str = ""
    next_level: int = 2
    next_level_name: str = ""
    error: Optional[str] = None

@dataclass(frozen=True)
class PowerDataResult:
    """Result containing power-specific data only."""
    success: bool
    current_power: float = 0.0
    total_donated: float = 0.0
    progress_current: int = 0
    progress_max: int = 20
    progress_percentage: float = 0.0
    error: Optional[str] = None

@dataclass(frozen=True)
class EvolutionDataResult:
    """Result containing evolution-specific data only."""
    success: bool
    current_level: int = 1
    level_name: str = ""
    next_threshold: float = 20.0
    next_level_threshold: float = 20.0  # Compatibility alias
    amount_needed: float = 20.0
    evolution_mode: str = "dynamic"
    difficulty_multiplier: float = 1.0
    error: Optional[str] = None

@dataclass(frozen=True)
class SpeedDataResult:
    """Result containing speed-specific data only."""
    success: bool
    speed_level: int = 0
    speed_description: str = "OFFLINE"
    speed_color: str = "#888888"
    error: Optional[str] = None

@dataclass(frozen=True)
class DecayDataResult:
    """Result containing decay-specific data only."""
    success: bool
    decay_rate: float = 1.0
    decay_per_hour: float = 0.041666
    is_immortal: bool = False
    survival_hours: Optional[float] = None
    error: Optional[str] = None

@dataclass(frozen=True)
class ProjectionDataResult:
    """Result containing power projection data."""
    success: bool
    projected_power: float = 0.0
    hours_until_zero: Optional[float] = None
    survival_category: str = "unknown"
    projections: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

# ============================================================================ #
#                              MECHDATASTORE CLASS                            #
# ============================================================================ #

class MechDataStore:
    """
    Centralized Single Source of Truth for ALL Mech Data.

    This service consolidates all mech-related calculations and queries
    into a single, consistent, cached interface.
    """

    def __init__(self):
        """Initialize the MechDataStore."""
        self.logger = logger

        # Intelligent caching
        self._cache = {}
        self._cache_ttl = 10.0  # 10 seconds default cache
        self._last_cache_clear = time.time()

        self.logger.info("MechDataStore initialized with intelligent caching")

    # ========================================================================
    #                          PUBLIC API METHODS
    # ========================================================================

    def get_comprehensive_data(self, request: MechDataRequest) -> MechDataResult:
        """
        Get comprehensive mech data including all available information.

        This is the primary method that provides all mech data in a single call.
        Other specialized methods use this internally for consistency.

        Args:
            request: MechDataRequest with query options

        Returns:
            MechDataResult with all mech data or error information
        """
        try:
            cache_key = f"comprehensive_{request.include_decimals}_{request.language}"

            # Check cache first (unless force refresh)
            if not request.force_refresh:
                cached_data = self._get_from_cache(cache_key)
                if cached_data is not None:
                    self.logger.debug("Returning cached comprehensive data")
                    return cached_data

            # Calculate fresh data
            self.logger.debug("Calculating fresh comprehensive mech data")

            # Step 1: Get core mech state from Single Point of Truth
            core_data = self._get_core_mech_data()
            if not core_data['success']:
                return MechDataResult(success=False, error=core_data['error'])

            # Step 2: Calculate evolution information
            evolution_data = self._calculate_evolution_data(core_data)

            # Step 3: Calculate speed information
            speed_data = self._calculate_speed_data(core_data, request.language)

            # Step 4: Calculate decay information
            decay_data = self._calculate_decay_data(core_data)

            # Step 5: Calculate progression information
            progress_data = self._calculate_progress_data(core_data, evolution_data)

            # Step 6: Get technical information
            technical_data = self._get_technical_data()

            # Step 7: Calculate projections if requested
            projections = None
            if request.include_projections:
                projections = self._calculate_projections(core_data, decay_data, request.projection_hours)

            # Combine all data into comprehensive result
            result = MechDataResult(
                success=True,

                # Core data
                current_level=core_data['level'],
                current_power=core_data['power'],
                total_donated=core_data['total_donated'],

                # Evolution data
                level_name=evolution_data['level_name'],
                next_level=evolution_data['next_level'],
                next_level_name=evolution_data['next_level_name'],
                next_threshold=evolution_data['next_threshold'],
                next_level_threshold=evolution_data['next_threshold'],  # Compatibility alias
                amount_needed=evolution_data['amount_needed'],

                # Speed data
                speed_level=speed_data['speed_level'],
                speed_description=speed_data['speed_description'],
                speed_color=speed_data['speed_color'],

                # Decay data
                decay_rate=decay_data['decay_rate'],
                decay_per_hour=decay_data['decay_per_hour'],
                is_immortal=decay_data['is_immortal'],

                # Progress data
                progress_current=progress_data['progress_current'],
                progress_max=progress_data['progress_max'],
                progress_percentage=progress_data['progress_percentage'],

                # Technical data
                evolution_mode=technical_data['evolution_mode'],
                difficulty_multiplier=technical_data['difficulty_multiplier'],
                cache_timestamp=time.time(),

                # Legacy compatibility - separate Power Bar and Evolution Bar calculations
                bars=self._calculate_power_bars(core_data, evolution_data, progress_data),

                # Optional projections
                projections=projections
            )

            # Cache the result
            self._store_in_cache(cache_key, result)

            return result

        except (ImportError, AttributeError) as e:
            # Service dependency errors (progress service, mech service unavailable)
            self.logger.error(f"Service dependency error in get_comprehensive_data: {e}", exc_info=True)
            return MechDataResult(
                success=False,
                error=f"Service dependency error: {str(e)}"
            )
        except (ValueError, TypeError, KeyError) as e:
            # Data processing errors (calculation, parsing, dictionary access)
            self.logger.error(f"Data processing error in get_comprehensive_data: {e}", exc_info=True)
            return MechDataResult(
                success=False,
                error=f"Data processing error: {str(e)}"
            )
        except RuntimeError as e:
            # Runtime errors (service call failures, etc.)
            self.logger.error(f"Runtime error in get_comprehensive_data: {e}", exc_info=True)
            return MechDataResult(
                success=False,
                error=f"Runtime error: {str(e)}"
            )

    def get_level_info(self, request: LevelDataRequest) -> LevelDataResult:
        """Get level-specific information only."""
        try:
            # Use comprehensive data but return only level info
            comprehensive_request = MechDataRequest(force_refresh=request.force_refresh)
            comprehensive_data = self.get_comprehensive_data(comprehensive_request)

            if not comprehensive_data.success:
                return LevelDataResult(success=False, error=comprehensive_data.error)

            return LevelDataResult(
                success=True,
                current_level=comprehensive_data.current_level,
                level_name=comprehensive_data.level_name,
                next_level=comprehensive_data.next_level,
                next_level_name=comprehensive_data.next_level_name
            )

        except (ImportError, AttributeError, ValueError, TypeError, KeyError, RuntimeError) as e:
            # Service or data errors (delegated to get_comprehensive_data)
            self.logger.error(f"Error in get_level_info: {e}", exc_info=True)
            return LevelDataResult(success=False, error=str(e))

    def get_power_info(self, request: PowerDataRequest) -> PowerDataResult:
        """Get power-specific information only."""
        try:
            comprehensive_request = MechDataRequest(
                include_decimals=request.include_decimals,
                force_refresh=request.force_refresh
            )
            comprehensive_data = self.get_comprehensive_data(comprehensive_request)

            if not comprehensive_data.success:
                return PowerDataResult(success=False, error=comprehensive_data.error)

            return PowerDataResult(
                success=True,
                current_power=comprehensive_data.current_power,
                total_donated=comprehensive_data.total_donated,
                progress_current=comprehensive_data.progress_current,
                progress_max=comprehensive_data.progress_max,
                progress_percentage=comprehensive_data.progress_percentage
            )

        except (ImportError, AttributeError, ValueError, TypeError, KeyError, RuntimeError) as e:
            # Service or data errors (delegated to get_comprehensive_data)
            self.logger.error(f"Error in get_power_info: {e}", exc_info=True)
            return PowerDataResult(success=False, error=str(e))

    def get_evolution_info(self, request: EvolutionDataRequest) -> EvolutionDataResult:
        """Get evolution-specific information only."""
        try:
            comprehensive_request = MechDataRequest(
                force_refresh=request.force_refresh,
                language=request.language
            )
            comprehensive_data = self.get_comprehensive_data(comprehensive_request)

            if not comprehensive_data.success:
                return EvolutionDataResult(success=False, error=comprehensive_data.error)

            return EvolutionDataResult(
                success=True,
                current_level=comprehensive_data.current_level,
                level_name=comprehensive_data.level_name,
                next_threshold=comprehensive_data.next_threshold,
                next_level_threshold=comprehensive_data.next_threshold,  # Compatibility alias
                amount_needed=comprehensive_data.amount_needed,
                evolution_mode=comprehensive_data.evolution_mode,
                difficulty_multiplier=comprehensive_data.difficulty_multiplier
            )

        except (ImportError, AttributeError, ValueError, TypeError, KeyError, RuntimeError) as e:
            # Service or data errors (delegated to get_comprehensive_data)
            self.logger.error(f"Error in get_evolution_info: {e}", exc_info=True)
            return EvolutionDataResult(success=False, error=str(e))

    def get_speed_info(self, request: SpeedDataRequest) -> SpeedDataResult:
        """Get speed-specific information only."""
        try:
            comprehensive_request = MechDataRequest(
                force_refresh=request.force_refresh,
                language=request.language
            )
            comprehensive_data = self.get_comprehensive_data(comprehensive_request)

            if not comprehensive_data.success:
                return SpeedDataResult(success=False, error=comprehensive_data.error)

            return SpeedDataResult(
                success=True,
                speed_level=comprehensive_data.speed_level,
                speed_description=comprehensive_data.speed_description,
                speed_color=comprehensive_data.speed_color
            )

        except (ImportError, AttributeError, ValueError, TypeError, KeyError, RuntimeError) as e:
            # Service or data errors (delegated to get_comprehensive_data)
            self.logger.error(f"Error in get_speed_info: {e}", exc_info=True)
            return SpeedDataResult(success=False, error=str(e))

    def get_decay_info(self, request: DecayDataRequest) -> DecayDataResult:
        """Get decay-specific information only."""
        try:
            comprehensive_request = MechDataRequest(force_refresh=request.force_refresh)
            comprehensive_data = self.get_comprehensive_data(comprehensive_request)

            if not comprehensive_data.success:
                return DecayDataResult(success=False, error=comprehensive_data.error)

            # Calculate survival hours if not immortal
            survival_hours = None
            if not comprehensive_data.is_immortal and comprehensive_data.current_power > 0:
                survival_hours = comprehensive_data.current_power / comprehensive_data.decay_per_hour

            return DecayDataResult(
                success=True,
                decay_rate=comprehensive_data.decay_rate,
                decay_per_hour=comprehensive_data.decay_per_hour,
                is_immortal=comprehensive_data.is_immortal,
                survival_hours=survival_hours
            )

        except (ImportError, AttributeError, ValueError, TypeError, KeyError, RuntimeError) as e:
            # Service or data errors (delegated to get_comprehensive_data)
            self.logger.error(f"Error in get_decay_info: {e}", exc_info=True)
            return DecayDataResult(success=False, error=str(e))

    def get_projections(self, request: ProjectionDataRequest) -> ProjectionDataResult:
        """Get power projection data."""
        try:
            comprehensive_request = MechDataRequest(
                force_refresh=request.force_refresh,
                include_projections=True,
                projection_hours=request.hours_ahead
            )
            comprehensive_data = self.get_comprehensive_data(comprehensive_request)

            if not comprehensive_data.success:
                return ProjectionDataResult(success=False, error=comprehensive_data.error)

            projections = comprehensive_data.projections or {}

            return ProjectionDataResult(
                success=True,
                projected_power=projections.get('projected_power', comprehensive_data.current_power),
                hours_until_zero=projections.get('hours_until_zero'),
                survival_category=projections.get('survival_category', 'unknown'),
                projections=projections
            )

        except (ImportError, AttributeError, ValueError, TypeError, KeyError, RuntimeError) as e:
            # Service or data errors (delegated to get_comprehensive_data)
            self.logger.error(f"Error in get_projections: {e}", exc_info=True)
            return ProjectionDataResult(success=False, error=str(e))

    # ========================================================================
    #                           PRIVATE HELPER METHODS
    # ========================================================================

    def _get_core_mech_data(self) -> Dict[str, Any]:
        """Get core mech data from Single Point of Truth (mech_service)."""
        try:
            from services.mech.mech_service import get_mech_service, GetMechStateRequest

            mech_service = get_mech_service()
            request = GetMechStateRequest(include_decimals=True)
            result = mech_service.get_mech_state_service(request)

            if not result.success:
                return {'success': False, 'error': f'Failed to get mech state: {result.error_message}'}

            return {
                'success': True,
                'level': result.level,
                'power': result.power,
                'total_donated': result.total_donated
            }

        except (ImportError, AttributeError) as e:
            # Service dependency errors (mech service unavailable)
            self.logger.error(f"Service dependency error getting core mech data: {e}", exc_info=True)
            return {'success': False, 'error': str(e)}
        except (ValueError, TypeError, KeyError) as e:
            # Data access errors (result object access)
            self.logger.error(f"Data access error getting core mech data: {e}", exc_info=True)
            return {'success': False, 'error': str(e)}

    def _calculate_evolution_data(self, core_data: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate evolution-related data from progress service."""
        try:
            # Get data from progress service (NEW dynamic evolution system)
            from services.mech.progress_service import get_progress_service
            from services.mech.mech_levels import get_level_name

            prog_service = get_progress_service()
            prog_state = prog_service.get_state()

            current_level = prog_state.level
            next_level = min(current_level + 1, 11)

            return {
                'level_name': get_level_name(current_level),
                'next_level': next_level,
                'next_level_name': get_level_name(next_level),
                'next_threshold': prog_state.evo_max,  # Dynamic threshold from progress service
                'amount_needed': max(0, prog_state.evo_max - prog_state.evo_current)
            }

        except (ImportError, AttributeError) as e:
            # Service dependency errors (progress service, mech_levels unavailable)
            self.logger.error(f"Service dependency error calculating evolution data: {e}", exc_info=True)
            return {
                'level_name': f"Level {core_data['level']}",
                'next_level': core_data['level'] + 1,
                'next_level_name': 'Next Level',
                'next_threshold': 0,
                'amount_needed': 0
            }
        except (ValueError, TypeError, KeyError) as e:
            # Data access/calculation errors
            self.logger.error(f"Data error calculating evolution data: {e}", exc_info=True)
            return {
                'level_name': f"Level {core_data['level']}",
                'next_level': core_data['level'] + 1,
                'next_level_name': 'Next Level',
                'next_threshold': 0,
                'amount_needed': 0
            }

    def _calculate_speed_data(self, core_data: Dict[str, Any], language: str) -> Dict[str, Any]:
        """Calculate speed-related data using get_combined_mech_status (Single Point of Truth)."""
        try:
            from services.mech.speed_levels import get_combined_mech_status

            # Use get_combined_mech_status with proper parameters:
            # - Power_amount: current power (after decay)
            # - total_donations_received: total donations (for correct evolution level)
            combined_status = get_combined_mech_status(
                Power_amount=core_data['power'],
                total_donations_received=core_data.get('total_donated', core_data['power']),
                language=language
            )

            return {
                'speed_level': combined_status['speed']['level'],
                'speed_description': combined_status['speed']['description'],
                'speed_color': combined_status['speed']['color']
            }

        except (ImportError, AttributeError) as e:
            # Service dependency errors (speed_levels, mech_evolutions unavailable)
            self.logger.error(f"Service dependency error calculating speed data: {e}", exc_info=True)
            return {
                'speed_level': 0,
                'speed_description': 'OFFLINE',
                'speed_color': '#888888'
            }
        except (ValueError, TypeError, KeyError) as e:
            # Data access/calculation errors
            self.logger.error(f"Data error calculating speed data: {e}", exc_info=True)
            return {
                'speed_level': 0,
                'speed_description': 'OFFLINE',
                'speed_color': '#888888'
            }

    def _calculate_decay_data(self, core_data: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate decay-related data."""
        try:
            from services.mech.mech_evolutions import get_evolution_level_info

            evolution_level_info = get_evolution_level_info(core_data['level'])
            if evolution_level_info:
                decay_rate = evolution_level_info.decay_per_day
            else:
                decay_rate = 1.0  # Default fallback

            decay_per_hour = decay_rate / 24.0
            is_immortal = decay_rate <= 0.0

            return {
                'decay_rate': decay_rate,
                'decay_per_hour': decay_per_hour,
                'is_immortal': is_immortal
            }

        except (ImportError, AttributeError) as e:
            # Service dependency errors (mech_evolutions unavailable)
            self.logger.error(f"Service dependency error calculating decay data: {e}", exc_info=True)
            return {
                'decay_rate': 1.0,
                'decay_per_hour': 0.041666,
                'is_immortal': False
            }
        except (ValueError, TypeError, KeyError) as e:
            # Data access/calculation errors
            self.logger.error(f"Data error calculating decay data: {e}", exc_info=True)
            return {
                'decay_rate': 1.0,
                'decay_per_hour': 0.041666,
                'is_immortal': False
            }

    def _calculate_progress_data(self, core_data: Dict[str, Any], evolution_data: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate progression-related data."""
        try:
            current_threshold = 0
            next_threshold = evolution_data['next_threshold']

            # Calculate how much progress towards next level
            if next_threshold > 0:
                progress_max = int(next_threshold - current_threshold)
                progress_current = min(int(core_data['total_donated'] - current_threshold), progress_max)
                progress_percentage = (progress_current / progress_max * 100.0) if progress_max > 0 else 0.0
            else:
                # Max level reached
                progress_max = 100
                progress_current = 100
                progress_percentage = 100.0

            return {
                'progress_current': progress_current,
                'progress_max': progress_max,
                'progress_percentage': progress_percentage
            }

        except (ValueError, TypeError, KeyError, ZeroDivisionError) as e:
            # Data access/calculation errors (division by zero, etc.)
            self.logger.error(f"Data error calculating progress data: {e}", exc_info=True)
            return {
                'progress_current': 0,
                'progress_max': 20,
                'progress_percentage': 0.0
            }

    def _get_technical_data(self) -> Dict[str, Any]:
        """Get technical configuration data."""
        try:
            from services.mech.mech_service import get_mech_service

            mech_service = get_mech_service()
            evolution_mode = mech_service._get_evolution_mode()

            return {
                'evolution_mode': 'dynamic' if evolution_mode.get('use_dynamic', True) else 'static',
                'difficulty_multiplier': evolution_mode.get('difficulty_multiplier', 1.0)
            }

        except (ImportError, AttributeError) as e:
            # Service dependency errors (mech service unavailable)
            self.logger.error(f"Service dependency error getting technical data: {e}", exc_info=True)
            return {
                'evolution_mode': 'dynamic',
                'difficulty_multiplier': 1.0
            }
        except (ValueError, TypeError, KeyError) as e:
            # Data access errors
            self.logger.error(f"Data error getting technical data: {e}", exc_info=True)
            return {
                'evolution_mode': 'dynamic',
                'difficulty_multiplier': 1.0
            }

    def _calculate_projections(self, core_data: Dict[str, Any], decay_data: Dict[str, Any], hours_ahead: float) -> Dict[str, Any]:
        """Calculate power projections."""
        try:
            current_power = core_data['power']
            decay_per_hour = decay_data['decay_per_hour']

            # Calculate projected power
            projected_power = max(0.0, current_power - (decay_per_hour * hours_ahead))

            # Calculate hours until zero
            hours_until_zero = None
            if not decay_data['is_immortal'] and current_power > 0 and decay_per_hour > 0:
                hours_until_zero = current_power / decay_per_hour

            # Determine survival category
            survival_category = 'immortal'
            if hours_until_zero is not None:
                if hours_until_zero <= 1:
                    survival_category = 'critical'
                elif hours_until_zero <= 6:
                    survival_category = 'urgent'
                elif hours_until_zero <= 24:
                    survival_category = 'warning'
                elif hours_until_zero <= 72:
                    survival_category = 'stable'
                else:
                    survival_category = 'healthy'

            return {
                'projected_power': projected_power,
                'hours_until_zero': hours_until_zero,
                'survival_category': survival_category,
                'projection_hours': hours_ahead
            }

        except (ValueError, TypeError, KeyError, ZeroDivisionError) as e:
            # Data access/calculation errors (division by zero, etc.)
            self.logger.error(f"Data error calculating projections: {e}", exc_info=True)
            return {
                'projected_power': core_data['power'],
                'hours_until_zero': None,
                'survival_category': 'unknown',
                'projection_hours': hours_ahead
            }

    # ========================================================================
    #                            CACHING METHODS
    # ========================================================================

    def _get_from_cache(self, key: str) -> Optional[MechDataResult]:
        """Get data from cache if valid."""
        if key not in self._cache:
            return None

        cache_entry = self._cache[key]
        cache_time = cache_entry.get('timestamp', 0)

        # Check if cache is still valid
        if time.time() - cache_time < self._cache_ttl:
            return cache_entry.get('data')

        # Cache expired, remove entry
        del self._cache[key]
        return None

    def _store_in_cache(self, key: str, data: MechDataResult) -> None:
        """Store data in cache."""
        self._cache[key] = {
            'data': data,
            'timestamp': time.time()
        }

        # Periodic cache cleanup (every 5 minutes)
        if time.time() - self._last_cache_clear > 300:
            self._cleanup_cache()

    def _cleanup_cache(self) -> None:
        """Clean up expired cache entries."""
        current_time = time.time()
        expired_keys = []

        for key, entry in self._cache.items():
            if current_time - entry.get('timestamp', 0) >= self._cache_ttl:
                expired_keys.append(key)

        for key in expired_keys:
            del self._cache[key]

        self._last_cache_clear = current_time
        self.logger.debug(f"Cache cleanup: removed {len(expired_keys)} expired entries")

    def clear_cache(self) -> None:
        """Manually clear all cache entries."""
        self._cache.clear()
        self._last_cache_clear = time.time()
        self.logger.info("Manual cache clear performed")

    def _calculate_power_bars(self, core_data: dict, evolution_data: dict, progress_data: dict) -> BarsCompat:
        """Calculate power bars from progress service data."""
        try:
            # Get data from progress service (NEW dynamic evolution system)
            from services.mech.progress_service import get_progress_service

            prog_service = get_progress_service()
            prog_state = prog_service.get_state()

            return BarsCompat(
                # Power Bar: Show current power vs. max power for CURRENT level
                Power_current=prog_state.power_current,
                Power_max_for_level=prog_state.power_max,

                # Evolution Bar: Show progress toward next level threshold
                mech_progress_current=prog_state.evo_current,
                mech_progress_max=prog_state.evo_max
            )

        except (ImportError, AttributeError) as e:
            # Service dependency errors (progress service unavailable)
            self.logger.error(f"Service dependency error in _calculate_power_bars: {e}", exc_info=True)
            # Return safe fallback values
            return BarsCompat(
                Power_current=core_data.get('power', 0.0),
                Power_max_for_level=50,  # Safe fallback
                mech_progress_current=0,
                mech_progress_max=100
            )
        except (ValueError, TypeError, KeyError) as e:
            # Data access errors
            self.logger.error(f"Data error in _calculate_power_bars: {e}", exc_info=True)
            # Return safe fallback values
            return BarsCompat(
                Power_current=core_data.get('power', 0.0),
                Power_max_for_level=50,  # Safe fallback
                mech_progress_current=0,
                mech_progress_max=100
            )


# ============================================================================ #
#                              SINGLETON FACTORY                              #
# ============================================================================ #

_mech_data_store_instance: Optional[MechDataStore] = None

def get_mech_data_store() -> MechDataStore:
    """Get or create the singleton MechDataStore instance."""
    global _mech_data_store_instance
    if _mech_data_store_instance is None:
        _mech_data_store_instance = MechDataStore()
    return _mech_data_store_instance
