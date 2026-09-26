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

from utils.logging_utils import get_module_logger
import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime

logger = get_module_logger('diagnostics_service')


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

# Singleton instance
_diagnostics_service = None


def get_diagnostics_service() -> DiagnosticsService:
    """Get the singleton DiagnosticsService instance."""
    global _diagnostics_service
    if _diagnostics_service is None:
        _diagnostics_service = DiagnosticsService()
    return _diagnostics_service
