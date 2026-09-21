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
from services.exceptions import DockerServiceError
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

# Catalog source strings (English) for the connectivity error embed, per context:
# (title, description with an {error} placeholder, footer). Translations are in
# locales/*.json; keep the keys there in sync when changing a text here.
_EMBED_TEXTS = {
    "serverstatus": (
        "🚨 Container Monitoring Unavailable",
        "**Docker connectivity issue detected**\n\n"
        "Unable to retrieve container status information.\n"
        "Please contact the system administrator.\n\n"
        "**Technical Details:** {error}\n\n"
        "**System Administrator Actions Required:**\n"
        "• Check Docker daemon status\n"
        "• Verify DDC container configuration\n"
        "• Restart DDC container if needed",
        "No container information available • https://ddc.bot",
    ),
    "individual_container": (
        "🚨 System Administrator Required",
        "**Docker connectivity issue detected**\n\n"
        "The container monitoring system cannot connect to Docker.\n"
        "All container status information is unavailable.\n\n"
        "**Technical Details:** {error}\n\n"
        "**Required Action:**\n"
        "• System administrator must fix Docker connectivity\n"
        "• Check Docker daemon status\n"
        "• Verify DDC container configuration\n"
        "• Restart DDC container if needed",
        "No container operations available until resolved • https://ddc.bot",
    ),
    "general": (
        "🚨 Docker Connectivity Issue",
        "**Docker connectivity problem detected**\n\n"
        "**Technical Details:** {error}\n\n"
        "**Administrator Actions Required:**\n"
        "• Check Docker daemon status\n"
        "• Verify container configuration\n"
        "• Restart services if needed",
        "System administrator intervention required • https://ddc.bot",
    ),
}


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
                # Docker.ping() returns True if daemon is reachable (blocking HTTP call -> worker thread)
                ping_result = await asyncio.to_thread(client.ping)

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
            return self._classified_failure(e)

        except DockerServiceError as e:
            # The one that was missing (review E15). get_docker_client_async
            # raises DockerConnectionError when every way of building a client
            # has failed - the socket unmounted, the daemon stopped. That is
            # THE case this whole service exists to report, and it was the one
            # case that walked past all of these handlers and raised at the
            # caller instead.
            #
            # What that cost is not an abstraction: DDC has a finished answer
            # for exactly this situation. create_error_embed_data builds the
            # "Container Monitoring Unavailable" embed, translated into all 40
            # languages, that tells the operator to check the socket mount. It
            # is reached from is_connected being False - a flag that was never
            # set, because the check raised before it could return one.
            #
            # The pool wraps the original text into its message, so the same
            # classification works on it.
            return self._classified_failure(e)

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

    def _classified_failure(self, error: Exception) -> DockerConnectivityResult:
        """Turn a connection failure into the answer, with the right kind named.

        The kind matters: it is what create_error_embed_data picks its wording
        from, and "your socket is not mounted" and "you lack permission on the
        socket" are different pieces of advice. The classification reads the
        message text because that is the only place the distinction survives -
        docker's own exceptions do not carry it structurally.
        """
        error_str = str(error).lower()

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
            error_message = f"Docker connectivity error: {error}"
            technical_details = str(error)

        self.logger.warning(f"[DOCKER_CONNECTIVITY] {error_message}", exc_info=True)
        return DockerConnectivityResult(
            is_connected=False,
            error_message=error_message,
            error_type=error_type,
            technical_details=technical_details
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
            # English source strings, translated through the catalog in the
            # server's language. Until 2026-09-19 there were two hard-wired
            # variants: 'en' got English and EVERY other language got German, so
            # French, Spanish, Japanese ... servers saw this error in German.
            # German now lives in locales/de.json like every other translation.
            from cogs.translation_manager import translation_manager
            title, description, footer_text = _EMBED_TEXTS.get(request.context, _EMBED_TEXTS["general"])
            title = translation_manager.translate(title, request.language)
            description = translation_manager.translate(description, request.language).format(
                error=request.error_message)
            footer_text = translation_manager.translate(footer_text, request.language)

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
