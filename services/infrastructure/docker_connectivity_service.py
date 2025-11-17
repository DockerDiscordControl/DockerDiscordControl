# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Docker Connectivity Service - Clean service architecture for checking Docker daemon connectivity
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional, Tuple, Dict, Any
from utils.logging_utils import get_module_logger

logger = get_module_logger('docker_connectivity_service')

@dataclass(frozen=True)
class DockerConnectivityRequest:
    """Request for checking Docker connectivity."""
    timeout_seconds: float = 5.0

@dataclass(frozen=True)
class DockerConnectivityResult:
    """Result of Docker connectivity check."""
    is_connected: bool
    error_message: Optional[str] = None
    error_type: Optional[str] = None  # 'socket_error', 'daemon_error', 'permission_error', etc.
    technical_details: Optional[str] = None

@dataclass(frozen=True)
class DockerErrorEmbedRequest:
    """Request for creating Docker connectivity error embed."""
    error_message: str
    language: str = 'de'
    context: str = 'general'  # 'general', 'serverstatus', 'individual_container'

@dataclass(frozen=True)
class DockerErrorEmbedResult:
    """Result containing Discord embed data for Docker errors."""
    success: bool
    title: str
    description: str
    color: int = 0xe74c3c  # Red color for errors
    footer_text: str = "No container operations available until resolved • https://ddc.bot"
    error: Optional[str] = None

