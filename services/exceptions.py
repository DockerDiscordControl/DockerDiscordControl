#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DockerDiscordControl - Custom Exception Hierarchy
Structured error handling for all DDC services
"""

# ============================================================================
# BASE EXCEPTIONS
# ============================================================================

class DDCBaseException(Exception):
    """
    Base exception for all DockerDiscordControl errors.

    All custom exceptions inherit from this to allow catching all DDC-specific errors.
    Includes structured error data support.
    """
    def __init__(self, message: str, error_code: str = None, details: dict = None):
        super().__init__(message)
        self.message = message
        self.error_code = error_code or self.__class__.__name__
        self.details = details or {}

    def to_dict(self):
        """Convert exception to structured dictionary for logging/API responses."""
        return {
            'error': self.__class__.__name__,
            'error_code': self.error_code,
            'message': self.message,
            'details': self.details
        }


# ============================================================================
# CONFIGURATION EXCEPTIONS
# ============================================================================

class ConfigServiceError(DDCBaseException):
    """Base exception for all configuration service errors."""

class ConfigLoadError(ConfigServiceError):
    """Raised when configuration loading fails."""

class ConfigSaveError(ConfigServiceError):
    """Raised when configuration saving fails."""

class ConfigValidationError(ConfigServiceError):
    """Raised when configuration validation fails."""

class ConfigMigrationError(ConfigServiceError):
    """Raised when configuration migration fails."""

class ConfigCacheError(ConfigServiceError):
    """Raised when configuration cache operations fail."""

class TokenEncryptionError(ConfigServiceError):
    """Raised when token encryption/decryption fails."""

class InvalidConfigFormatError(ConfigValidationError):
    """Raised when config file has invalid format."""

class MissingConfigError(ConfigLoadError):
    """Raised when required configuration is missing."""


# ============================================================================
# DOCKER SERVICE EXCEPTIONS
# ============================================================================

class DockerServiceError(DDCBaseException):
    """Base exception for all Docker service errors."""

class DockerConnectionError(DockerServiceError):
    """Raised when Docker daemon connection fails."""

class DockerClientPoolExhausted(DockerServiceError):
    """Raised when Docker client pool has no available connections."""

class DockerCommandTimeoutError(DockerServiceError):
    """Raised when Docker command times out."""

class ContainerNotFoundError(DockerServiceError):
    """Raised when specified container doesn't exist."""

class ContainerActionError(DockerServiceError):
    """Raised when container action (start/stop/restart) fails."""

class ContainerLogError(DockerServiceError):
    """Raised when fetching container logs fails."""

class DockerImageError(DockerServiceError):
    """Raised when Docker image operations fail."""


# ============================================================================
# DONATION SERVICE EXCEPTIONS
# ============================================================================

class DonationServiceError(DDCBaseException):
    """Base exception for all donation service errors."""

class DonationKeyValidationError(DonationServiceError):
    """Raised when donation key validation fails."""

class DonationAPIError(DonationServiceError):
    """Raised when external donation API calls fail."""

class DonationDataError(DonationServiceError):
    """Raised when donation data processing fails."""

class DonationThresholdError(DonationServiceError):
    """Raised when donation threshold checks fail."""


# ============================================================================
# MECH SERVICE EXCEPTIONS
# ============================================================================

class MechServiceError(DDCBaseException):
    """Base exception for all mech service errors."""

class MechStateError(MechServiceError):
    """Raised when mech state operations fail."""

class MechEvolutionError(MechServiceError):
    """Raised when evolution calculations fail."""

class MechAnimationError(MechServiceError):
    """Raised when animation generation fails."""

class MechPowerDecayError(MechServiceError):
    """Raised when power decay calculations fail."""

class MechLevelError(MechServiceError):
    """Raised when level calculations fail."""


# ============================================================================
# WEB SERVICE EXCEPTIONS
# ============================================================================

class WebServiceError(DDCBaseException):
    """Base exception for all web service errors."""

class AuthenticationError(WebServiceError):
    """Raised when authentication fails."""

class AuthorizationError(WebServiceError):
    """Raised when user lacks required permissions."""

class SessionError(WebServiceError):
    """Raised when session management fails."""

class FormValidationError(WebServiceError):
    """Raised when web form validation fails."""

class TemplateRenderError(WebServiceError):
    """Raised when template rendering fails."""


# ============================================================================
# DISCORD BOT EXCEPTIONS
# ============================================================================

class BotServiceError(DDCBaseException):
    """Base exception for all bot service errors."""

class BotConnectionError(BotServiceError):
    """Raised when bot connection to Discord fails."""

class CommandExecutionError(BotServiceError):
    """Raised when Discord command execution fails."""

class InteractionError(BotServiceError):
    """Raised when Discord interaction handling fails."""

class ChannelPermissionError(BotServiceError):
    """Raised when channel permission checks fail."""

class MessageUpdateError(BotServiceError):
    """Raised when message update/editing fails."""


# ============================================================================
# SCHEDULING EXCEPTIONS
# ============================================================================

class SchedulerError(DDCBaseException):
    """Base exception for all scheduler errors."""

class TaskSchedulingError(SchedulerError):
    """Raised when task scheduling fails."""

class TaskExecutionError(SchedulerError):
    """Raised when scheduled task execution fails."""

class CronParseError(SchedulerError):
    """Raised when cron expression parsing fails."""


# ============================================================================
# DATABASE/STORAGE EXCEPTIONS
# ============================================================================

class StorageError(DDCBaseException):
    """Base exception for all storage/database errors."""

class FileStorageError(StorageError):
    """Raised when file storage operations fail."""

class DataIntegrityError(StorageError):
    """Raised when data integrity checks fail."""

class LockAcquisitionError(StorageError):
    """Raised when file/resource lock acquisition fails."""


# ============================================================================
# TRANSLATION/LOCALIZATION EXCEPTIONS
# ============================================================================

class TranslationError(DDCBaseException):
    """Base exception for translation errors."""

class MissingTranslationError(TranslationError):
    """Raised when translation key is missing."""

class LanguageNotSupportedError(TranslationError):
    """Raised when requested language is not supported."""


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_exception_info(exception: Exception) -> dict:
    """
    Extract structured information from any exception.

    Args:
        exception: The exception to extract info from

    Returns:
        Dictionary with exception details
    """
    if isinstance(exception, DDCBaseException):
        return exception.to_dict()
    else:
        return {
            'error': exception.__class__.__name__,
            'error_code': exception.__class__.__name__,
            'message': str(exception),
            'details': {}
        }


def is_recoverable_error(exception: Exception) -> bool:
    """
    Determine if an error is recoverable (retry possible).

    Args:
        exception: The exception to check

    Returns:
        True if error is recoverable, False otherwise
    """
    # Connection errors are typically recoverable
    recoverable_types = (
        DockerConnectionError,
        DockerCommandTimeoutError,
        BotConnectionError,
        DonationAPIError,
        ConfigCacheError
    )

    return isinstance(exception, recoverable_types)


def should_alert_admin(exception: Exception) -> bool:
    """
    Determine if an error requires admin notification.

    Args:
        exception: The exception to check

    Returns:
        True if admin should be alerted, False otherwise
    """
    # Critical errors that need immediate attention
    critical_types = (
        TokenEncryptionError,
        DataIntegrityError,
        AuthenticationError,
        ConfigMigrationError,
        BotConnectionError
    )

    return isinstance(exception, critical_types)
