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
    pass

class ConfigLoadError(ConfigServiceError):
    """Raised when configuration loading fails."""
    pass

class ConfigSaveError(ConfigServiceError):
    """Raised when configuration saving fails."""
    pass

class ConfigValidationError(ConfigServiceError):
    """Raised when configuration validation fails."""
    pass

class ConfigMigrationError(ConfigServiceError):
    """Raised when configuration migration fails."""
    pass

class ConfigCacheError(ConfigServiceError):
    """Raised when configuration cache operations fail."""
    pass

class TokenEncryptionError(ConfigServiceError):
    """Raised when token encryption/decryption fails."""
    pass

class InvalidConfigFormatError(ConfigValidationError):
    """Raised when config file has invalid format."""
    pass

class MissingConfigError(ConfigLoadError):
    """Raised when required configuration is missing."""
    pass


# ============================================================================
# DOCKER SERVICE EXCEPTIONS
# ============================================================================

class DockerServiceError(DDCBaseException):
    """Base exception for all Docker service errors."""
    pass

class DockerConnectionError(DockerServiceError):
    """Raised when Docker daemon connection fails."""
    pass

class DockerClientPoolExhausted(DockerServiceError):
    """Raised when Docker client pool has no available connections."""
    pass

class DockerCommandTimeoutError(DockerServiceError):
    """Raised when Docker command times out."""
    pass

class ContainerNotFoundError(DockerServiceError):
    """Raised when specified container doesn't exist."""
    pass

class ContainerActionError(DockerServiceError):
    """Raised when container action (start/stop/restart) fails."""
    pass

class ContainerLogError(DockerServiceError):
    """Raised when fetching container logs fails."""
    pass

class DockerImageError(DockerServiceError):
    """Raised when Docker image operations fail."""
    pass


# ============================================================================
# DONATION SERVICE EXCEPTIONS
# ============================================================================

class DonationServiceError(DDCBaseException):
    """Base exception for all donation service errors."""
    pass

class DonationKeyValidationError(DonationServiceError):
    """Raised when donation key validation fails."""
    pass

class DonationAPIError(DonationServiceError):
    """Raised when external donation API calls fail."""
    pass

class DonationDataError(DonationServiceError):
    """Raised when donation data processing fails."""
    pass

class DonationThresholdError(DonationServiceError):
    """Raised when donation threshold checks fail."""
    pass


# ============================================================================
# MECH SERVICE EXCEPTIONS
# ============================================================================

class MechServiceError(DDCBaseException):
    """Base exception for all mech service errors."""
    pass

class MechStateError(MechServiceError):
    """Raised when mech state operations fail."""
    pass

class MechEvolutionError(MechServiceError):
    """Raised when evolution calculations fail."""
    pass

class MechAnimationError(MechServiceError):
    """Raised when animation generation fails."""
    pass

class MechPowerDecayError(MechServiceError):
    """Raised when power decay calculations fail."""
    pass

class MechLevelError(MechServiceError):
    """Raised when level calculations fail."""
    pass


# ============================================================================
# WEB SERVICE EXCEPTIONS
# ============================================================================

class WebServiceError(DDCBaseException):
    """Base exception for all web service errors."""
    pass

class AuthenticationError(WebServiceError):
    """Raised when authentication fails."""
    pass

class AuthorizationError(WebServiceError):
    """Raised when user lacks required permissions."""
    pass

class SessionError(WebServiceError):
    """Raised when session management fails."""
    pass

class FormValidationError(WebServiceError):
    """Raised when web form validation fails."""
    pass

class TemplateRenderError(WebServiceError):
    """Raised when template rendering fails."""
    pass


# ============================================================================
# DISCORD BOT EXCEPTIONS
# ============================================================================

class BotServiceError(DDCBaseException):
    """Base exception for all bot service errors."""
    pass

class BotConnectionError(BotServiceError):
    """Raised when bot connection to Discord fails."""
    pass

class CommandExecutionError(BotServiceError):
    """Raised when Discord command execution fails."""
    pass

class InteractionError(BotServiceError):
    """Raised when Discord interaction handling fails."""
    pass

class ChannelPermissionError(BotServiceError):
    """Raised when channel permission checks fail."""
    pass

class MessageUpdateError(BotServiceError):
    """Raised when message update/editing fails."""
    pass


# ============================================================================
# SCHEDULING EXCEPTIONS
# ============================================================================

class SchedulerError(DDCBaseException):
    """Base exception for all scheduler errors."""
    pass

class TaskSchedulingError(SchedulerError):
    """Raised when task scheduling fails."""
    pass

class TaskExecutionError(SchedulerError):
    """Raised when scheduled task execution fails."""
    pass

class CronParseError(SchedulerError):
    """Raised when cron expression parsing fails."""
    pass


# ============================================================================
# DATABASE/STORAGE EXCEPTIONS
# ============================================================================

class StorageError(DDCBaseException):
    """Base exception for all storage/database errors."""
    pass

class FileStorageError(StorageError):
    """Raised when file storage operations fail."""
    pass

class DataIntegrityError(StorageError):
    """Raised when data integrity checks fail."""
    pass

class LockAcquisitionError(StorageError):
    """Raised when file/resource lock acquisition fails."""
    pass


# ============================================================================
# TRANSLATION/LOCALIZATION EXCEPTIONS
# ============================================================================

class TranslationError(DDCBaseException):
    """Base exception for translation errors."""
    pass

class MissingTranslationError(TranslationError):
    """Raised when translation key is missing."""
    pass

class LanguageNotSupportedError(TranslationError):
    """Raised when requested language is not supported."""
    pass


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