class DockerConnectivityService:
    """Clean service for Docker connectivity checking and error handling."""

    def __init__(self):
        self.logger = logger
        logger.info("Docker Connectivity Service initialized")

    async def check_connectivity(self, request: DockerConnectivityRequest) -> DockerConnectivityResult:
        """
        Check if Docker daemon is accessible using native Docker ping.

        Args:
            request: DockerConnectivityRequest with check parameters

        Returns:
            DockerConnectivityResult with connectivity status and error details
        """
        try:
            from services.docker_service.docker_client_pool import get_docker_client_async

            self.logger.debug(f"Checking Docker connectivity with {request.timeout_seconds}s timeout")

            # Use native Docker ping() for clean health check
            async with get_docker_client_async(
                timeout=request.timeout_seconds,
                operation='ping',
                container_name='connectivity_check'
            ) as client:
                # Docker.ping() returns True if daemon is reachable
                ping_result = client.ping()

                if ping_result:
                    self.logger.debug("Docker connectivity check successful (ping: OK)")
                    return DockerConnectivityResult(is_connected=True)
                else:
                    # Ping returned False/None - unusual but handle it
                    self.logger.warning("Docker ping returned unexpected result")
                    return DockerConnectivityResult(
                        is_connected=False,
                        error_message="Docker ping failed",
                        error_type="ping_failed"
                    )

        except asyncio.TimeoutError:
            error_msg = f"Docker daemon timeout after {request.timeout_seconds}s - system overloaded or unresponsive"
            self.logger.warning(f"[DOCKER_CONNECTIVITY] {error_msg}")
            return DockerConnectivityResult(
                is_connected=False,
                error_message=error_msg,
                error_type="timeout_error",
                technical_details=f"Timeout after {request.timeout_seconds} seconds"
            )

        except (OSError, IOError) as e:
            # Analyze the exception to determine error type
            error_str = str(e).lower()

            if "no such file or directory" in error_str:
                error_type = "socket_error"
                error_message = "Docker socket not accessible - container mount missing"
                technical_details = "Docker socket (/var/run/docker.sock) not mounted or accessible"
            elif "connection refused" in error_str or "connection aborted" in error_str:
                error_type = "daemon_error"
                error_message = "Docker daemon not running or unreachable"
                technical_details = "Docker daemon service not running or network unreachable"
            elif "permission denied" in error_str:
                error_type = "permission_error"
                error_message = "Docker socket permissions issue"
                technical_details = "User lacks permissions to access Docker socket"
            else:
                error_type = "connection_error"
                error_message = f"Docker connectivity error: {str(e)}"
                technical_details = str(e)

            self.logger.warning(f"[DOCKER_CONNECTIVITY] {error_message}", exc_info=True)
            return DockerConnectivityResult(
                is_connected=False,
                error_message=error_message,
                error_type=error_type,
                technical_details=technical_details
            )

        except (ImportError, AttributeError, RuntimeError) as e:
            # Service or import errors
            error_msg = f"Docker service error: {str(e)}"
            self.logger.error(f"[DOCKER_CONNECTIVITY] {error_msg}", exc_info=True)
            return DockerConnectivityResult(
                is_connected=False,
                error_message=error_msg,
                error_type="service_error",
                technical_details=str(e)
            )

    def create_error_embed_data(self, request: DockerErrorEmbedRequest) -> DockerErrorEmbedResult:
        """
        Create standardized embed data for Docker connectivity errors.

        Args:
            request: DockerErrorEmbedRequest with error details and language

        Returns:
            DockerErrorEmbedResult with Discord embed data
        """
        try:
            # Context-specific titles and descriptions
            if request.context == 'serverstatus':
                if request.language == 'en':
                    title = "🚨 Container Monitoring Unavailable"
                    description = ("**Docker connectivity issue detected**\n\n"
                                 "Unable to retrieve container status information.\n"
                                 "Please contact the system administrator.\n\n"
                                 f"**Technical Details:** {request.error_message}\n\n"
                                 "**System Administrator Actions Required:**\n"
                                 "• Check Docker daemon status\n"
                                 "• Verify DDC container configuration\n"
                                 "• Restart DDC container if needed")
                    footer_text = "No container information available • https://ddc.bot"
                else:  # German (default)
                    title = "🚨 Container-Überwachung nicht verfügbar"
                    description = ("**Docker-Konnektivitätsproblem erkannt**\n\n"
                                 "Container-Statusinformationen können nicht abgerufen werden.\n"
                                 "Bitte kontaktieren Sie den Systemadministrator.\n\n"
                                 f"**Technische Details:** {request.error_message}\n\n"
                                 "**Erforderliche Maßnahmen für Systemadministrator:**\n"
                                 "• Docker Daemon Status prüfen\n"
                                 "• DDC Container-Konfiguration überprüfen\n"
                                 "• DDC Container bei Bedarf neu starten")
                    footer_text = "Keine Container-Informationen verfügbar • https://ddc.bot"

            elif request.context == 'individual_container':
                if request.language == 'en':
                    title = "🚨 System Administrator Required"
                    description = ("**Docker connectivity issue detected**\n\n"
                                 "The container monitoring system cannot connect to Docker.\n"
                                 "All container status information is unavailable.\n\n"
                                 f"**Technical Details:** {request.error_message}\n\n"
                                 "**Required Action:**\n"
                                 "• System administrator must fix Docker connectivity\n"
                                 "• Check Docker daemon status\n"
                                 "• Verify DDC container configuration\n"
                                 "• Restart DDC container if needed")
                    footer_text = "No container operations available until resolved • https://ddc.bot"
                else:  # German (default)
                    title = "🚨 Systemadministrator erforderlich"
                    description = ("**Docker-Konnektivitätsproblem erkannt**\n\n"
                                 "Das Container-Überwachungssystem kann nicht mit Docker verbinden.\n"
                                 "Alle Container-Statusinformationen sind nicht verfügbar.\n\n"
                                 f"**Technische Details:** {request.error_message}\n\n"
                                 "**Erforderliche Maßnahme:**\n"
                                 "• Systemadministrator muss Docker-Konnektivität beheben\n"
                                 "• Docker Daemon Status prüfen\n"
                                 "• DDC Container-Konfiguration überprüfen\n"
                                 "• DDC Container bei Bedarf neu starten")
                    footer_text = "Keine Container-Operationen verfügbar bis zur Lösung • https://ddc.bot"

            else:  # general context
                if request.language == 'en':
                    title = "🚨 Docker Connectivity Issue"
                    description = ("**Docker connectivity problem detected**\n\n"
                                 f"**Technical Details:** {request.error_message}\n\n"
                                 "**Administrator Actions Required:**\n"
                                 "• Check Docker daemon status\n"
                                 "• Verify container configuration\n"
                                 "• Restart services if needed")
                    footer_text = "System administrator intervention required • https://ddc.bot"
                else:  # German (default)
                    title = "🚨 Docker-Konnektivitätsproblem"
                    description = ("**Docker-Konnektivitätsproblem erkannt**\n\n"
                                 f"**Technische Details:** {request.error_message}\n\n"
                                 "**Erforderliche Administrator-Maßnahmen:**\n"
                                 "• Docker Daemon Status prüfen\n"
                                 "• Container-Konfiguration überprüfen\n"
                                 "• Services bei Bedarf neu starten")
                    footer_text = "Systemadministrator-Eingriff erforderlich • https://ddc.bot"

            return DockerErrorEmbedResult(
                success=True,
                title=title,
                description=description,
                color=0xe74c3c,  # Red color for error
                footer_text=footer_text
            )

        except (RuntimeError, TypeError, ValueError, KeyError) as e:
            # Error creating embed (runtime errors, type/value errors, missing keys)
            error_msg = f"Error creating Docker connectivity embed: {e}"
            self.logger.error(error_msg, exc_info=True)
            return DockerErrorEmbedResult(
                success=False,
                title="Error",
                description="Could not create error embed",
                error=error_msg
            )

# Singleton instance
_docker_connectivity_service = None

def get_docker_connectivity_service() -> DockerConnectivityService:
    """Get the global Docker connectivity service instance.

    Returns:
        DockerConnectivityService instance
    """
    global _docker_connectivity_service
    if _docker_connectivity_service is None:
        _docker_connectivity_service = DockerConnectivityService()
    return _docker_connectivity_service