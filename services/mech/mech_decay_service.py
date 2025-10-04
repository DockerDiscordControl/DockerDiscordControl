#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Mech Decay Service                             #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""
Mech Decay Service - Handles all power decay calculations and logic
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class DecayCalculationRequest:
    """Represents a decay calculation request."""
    start_time: datetime
    end_time: datetime
    mech_level: int


@dataclass
class DecayInfoRequest:
    """Represents a decay information request."""
    mech_level: int


@dataclass
class PowerProjectionRequest:
    """Represents a power projection request."""
    current_power: float
    mech_level: int
    hours_ahead: float = 24.0


@dataclass
class DecayCalculationResult:
    """Represents the result of decay calculation."""
    success: bool
    decay_amount: Optional[float] = None
    seconds_elapsed: Optional[float] = None
    decay_rate_per_day: Optional[float] = None
    error: Optional[str] = None


@dataclass
class DecayInfoResult:
    """Represents the result of decay information query."""
    success: bool
    decay_info: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


@dataclass
class PowerProjectionResult:
    """Represents the result of power projection."""
    success: bool
    projected_power: Optional[float] = None
    time_until_zero: Optional[float] = None  # Hours until power reaches 0
    survival_info: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class MechDecayService:
    """Service for handling all mech power decay calculations and logic."""

    def __init__(self):
        self.logger = logger

    def calculate_decay_amount(self, request: DecayCalculationRequest) -> DecayCalculationResult:
        """
        Calculate power decay amount between two timestamps for a specific mech level.

        Args:
            request: DecayCalculationRequest with start/end times and mech level

        Returns:
            DecayCalculationResult with decay amount or error information
        """
        try:
            # Step 1: Calculate time difference in seconds
            time_info = self._calculate_time_difference(request.start_time, request.end_time)
            if time_info['seconds'] <= 0:
                return DecayCalculationResult(
                    success=True,
                    decay_amount=0.0,
                    seconds_elapsed=0.0,
                    decay_rate_per_day=self._get_decay_rate_for_level(request.mech_level)
                )

            # Step 2: Get level-specific decay rate
            decay_rate = self._get_decay_rate_for_level(request.mech_level)

            # Step 3: Calculate decay amount
            decay_amount = self._perform_decay_calculation(time_info['seconds'], decay_rate)

            return DecayCalculationResult(
                success=True,
                decay_amount=decay_amount,
                seconds_elapsed=time_info['seconds'],
                decay_rate_per_day=decay_rate
            )

        except Exception as e:
            self.logger.error(f"Error calculating decay amount: {e}", exc_info=True)
            return DecayCalculationResult(
                success=False,
                error=f"Error calculating decay: {str(e)}"
            )

    def get_decay_info_for_level(self, request: DecayInfoRequest) -> DecayInfoResult:
        """
        Get comprehensive decay information for a specific mech level.

        Args:
            request: DecayInfoRequest with mech level

        Returns:
            DecayInfoResult with decay information or error
        """
        try:
            # Step 1: Get level-specific decay rate
            decay_rate = self._get_decay_rate_for_level(request.mech_level)

            # Step 2: Get evolution information
            evolution_info = self._get_evolution_information(request.mech_level)

            # Step 3: Calculate survival times and thresholds
            survival_info = self._calculate_survival_information(decay_rate)

            # Step 4: Build comprehensive decay info
            decay_info = {
                'mech_level': request.mech_level,
                'decay_per_day': decay_rate,
                'decay_per_hour': decay_rate / 24.0,
                'decay_per_minute': decay_rate / (24.0 * 60.0),
                'evolution_name': evolution_info.get('name', f'Level {request.mech_level}'),
                'evolution_color': evolution_info.get('color', '#888888'),
                'is_immortal': decay_rate <= 0.0,
                'survival_from_1_power': survival_info['hours_from_1_power'],
                'survival_from_full_power': survival_info['hours_from_full_power'],
                'relative_decay_speed': decay_rate,  # Relative to Level 1 (1.0 = normal)
                'decay_speed_description': self._get_decay_speed_description(decay_rate)
            }

            return DecayInfoResult(
                success=True,
                decay_info=decay_info
            )

        except Exception as e:
            self.logger.error(f"Error getting decay info for level {request.mech_level}: {e}", exc_info=True)
            return DecayInfoResult(
                success=False,
                error=f"Error getting decay info: {str(e)}"
            )

    def project_power_over_time(self, request: PowerProjectionRequest) -> PowerProjectionResult:
        """
        Project power levels over time and calculate survival information.

        Args:
            request: PowerProjectionRequest with current power, level, and projection time

        Returns:
            PowerProjectionResult with projected power and survival data
        """
        try:
            # Step 1: Get decay rate for level
            decay_rate = self._get_decay_rate_for_level(request.mech_level)

            # Step 2: Calculate projected power
            projected_power = self._calculate_projected_power(
                request.current_power,
                decay_rate,
                request.hours_ahead
            )

            # Step 3: Calculate time until power reaches zero
            time_until_zero = self._calculate_time_until_zero(request.current_power, decay_rate)

            # Step 4: Build survival information
            survival_info = self._build_survival_information(
                request.current_power,
                decay_rate,
                time_until_zero,
                request.mech_level
            )

            return PowerProjectionResult(
                success=True,
                projected_power=max(0.0, projected_power),
                time_until_zero=time_until_zero,
                survival_info=survival_info
            )

        except Exception as e:
            self.logger.error(f"Error projecting power over time: {e}", exc_info=True)
            return PowerProjectionResult(
                success=False,
                error=f"Error projecting power: {str(e)}"
            )

    def apply_decay_to_power(self, current_power: float, mech_level: int, start_time: datetime, end_time: datetime) -> float:
        """
        Apply decay to current power and return the new power level.

        Args:
            current_power: Current power level
            mech_level: Mech evolution level
            start_time: Start time for decay calculation
            end_time: End time for decay calculation

        Returns:
            New power level after applying decay (>= 0.0)
        """
        try:
            request = DecayCalculationRequest(
                start_time=start_time,
                end_time=end_time,
                mech_level=mech_level
            )

            result = self.calculate_decay_amount(request)

            if not result.success or result.decay_amount is None:
                self.logger.warning(f"Failed to calculate decay, returning original power: {result.error}")
                return current_power

            new_power = max(0.0, current_power - result.decay_amount)
            return new_power

        except Exception as e:
            self.logger.error(f"Error applying decay to power: {e}")
            return current_power

    def _calculate_time_difference(self, start_time: datetime, end_time: datetime) -> Dict[str, float]:
        """Calculate time difference ensuring proper timezone handling."""
        # Ensure both times are timezone-aware
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)
        if end_time.tzinfo is None:
            end_time = end_time.replace(tzinfo=timezone.utc)

        # Convert to same timezone for calculation
        start_utc = start_time.astimezone(timezone.utc)
        end_utc = end_time.astimezone(timezone.utc)

        seconds = (end_utc - start_utc).total_seconds()

        return {
            'seconds': max(0.0, seconds),
            'hours': max(0.0, seconds / 3600.0),
            'days': max(0.0, seconds / 86400.0)
        }

    def _get_decay_rate_for_level(self, level: int) -> float:
        """Get decay rate for specific mech level."""
        try:
            from services.mech.evolution_config_manager import get_evolution_config_manager
            config_mgr = get_evolution_config_manager()
            evolution = config_mgr.get_evolution_level(level)

            return evolution.decay_per_day if evolution else 1.0

        except Exception as e:
            self.logger.error(f"Error getting decay rate for level {level}: {e}")
            return 1.0  # Default fallback

    def _perform_decay_calculation(self, seconds: float, decay_rate_per_day: float) -> float:
        """Perform the actual decay calculation."""
        # Calculate decay: (seconds / seconds_per_day) * decay_rate
        seconds_per_day = 86400.0
        decay_amount = (seconds / seconds_per_day) * decay_rate_per_day
        return max(0.0, decay_amount)

    def _get_evolution_information(self, level: int) -> Dict[str, Any]:
        """Get evolution information for level."""
        try:
            from services.mech.evolution_config_manager import get_evolution_config_manager
            config_mgr = get_evolution_config_manager()
            evolution = config_mgr.get_evolution_level(level)

            if evolution:
                return {
                    'name': evolution.name,
                    'color': evolution.color,
                    'power_max': evolution.power_max
                }
            else:
                return {
                    'name': f'Level {level}',
                    'color': '#888888',
                    'power_max': 100
                }

        except Exception as e:
            self.logger.error(f"Error getting evolution info for level {level}: {e}")
            return {
                'name': f'Level {level}',
                'color': '#888888',
                'power_max': 100
            }

    def _calculate_survival_information(self, decay_rate: float) -> Dict[str, float]:
        """Calculate survival time information."""
        if decay_rate <= 0:
            # Immortal mech
            return {
                'hours_from_1_power': float('inf'),
                'hours_from_full_power': float('inf')
            }

        # Hours to survive from 1.0 power
        hours_from_1_power = 24.0 / decay_rate  # 24 hours per day / decay_per_day

        # Assume "full power" is ~100 for estimation
        hours_from_full_power = (100.0 * 24.0) / decay_rate

        return {
            'hours_from_1_power': hours_from_1_power,
            'hours_from_full_power': hours_from_full_power
        }

    def _get_decay_speed_description(self, decay_rate: float) -> str:
        """Get human-readable description of decay speed."""
        if decay_rate <= 0:
            return "Immortal (no decay)"
        elif decay_rate == 1.0:
            return "Normal decay speed"
        elif decay_rate < 1.0:
            return f"Slow decay ({decay_rate}x normal)"
        elif decay_rate <= 2.0:
            return f"Fast decay ({decay_rate}x normal)"
        elif decay_rate <= 4.0:
            return f"Very fast decay ({decay_rate}x normal)"
        else:
            return f"Extreme decay ({decay_rate}x normal)"

    def _calculate_projected_power(self, current_power: float, decay_rate: float, hours_ahead: float) -> float:
        """Calculate projected power after specified hours."""
        if decay_rate <= 0:
            return current_power  # Immortal mech

        # Convert hours to days for calculation
        days_ahead = hours_ahead / 24.0
        decay_amount = days_ahead * decay_rate

        return current_power - decay_amount

    def _calculate_time_until_zero(self, current_power: float, decay_rate: float) -> Optional[float]:
        """Calculate hours until power reaches zero."""
        if decay_rate <= 0 or current_power <= 0:
            return None  # Immortal or already at zero

        # Hours = (power / decay_per_day) * 24_hours_per_day
        hours_until_zero = (current_power / decay_rate) * 24.0
        return hours_until_zero

    def _build_survival_information(self, current_power: float, decay_rate: float, time_until_zero: Optional[float], mech_level: int) -> Dict[str, Any]:
        """Build comprehensive survival information."""
        survival_info = {
            'current_power': current_power,
            'decay_rate_per_day': decay_rate,
            'decay_rate_per_hour': decay_rate / 24.0,
            'mech_level': mech_level,
            'is_immortal': decay_rate <= 0
        }

        if time_until_zero is not None:
            survival_info.update({
                'hours_until_zero': time_until_zero,
                'days_until_zero': time_until_zero / 24.0,
                'survival_category': self._get_survival_category(time_until_zero)
            })
        else:
            survival_info.update({
                'hours_until_zero': None,
                'days_until_zero': None,
                'survival_category': 'immortal'
            })

        return survival_info

    def _get_survival_category(self, hours_until_zero: float) -> str:
        """Get survival category based on hours until zero power."""
        if hours_until_zero <= 1:
            return 'critical'  # Less than 1 hour
        elif hours_until_zero <= 6:
            return 'urgent'    # Less than 6 hours
        elif hours_until_zero <= 24:
            return 'warning'   # Less than 1 day
        elif hours_until_zero <= 72:
            return 'stable'    # Less than 3 days
        else:
            return 'healthy'   # More than 3 days


# Singleton instance
_mech_decay_service = None


def get_mech_decay_service() -> MechDecayService:
    """Get the singleton MechDecayService instance."""
    global _mech_decay_service
    if _mech_decay_service is None:
        _mech_decay_service = MechDecayService()
    return _mech_decay_service