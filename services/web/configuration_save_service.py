#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Configuration Save Service                     #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""
Configuration Save Service - Handles complex configuration saving operations with cache management
"""

import os
import logging
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass

# Import custom exceptions
from services.exceptions import (
    ConfigServiceError, ConfigLoadError, ConfigSaveError,
    ConfigCacheError, FormValidationError, StorageError,
    FileStorageError
)

logger = logging.getLogger(__name__)


@dataclass
class ConfigurationSaveRequest:
    """Represents a configuration save request with form data."""
    form_data: Dict[str, Any]
    config_split_enabled: bool = False


@dataclass
class ConfigurationSaveResult:
    """Represents the result of configuration save operation."""
    success: bool
    message: str
    config_files: List[str] = None
    critical_settings_changed: bool = False
    error: Optional[str] = None


class ConfigurationSaveService:
    """Service for handling complex configuration save operations."""

    def __init__(self):
        self.logger = logger

    def save_configuration(self, request: ConfigurationSaveRequest) -> ConfigurationSaveResult:
        """
        Save configuration with comprehensive business logic handling.

        Args:
            request: ConfigurationSaveRequest with form data and options

        Returns:
            ConfigurationSaveResult with save status and details
        """
        try:
            # Step 1: Initialize and validate dependencies
            init_result = self._initialize_dependencies()
            if not init_result.success:
                return init_result

            # Step 2: Clean and process form data
            cleaned_form_data = self._clean_form_data(request.form_data)

            # Step 3: Process configuration through ConfigService
            processed_data, success, message = self._process_configuration(cleaned_form_data)
            if not success:
                return ConfigurationSaveResult(
                    success=False,
                    message=message or "Configuration processing failed"
                )

            # Step 4: Check for critical settings changes
            critical_changes = self._check_critical_changes(processed_data)

            # Step 5: Save server order separately for immediate effect
            self._save_server_order(processed_data)

            # Step 6: Save main configuration and container info
            save_result = self._save_configuration_files(processed_data, cleaned_form_data, request.config_split_enabled)
            if not save_result.success:
                return save_result

            # Step 7: Handle critical settings changes (cache invalidation, etc.)
            if critical_changes.changed:
                self._handle_critical_changes(critical_changes)

            # Step 8: Update logging settings
            self._update_logging_settings()

            # Step 9: Log the action
            self._log_save_action()

            # Step 10: Build response
            return self._build_save_response(message, save_result.config_files, critical_changes.changed, critical_changes.message)

        except (ImportError, AttributeError, RuntimeError) as e:
            # Service dependency errors (config service unavailable, service method failures)
            self.logger.error(f"Service dependency error saving configuration: {e}", exc_info=True)
            return ConfigurationSaveResult(
                success=False,
                error=f"Service error saving configuration: {str(e)}"
            )
        except (ValueError, TypeError, KeyError) as e:
            # Data errors (invalid form data, type mismatches, missing required fields)
            self.logger.error(f"Data error saving configuration: {e}", exc_info=True)
            return ConfigurationSaveResult(
                success=False,
                error=f"Data error saving configuration: {str(e)}"
            )

    def _initialize_dependencies(self) -> ConfigurationSaveResult:
        """Initialize and validate required dependencies."""
        try:
            from services.config.config_service import get_config_service
            self.config_service = get_config_service()

            # Check server order utilities availability
            try:
                from services.docker_service.server_order import save_server_order
                self.save_server_order_func = save_server_order
                self.server_order_available = True
            except ImportError:
                self.server_order_available = False
                self.logger.warning("Server order utilities not available, server order changes will require restart")

            return ConfigurationSaveResult(success=True, message="Dependencies initialized")

        except ImportError as e:
            # Import errors (config service module unavailable)
            self.logger.error(f"Import error loading required dependencies: {e}", exc_info=True)
            return ConfigurationSaveResult(
                success=False,
                error=f"Failed to import dependencies: {str(e)}"
            )
        except (AttributeError, RuntimeError) as e:
            # Service errors (service initialization failures, invalid service state)
            self.logger.error(f"Service error initializing dependencies: {e}", exc_info=True)
            return ConfigurationSaveResult(
                success=False,
                error=f"Service initialization error: {str(e)}"
            )

    def _clean_form_data(self, form_data: Dict[str, Any]) -> Dict[str, Any]:
        """Clean form data by converting single-item lists to values."""
        cleaned_data = {}
        for key, value in form_data.items():
            if isinstance(value, list) and len(value) == 1:
                cleaned_data[key] = value[0]
            else:
                cleaned_data[key] = value
        return cleaned_data

    def _process_configuration(self, form_data: Dict[str, Any]) -> Tuple[Dict[str, Any], bool, str]:
        """Process configuration through ConfigService."""
        try:
            from services.config.config_service import process_config_form, load_config

            current_config = load_config()
            return process_config_form(form_data, current_config)

        except (ImportError, AttributeError, RuntimeError) as e:
            # Service dependency errors (config service unavailable, processing function failures)
            self.logger.error(f"Service error processing configuration: {e}", exc_info=True)
            return {}, False, f"Service error processing configuration: {str(e)}"
        except (ValueError, TypeError, KeyError) as e:
            # Data errors (invalid form data, type mismatches, missing required fields)
            self.logger.error(f"Data error processing configuration: {e}", exc_info=True)
            return {}, False, f"Data error processing configuration: {str(e)}"

    def _check_critical_changes(self, processed_data: Dict[str, Any]) -> 'CriticalChanges':
        """Check for critical settings that require cache invalidation."""
        try:
            from services.config.config_service import load_config
            current_config = load_config()

            changes = CriticalChanges()

            # Check language change
            old_language = current_config.get('language', 'en')
            new_language = processed_data.get('language', 'en')
            if old_language != new_language:
                self.logger.info(f"Language changed from '{old_language}' to '{new_language}'")
                changes.language_changed = True
                changes.old_language = old_language
                changes.new_language = new_language

            # Check timezone change
            old_timezone = current_config.get('timezone', 'Europe/Berlin')
            new_timezone = processed_data.get('timezone', 'Europe/Berlin')
            if old_timezone != new_timezone:
                self.logger.info(f"Timezone changed from '{old_timezone}' to '{new_timezone}'")
                changes.timezone_changed = True

            if changes.language_changed or changes.timezone_changed:
                changes.changed = True
                changes.message = "Critical settings changed - caches have been invalidated. Changes should take effect immediately."

            return changes

        except (ImportError, AttributeError, RuntimeError) as e:
            # Service dependency errors (config service unavailable, load_config failures)
            self.logger.error(f"Service error checking critical changes: {e}", exc_info=True)
            return CriticalChanges()
        except (ValueError, TypeError, KeyError) as e:
            # Data errors (invalid config data, type mismatches, missing keys)
            self.logger.error(f"Data error checking critical changes: {e}", exc_info=True)
            return CriticalChanges()

    def _save_server_order(self, processed_data: Dict[str, Any]) -> None:
        """Save server order separately for immediate effect."""
        if not self.server_order_available:
            return

        try:
            server_order = processed_data.get('server_order')
            if server_order:
                # If it's a string with separators, split it
                if isinstance(server_order, str):
                    server_order = [name.strip() for name in server_order.split('__,__') if name.strip()]

                # Save to dedicated file
                self.save_server_order_func(server_order)
                self.logger.info(f"Server order saved separately: {server_order}")

        except (AttributeError, RuntimeError) as e:
            # Service errors (save_server_order function failures, file write errors)
            self.logger.error(f"Service error saving server order: {e}", exc_info=True)
        except (ValueError, TypeError) as e:
            # Data errors (invalid server_order format, string processing failures)
            self.logger.error(f"Data error saving server order: {e}", exc_info=True)

    def _save_configuration_files(self, processed_data: Dict[str, Any], form_data: Dict[str, Any], config_split_enabled: bool) -> 'SaveFilesResult':
        """Save main configuration and container info files."""
        try:
            from services.config.config_service import save_config
            from app.utils.container_info_web_handler import save_container_info_from_web, save_container_configs_from_web
            from pathlib import Path
            import json

            # Save main configuration
            save_config(processed_data)

            # Save container configs (allowed_actions, display_name, etc.) to individual files
            if 'servers' in processed_data:
                self.logger.info(f"[SAVE_DEBUG] Found servers in processed_data: {len(processed_data.get('servers', []))} servers")
                if processed_data['servers']:
                    self.logger.info(f"[SAVE_DEBUG] Calling save_container_configs_from_web with {len(processed_data['servers'])} servers")
                    for server in processed_data['servers'][:3]:  # Log first 3 servers for debugging
                        self.logger.info(f"[SAVE_DEBUG] Server: {server.get('docker_name')} - actions: {server.get('allowed_actions')}")
                    config_results = save_container_configs_from_web(processed_data['servers'])
                    self.logger.info(f"[SAVE_DEBUG] Container config save results: {config_results}")
                else:
                    self.logger.warning("[SAVE_DEBUG] servers list is empty!")
            else:
                self.logger.warning("[SAVE_DEBUG] No 'servers' key in processed_data!")

            # Get ALL containers from the containers directory, not just active ones
            containers_dir = Path('config/containers')
            all_container_names = []
            if containers_dir.exists():
                for json_file in containers_dir.glob('*.json'):
                    try:
                        with open(json_file, 'r') as f:
                            container_data = json.load(f)
                            container_name = container_data.get('container_name') or json_file.stem
                            all_container_names.append(container_name)
                    except (json.JSONDecodeError, ValueError) as e:
                        # JSON/data errors (malformed JSON, invalid container data)
                        self.logger.error(f"JSON/data error reading {json_file}: {e}", exc_info=True)
                    except (IOError, OSError) as e:
                        # File I/O errors (cannot read file, permission denied)
                        self.logger.error(f"File I/O error reading {json_file}: {e}", exc_info=True)

            # Get list of active containers
            active_container_names = []
            if 'servers' in processed_data:
                active_container_names = [server.get('docker_name') or server.get('container_name')
                                         for server in processed_data['servers']
                                         if server.get('docker_name') or server.get('container_name')]

            # Save container info for ALL containers
            if all_container_names:
                # For inactive containers, we need to clear their info fields
                for container_name in all_container_names:
                    if container_name not in active_container_names:
                        # Create empty form data for inactive containers to clear their info
                        form_data[f'info_enabled_{container_name}'] = '0'
                        form_data[f'info_show_ip_{container_name}'] = '0'
                        form_data[f'info_custom_ip_{container_name}'] = ''
                        form_data[f'info_custom_port_{container_name}'] = ''
                        form_data[f'info_custom_text_{container_name}'] = ''
                        self.logger.info(f"[SAVE_DEBUG] Clearing info for inactive container: {container_name}")

                # Save info for ALL containers (active and inactive)
                info_results = save_container_info_from_web(form_data, all_container_names)
                self.logger.info(f"Container info save results for {len(all_container_names)} containers: {info_results}")

            # Prepare file paths for display
            config_files = []
            if config_split_enabled:
                config_files = [
                    os.path.basename(self.config_service.bot_config_file),
                    os.path.basename(self.config_service.docker_config_file),
                    os.path.basename(self.config_service.channels_config_file),
                    os.path.basename(self.config_service.web_config_file)
                ]

            return SaveFilesResult(success=True, config_files=config_files)

        except (ImportError, AttributeError, RuntimeError) as e:
            # Service dependency errors (config service unavailable, save functions unavailable)
            self.logger.error(f"Service error saving configuration files: {e}", exc_info=True)
            return SaveFilesResult(
                success=False,
                error=f"Service error saving configuration files: {str(e)}"
            )
        except (IOError, OSError, json.JSONDecodeError) as e:
            # File I/O or JSON errors (cannot write files, JSON encoding failures)
            self.logger.error(f"File/JSON error saving configuration files: {e}", exc_info=True)
            return SaveFilesResult(
                success=False,
                error=f"File error saving configuration files: {str(e)}"
            )
        except (ValueError, TypeError, KeyError) as e:
            # Data errors (invalid processed_data, type mismatches, missing required keys)
            self.logger.error(f"Data error saving configuration files: {e}", exc_info=True)
            return SaveFilesResult(
                success=False,
                error=f"Data error saving configuration files: {str(e)}"
            )

    def _handle_critical_changes(self, changes: 'CriticalChanges') -> None:
        """Handle critical settings changes by invalidating caches."""
        try:
            # Invalidate ConfigService cache
            try:
                self.config_service._cache_service.invalidate_cache()
                self.logger.info("ConfigService cache invalidated due to critical settings change")
            except (AttributeError, RuntimeError) as cache_error:
                # Service errors (cache service unavailable, invalidation failures)
                self.logger.error(f"Service error invalidating ConfigService cache: {cache_error}", exc_info=True)
                raise ConfigCacheError(
                    "Failed to invalidate ConfigService cache",
                    error_code="CACHE_INVALIDATION_FAILED",
                    details={'error': str(cache_error)}
                )

            # Invalidate config cache
            try:
                from utils.config_cache import get_config_cache
                config_cache = get_config_cache()
                config_cache.clear()
                self.logger.info("Config cache cleared due to critical settings change")
            except (ImportError, AttributeError, RuntimeError) as cache_error:
                # Service errors (config_cache module unavailable, cache clear failures)
                self.logger.error(f"Service error clearing config cache: {cache_error}", exc_info=True)
                # Non-critical, continue

            # Force reload of configuration in config cache
            try:
                from utils.config_cache import init_config_cache
                from services.config.config_service import load_config
                fresh_config = load_config()
                init_config_cache(fresh_config)
                self.logger.info("Config cache reinitialized with fresh configuration")
            except ConfigLoadError as e:
                self.logger.error(f"Failed to reload config: {e.message}", exc_info=True)
                raise
            except (ImportError, AttributeError, RuntimeError) as reload_error:
                # Service errors (config cache init unavailable, reinitialization failures)
                self.logger.error(f"Service error reinitializing config cache: {reload_error}", exc_info=True)
                # Non-critical, continue

            # Clear translation manager cache if language changed
            if changes.language_changed:
                try:
                    self._clear_translation_cache(changes.old_language, changes.new_language)
                except (AttributeError, RuntimeError) as trans_error:
                    # Service errors (translation cache clear failures)
                    self.logger.error(f"Service error clearing translation cache: {trans_error}", exc_info=True)
                    # Non-critical, continue

            # Clear timezone cache if timezone changed
            if changes.timezone_changed:
                try:
                    from utils.time_utils import clear_timezone_cache
                    clear_timezone_cache()
                    self.logger.info("Timezone cache cleared due to timezone change")
                except ImportError:
                    # Import errors (time_utils module unavailable)
                    self.logger.debug("Timezone cache utilities not available")
                except (AttributeError, RuntimeError) as tz_error:
                    # Service errors (timezone cache clear failures)
                    self.logger.error(f"Service error clearing timezone cache: {tz_error}", exc_info=True)
                    # Non-critical, continue

        except ConfigCacheError:
            # Re-raise cache errors
            raise
        except (AttributeError, RuntimeError, TypeError) as e:
            # Service/runtime errors (unexpected cache operation failures, invalid states)
            self.logger.error(f"Runtime error handling critical changes: {e}", exc_info=True)
            # Don't raise - this shouldn't block the config save

    def _clear_translation_cache(self, old_language: str, new_language: str) -> None:
        """Clear translation manager cache for language changes."""
        try:
            from cogs.translation_manager import translation_manager

            # Clear the translation cache to force reload with new language
            if hasattr(translation_manager, '_'):
                translation_manager._.cache_clear()

            # Reset cached language to force fresh lookup
            if hasattr(translation_manager, '_cached_language'):
                delattr(translation_manager, '_cached_language')

            self.logger.info(f"Translation manager cache cleared for language change: {old_language} -> {new_language}")

        except (ImportError, AttributeError) as e:
            # Import/service errors (translation_manager unavailable, cache operations not supported)
            self.logger.warning(f"Service error clearing translation manager cache: {e}")

    def _update_logging_settings(self) -> None:
        """Update logging level settings based on new configuration."""
        try:
            from services.config.config_service import load_config
            import logging

            config_check = load_config()
            debug_level_enabled = config_check.get('debug_level_enabled', False)
            current_level = 'DEBUG' if debug_level_enabled else 'INFO'

            self.logger.info(f"Log level after config save: {current_level}")

            # Update logging level for all loggers
            root_logger = logging.getLogger()
            target_level = logging.DEBUG if debug_level_enabled else logging.INFO
            root_logger.setLevel(target_level)

            # Update specific loggers
            for logger_name in ['ddc', 'gunicorn', 'discord', 'app']:
                specific_logger = logging.getLogger(logger_name)
                specific_logger.setLevel(target_level)

            self.logger.info(f"All loggers set to {current_level} level")

            # Update scheduler logging if available
            try:
                from services.scheduling.scheduler import initialize_logging
                initialize_logging()
                self.logger.info("Scheduler logging settings updated after configuration save")
            except ImportError:
                self.logger.debug("Scheduler module not available for logging update")

        except (ImportError, AttributeError, RuntimeError) as e:
            # Service errors (config service unavailable, logging module errors)
            self.logger.warning(f"Service error updating logging settings: {str(e)}")

    def _log_save_action(self) -> None:
        """Log the configuration save action."""
        try:
            from services.infrastructure.action_logger import log_user_action
            log_user_action("SAVE", "Configuration", source="Web UI ConfigurationSaveService")
        except (ImportError, AttributeError, RuntimeError) as e:
            # Service errors (action_logger unavailable, logging failures)
            self.logger.warning(f"Service error logging save action: {e}")

    def _build_save_response(self, message: str, config_files: List[str], critical_changed: bool, critical_message: str) -> ConfigurationSaveResult:
        """Build the final save response."""
        final_message = message or 'Configuration saved successfully.'
        if critical_changed and critical_message:
            final_message += f" {critical_message}"

        return ConfigurationSaveResult(
            success=True,
            message=final_message,
            config_files=config_files or [],
            critical_settings_changed=critical_changed
        )


@dataclass
class CriticalChanges:
    """Tracks critical configuration changes."""
    changed: bool = False
    language_changed: bool = False
    timezone_changed: bool = False
    old_language: str = ""
    new_language: str = ""
    message: str = ""


@dataclass
class SaveFilesResult:
    """Result of saving configuration files."""
    success: bool
    config_files: List[str] = None
    error: Optional[str] = None


# Singleton instance
_configuration_save_service = None


def get_configuration_save_service() -> ConfigurationSaveService:
    """Get the singleton ConfigurationSaveService instance."""
    global _configuration_save_service
    if _configuration_save_service is None:
        _configuration_save_service = ConfigurationSaveService()
    return _configuration_save_service
