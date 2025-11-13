#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Diagnostics Service                            #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""
Diagnostics Service - Handles comprehensive diagnostic operations including
temporary debug mode management, port diagnostics, and system health checks.
"""

import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class DebugModeRequest:
    """Represents a debug mode request."""
    duration_minutes: Optional[int] = None  # For enable requests


@dataclass
class DebugStatusRequest:
    """Represents a debug status request."""
    pass


@dataclass
class PortDiagnosticsRequest:
    """Represents a port diagnostics request."""
    pass


@dataclass
class DiagnosticsResult:
    """Represents the result of diagnostic operations."""
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    status_code: int = 200


class DiagnosticsService:
    """Service for comprehensive system diagnostics and debug management."""

    def __init__(self):
        self.logger = logger

    def enable_temp_debug(self, request: DebugModeRequest) -> DiagnosticsResult:
        """
        Enable temporary debug mode for a specified duration.

        Args:
            request: DebugModeRequest with duration in minutes

        Returns:
            DiagnosticsResult with debug enablement information
        """
        try:
            # Validate and sanitize duration
            duration_minutes = self._validate_debug_duration(request.duration_minutes)

            # Enable temporary debug mode
            from utils.logging_utils import enable_temporary_debug
            success, expiry = enable_temporary_debug(duration_minutes)

            if success:
                # Format expiry time for display
                expiry_formatted = datetime.fromtimestamp(expiry).strftime('%Y-%m-%d %H:%M:%S')

                # Log the action
                self._log_debug_action("ENABLE", "Temporary Debug Mode")

                self.logger.info(f"Temporary debug mode enabled for {duration_minutes} minutes (until {expiry_formatted})")

                return DiagnosticsResult(
                    success=True,
                    data={
                        'message': f"Temporary debug mode enabled for {duration_minutes} minutes",
                        'expiry': expiry,
                        'expiry_formatted': expiry_formatted,
                        'duration_minutes': duration_minutes
                    }
                )
            else:
                return DiagnosticsResult(
                    success=False,
                    error="Failed to enable temporary debug mode",
                    status_code=500
                )

        except (RuntimeError) as e:
            self.logger.error(f"Error enabling temporary debug mode: {e}", exc_info=True)
            return DiagnosticsResult(
                success=False,
                error="Error enabling temporary debug mode. Please check the logs for details.",
                status_code=500
            )

    def disable_temp_debug(self, request: DebugModeRequest) -> DiagnosticsResult:
        """
        Disable temporary debug mode immediately.

        Args:
            request: DebugModeRequest (unused for disable)

        Returns:
            DiagnosticsResult with debug disablement information
        """
        try:
            # Disable temporary debug mode
            from utils.logging_utils import disable_temporary_debug
            success = disable_temporary_debug()

            if success:
                # Log the action
                self._log_debug_action("DISABLE", "Temporary Debug Mode")

                self.logger.info("Temporary debug mode disabled manually")

                return DiagnosticsResult(
                    success=True,
                    data={'message': "Temporary debug mode disabled"}
                )
            else:
                return DiagnosticsResult(
                    success=False,
                    error="Failed to disable temporary debug mode",
                    status_code=500
                )

        except (RuntimeError) as e:
            self.logger.error(f"Error disabling temporary debug mode: {e}", exc_info=True)
            return DiagnosticsResult(
                success=False,
                error="Error disabling temporary debug mode. Please check the logs for details.",
                status_code=500
            )

    def get_debug_status(self, request: DebugStatusRequest) -> DiagnosticsResult:
        """
        Get the current status of temporary debug mode.

        Args:
            request: DebugStatusRequest

        Returns:
            DiagnosticsResult with current debug status information
        """
        try:
            # Get current status
            from utils.logging_utils import get_temporary_debug_status
            is_enabled, expiry, remaining_seconds = get_temporary_debug_status()

            # Format times
            status_info = self._format_debug_status(is_enabled, expiry, remaining_seconds)

            return DiagnosticsResult(
                success=True,
                data=status_info
            )

        except (RuntimeError) as e:
            self.logger.error(f"Error getting temporary debug status: {e}", exc_info=True)
            return DiagnosticsResult(
                success=False,
                error="Error getting temporary debug status. Please check the logs for details.",
                data={'is_enabled': False},
                status_code=500
            )

    def run_port_diagnostics(self, request: PortDiagnosticsRequest) -> DiagnosticsResult:
        """
        Run comprehensive port diagnostics to help troubleshoot Web UI connection issues.

        Args:
            request: PortDiagnosticsRequest

        Returns:
            DiagnosticsResult with port diagnostics information
        """
        try:
            self.logger.info("Running port diagnostics on demand...")

            from app.utils.port_diagnostics import run_port_diagnostics
            diagnostics_report = run_port_diagnostics()

            return DiagnosticsResult(
                success=True,
                data={'diagnostics': diagnostics_report}
            )

        except (RuntimeError) as e:
            self.logger.error(f"Error running port diagnostics: {e}", exc_info=True)
            return DiagnosticsResult(
                success=False,
                error="Error running port diagnostics. Please check the logs for details.",
                status_code=500
            )

    # ========================================================================
    # Private Helper Methods
    # ========================================================================

    def _validate_debug_duration(self, duration_minutes: Optional[int]) -> int:
        """Validate and sanitize debug duration."""
        try:
            duration = int(duration_minutes) if duration_minutes is not None else 10
        except (ValueError, TypeError):
            duration = 10

        # Enforce reasonable limits
        if duration < 1:
            duration = 1
        elif duration > 60:
            duration = 60

        return duration

    def _format_debug_status(self, is_enabled: bool, expiry: float, remaining_seconds: float) -> Dict[str, Any]:
        """Format debug status information for response."""
        # Format expiry time
        expiry_formatted = datetime.fromtimestamp(expiry).strftime('%Y-%m-%d %H:%M:%S') if expiry > 0 else ""

        # Format remaining time
        remaining_minutes = int(remaining_seconds / 60)
        remaining_seconds_mod = int(remaining_seconds % 60)
        remaining_formatted = f"{remaining_minutes}m {remaining_seconds_mod}s" if is_enabled else ""

        return {
            'is_enabled': is_enabled,
            'expiry': expiry,
            'expiry_formatted': expiry_formatted,
            'remaining_seconds': remaining_seconds,
            'remaining_formatted': remaining_formatted
        }

    def _log_debug_action(self, action: str, target: str):
        """Log debug action for audit trail."""
        try:
            from services.infrastructure.action_logger import log_user_action
            log_user_action(action=action, target=target, source="Web UI")
        except (AttributeError, ImportError, KeyError, ModuleNotFoundError, RuntimeError, TypeError) as e:
            self.logger.warning(f"Could not log debug action: {e}")


# Singleton instance
_diagnostics_service = None


def get_diagnostics_service() -> DiagnosticsService:
    """Get the singleton DiagnosticsService instance."""
    global _diagnostics_service
    if _diagnostics_service is None:
        _diagnostics_service = DiagnosticsService()
    return _diagnostics_service