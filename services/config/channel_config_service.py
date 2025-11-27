# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
SERVICE FIRST: Channel Configuration Service - SINGLE POINT OF TRUTH
"""

import logging
import json
import tempfile
from pathlib import Path
from typing import Dict, Any, Optional
import os

logger = logging.getLogger('ddc.channel_config_service')

class ChannelConfigService:
    """Service First implementation for channel configuration management.

    SINGLE POINT OF TRUTH: Manages channel configurations and ensures
    consistency between /config/channels/*.json AND config.json
    """

    def __init__(self):
        """Initialize the ChannelConfigService."""
        # Robust absolute path relative to project root (3 levels up from services/config/channel_config_service.py)
        self.base_dir = Path(__file__).parents[2]
        self.channels_dir = self.base_dir / 'config' / 'channels'
        self.config_file = self.base_dir / 'config' / 'config.json'

        # Ensure channels directory exists
        self.channels_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"ChannelConfigService initialized - managing {self.channels_dir}")

    def _atomic_write_json(self, file_path: Path, data: Dict[str, Any]) -> None:
        """Write JSON data to file atomically to prevent corruption.

        Args:
            file_path: Path to the file to write
            data: Dictionary to serialize as JSON
        """
        temp_dir = str(file_path.parent)
        fd, temp_path = tempfile.mkstemp(dir=temp_dir, text=True, suffix='.json.tmp')

        try:
            # Write to temp file
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())  # Ensure data is written to disk

            # Atomic rename (POSIX) or move (Windows)
            if os.name == 'posix':
                os.rename(temp_path, file_path)
            else:
                # Windows: remove target first if exists
                if file_path.exists():
                    file_path.unlink()
                os.rename(temp_path, file_path)
        except Exception:
            # Cleanup temp file on error
            if os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass  # Best effort cleanup
            raise

    def _is_valid_discord_id(self, value: str) -> bool:
        """Check if a string is a valid Discord Snowflake ID.

        Discord IDs are 17-19 digit numbers (Snowflake format).

        Args:
            value: String to validate

        Returns:
            True if valid Discord ID format, False otherwise
        """
        if not value or not isinstance(value, str):
            return False
        return value.isdigit() and 17 <= len(value) <= 19

    def _extract_channel_id_from_data(self, channel_data: Dict[str, Any], filename: str) -> Optional[str]:
        """Try to extract a valid channel ID from channel data.

        Checks 'channel_id' field first, then 'name' field.

        Args:
            channel_data: Channel configuration dictionary
            filename: Original filename (without .json) for logging

        Returns:
            Valid channel ID string, or None if not found
        """
        # First try explicit channel_id field
        if 'channel_id' in channel_data:
            candidate = str(channel_data['channel_id']).strip()
            if self._is_valid_discord_id(candidate):
                logger.info(f"Found valid channel ID in 'channel_id' field: {candidate} (file: {filename})")
                return candidate

        # Then try name field (sometimes ID is stored there by mistake)
        if 'name' in channel_data:
            candidate = str(channel_data['name']).strip()
            if self._is_valid_discord_id(candidate):
                logger.info(f"Found valid channel ID in 'name' field: {candidate} (file: {filename})")
                return candidate

        return None

    def get_all_channels(self) -> Dict[str, Dict[str, Any]]:
        """Get all channel configurations from individual JSON files.

        Includes validation and auto-migration for incorrectly named files.

        Returns:
            Dict with channel IDs as keys and config dicts as values
        """
        channels = {}

        try:
            # Read each JSON file in channels directory
            for json_file in self.channels_dir.glob('*.json'):
                try:
                    filename = json_file.stem  # filename without .json
                    with open(json_file, 'r') as f:
                        channel_data = json.load(f)

                    # Validate: Is the filename a valid Discord channel ID?
                    if self._is_valid_discord_id(filename):
                        # Filename is a valid ID - use it directly
                        channel_id = filename
                    else:
                        # Filename is NOT a valid ID (e.g., "Control" instead of "1234567890123456789")
                        # Try to extract the real ID from the data
                        extracted_id = self._extract_channel_id_from_data(channel_data, filename)

                        if extracted_id:
                            channel_id = extracted_id
                            logger.warning(
                                f"Channel file '{filename}.json' has invalid name. "
                                f"Using extracted ID: {channel_id}. "
                                f"Auto-migrating file..."
                            )

                            # Auto-migrate: rename file to correct name
                            try:
                                new_file = self.channels_dir / f"{channel_id}.json"
                                if not new_file.exists():
                                    json_file.rename(new_file)
                                    logger.info(f"Migrated: {filename}.json -> {channel_id}.json")
                                else:
                                    # Target file exists - delete the incorrectly named one
                                    json_file.unlink()
                                    logger.info(f"Removed duplicate incorrectly-named file: {filename}.json")
                            except (OSError, PermissionError) as rename_error:
                                logger.warning(f"Could not auto-migrate file: {rename_error}")
                        else:
                            # No valid ID found anywhere - skip this file with warning
                            logger.warning(
                                f"Invalid channel ID: {filename} - "
                                f"File '{filename}.json' has no valid Discord ID. "
                                f"Please manually fix or remove this file."
                            )
                            continue

                    channels[channel_id] = channel_data
                    logger.debug(f"Loaded channel config: {channel_id}")

                except json.JSONDecodeError as e:
                    logger.error(f"Invalid JSON in {json_file}: {e}")
                except (IOError, OSError, PermissionError, UnicodeDecodeError, KeyError, ValueError) as e:
                    # File I/O errors (read errors, permissions, decode errors, data errors)
                    logger.error(f"File error reading {json_file}: {e}")

            logger.info(f"Loaded {len(channels)} channel configurations")

        except (OSError, AttributeError, TypeError) as e:
            # Directory/path errors (path operations, attribute/type errors)
            logger.error(f"Error loading channel configs: {e}")

        return channels

    def get_channel(self, channel_id: str) -> Optional[Dict[str, Any]]:
        """Get configuration for a specific channel.

        Args:
            channel_id: The Discord channel ID

        Returns:
            Channel configuration dict or None if not found
        """
        try:
            config_file = self.channels_dir / f"{channel_id}.json"
            if config_file.exists():
                with open(config_file, 'r') as f:
                    return json.load(f)
        except (IOError, OSError, PermissionError, json.JSONDecodeError, KeyError) as e:
            # File/JSON errors (I/O errors, permissions, invalid JSON, missing keys)
            logger.error(f"File/JSON error loading channel {channel_id}: {e}")
        return None

    def save_channel(self, channel_id: str, config: Dict[str, Any]) -> bool:
        """Save configuration for a specific channel.

        Args:
            channel_id: The Discord channel ID
            config: Configuration dictionary to save

        Returns:
            True if successful, False otherwise
        """
        try:
            # Validate channel_id is a proper Discord ID
            if not self._is_valid_discord_id(channel_id):
                logger.error(
                    f"Refusing to save channel config: '{channel_id}' is not a valid Discord ID. "
                    f"Discord IDs must be 17-19 digit numbers."
                )
                return False

            # Save to individual channel file atomically
            config_file = self.channels_dir / f"{channel_id}.json"
            self._atomic_write_json(config_file, config)
            logger.info(f"Saved channel config for {channel_id}")

            # Also update main config.json for consistency
            self._update_main_config(channel_id, config)

            return True

        except (IOError, OSError, PermissionError, TypeError, ValueError) as e:
            # File/JSON errors (I/O errors, permissions, JSON serialization errors)
            logger.error(f"File/JSON error saving channel {channel_id}: {e}")
            return False

    def delete_channel(self, channel_id: str) -> bool:
        """Delete configuration for a specific channel.

        Args:
            channel_id: The Discord channel ID

        Returns:
            True if successful or file doesn't exist, False on error
        """
        try:
            config_file = self.channels_dir / f"{channel_id}.json"
            if config_file.exists():
                config_file.unlink()
                logger.info(f"Deleted channel config for {channel_id}")

            # Also remove from main config.json
            self._remove_from_main_config(channel_id)

            return True

        except (OSError, PermissionError, AttributeError) as e:
            # File operation errors (unlink errors, permissions, attribute errors)
            logger.error(f"File error deleting channel {channel_id}: {e}")
            return False

    def save_all_channels(self, channels: Dict[str, Dict[str, Any]]) -> bool:
        """Save all channel configurations at once.

        Args:
            channels: Dict with channel IDs as keys and configs as values

        Returns:
            True if all successful, False if any failed
        """
        success = True

        # First, remove channels that are no longer in the new config
        existing_files = set(f.stem for f in self.channels_dir.glob('*.json'))
        new_channels = set(channels.keys())
        to_remove = existing_files - new_channels

        for channel_id in to_remove:
            if not self.delete_channel(channel_id):
                success = False

        # Then save all new/updated channels
        for channel_id, config in channels.items():
            if not self.save_channel(channel_id, config):
                success = False

        # Update main config with all channels
        self._update_main_config_bulk(channels)

        return success

    def _update_main_config(self, channel_id: str, channel_config: Dict[str, Any]) -> None:
        """Update the main config.json with channel configuration.

        Args:
            channel_id: The Discord channel ID
            channel_config: Configuration for the channel
        """
        try:
            # Load main config
            main_config = {}
            if self.config_file.exists():
                with open(self.config_file, 'r') as f:
                    main_config = json.load(f)

            # Update channel_permissions section
            if 'channel_permissions' not in main_config:
                main_config['channel_permissions'] = {}

            main_config['channel_permissions'][channel_id] = channel_config

            # Save back atomically
            self._atomic_write_json(self.config_file, main_config)

            logger.debug(f"Updated main config with channel {channel_id}")

        except (IOError, OSError, PermissionError, json.JSONDecodeError, TypeError, ValueError, KeyError) as e:
            # File/JSON/data errors (I/O, permissions, JSON parsing/serialization, data errors)
            logger.error(f"File/JSON error updating main config for channel {channel_id}: {e}")

    def _remove_from_main_config(self, channel_id: str) -> None:
        """Remove a channel from the main config.json.

        Args:
            channel_id: The Discord channel ID to remove
        """
        try:
            if self.config_file.exists():
                with open(self.config_file, 'r') as f:
                    main_config = json.load(f)

                if 'channel_permissions' in main_config and channel_id in main_config['channel_permissions']:
                    del main_config['channel_permissions'][channel_id]

                    # Save back atomically
                    self._atomic_write_json(self.config_file, main_config)

                    logger.debug(f"Removed channel {channel_id} from main config")

        except (IOError, OSError, PermissionError, json.JSONDecodeError, TypeError, ValueError, KeyError) as e:
            # File/JSON/data errors (I/O, permissions, JSON parsing/serialization, data errors)
            logger.error(f"File/JSON error removing channel {channel_id} from main config: {e}")

    def _update_main_config_bulk(self, channels: Dict[str, Dict[str, Any]]) -> None:
        """Update the main config.json with all channel configurations at once.

        Args:
            channels: Dict with channel IDs as keys and configs as values
        """
        try:
            # Load main config
            main_config = {}
            if self.config_file.exists():
                with open(self.config_file, 'r') as f:
                    main_config = json.load(f)

            # Replace entire channel_permissions section
            main_config['channel_permissions'] = channels

            # Save back atomically
            self._atomic_write_json(self.config_file, main_config)

            logger.info(f"Updated main config with {len(channels)} channels")

        except (IOError, OSError, PermissionError, json.JSONDecodeError, TypeError, ValueError, KeyError) as e:
            # File/JSON/data errors (I/O, permissions, JSON parsing/serialization, data errors)
            logger.error(f"File/JSON error updating main config bulk: {e}")

    def sync_from_main_config(self) -> bool:
        """Sync channel configs FROM main config.json to individual files.

        This is useful after a rebuild or when main config has been updated externally.

        Returns:
            True if successful, False otherwise
        """
        try:
            if not self.config_file.exists():
                logger.warning("Main config.json not found, nothing to sync")
                return True

            with open(self.config_file, 'r') as f:
                main_config = json.load(f)

            channel_permissions = main_config.get('channel_permissions', {})

            if channel_permissions:
                logger.info(f"Syncing {len(channel_permissions)} channels from main config")
                return self.save_all_channels(channel_permissions)
            else:
                logger.info("No channel permissions in main config to sync")
                return True

        except (IOError, OSError, PermissionError, json.JSONDecodeError, TypeError, ValueError, KeyError) as e:
            # File/JSON/data errors (I/O, permissions, JSON parsing/serialization, data errors)
            logger.error(f"File/JSON error syncing from main config: {e}")
            return False

# Singleton instance management
_channel_config_service_instance = None

def get_channel_config_service() -> ChannelConfigService:
    """Get singleton instance of ChannelConfigService.

    Returns:
        ChannelConfigService instance
    """
    global _channel_config_service_instance

    if _channel_config_service_instance is None:
        _channel_config_service_instance = ChannelConfigService()
        logger.info("Created new ChannelConfigService singleton instance")

    return _channel_config_service_instance

def reset_channel_config_service():
    """Reset the singleton instance (mainly for testing)."""
    global _channel_config_service_instance
    _channel_config_service_instance = None
    logger.info("ChannelConfigService singleton reset")
