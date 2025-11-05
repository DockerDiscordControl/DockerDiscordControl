# =============================================================================
# SERVICE FIRST: Channel Configuration Service - SINGLE POINT OF TRUTH
# =============================================================================

import logging
import json
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
        self.base_dir = os.environ.get('DDC_BASE_DIR', os.getcwd() if os.path.exists('config') else '/app')
        self.channels_dir = Path(self.base_dir) / 'config' / 'channels'
        self.config_file = Path(self.base_dir) / 'config' / 'config.json'

        # Ensure channels directory exists
        self.channels_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"ChannelConfigService initialized - managing {self.channels_dir}")

    def get_all_channels(self) -> Dict[str, Dict[str, Any]]:
        """Get all channel configurations from individual JSON files.

        Returns:
            Dict with channel IDs as keys and config dicts as values
        """
        channels = {}

        try:
            # Read each JSON file in channels directory
            for json_file in self.channels_dir.glob('*.json'):
                try:
                    channel_id = json_file.stem  # filename without .json
                    with open(json_file, 'r') as f:
                        channel_data = json.load(f)
                        channels[channel_id] = channel_data
                        logger.debug(f"Loaded channel config: {channel_id}")

                except json.JSONDecodeError as e:
                    logger.error(f"Invalid JSON in {json_file}: {e}")
                except Exception as e:
                    logger.error(f"Error reading {json_file}: {e}")

            logger.info(f"Loaded {len(channels)} channel configurations")

        except Exception as e:
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
        except Exception as e:
            logger.error(f"Error loading channel {channel_id}: {e}")
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
            # Save to individual channel file
            config_file = self.channels_dir / f"{channel_id}.json"
            with open(config_file, 'w') as f:
                json.dump(config, f, indent=2)
            logger.info(f"Saved channel config for {channel_id}")

            # Also update main config.json for consistency
            self._update_main_config(channel_id, config)

            return True

        except Exception as e:
            logger.error(f"Error saving channel {channel_id}: {e}")
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

        except Exception as e:
            logger.error(f"Error deleting channel {channel_id}: {e}")
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

            # Save back
            with open(self.config_file, 'w') as f:
                json.dump(main_config, f, indent=2)

            logger.debug(f"Updated main config with channel {channel_id}")

        except Exception as e:
            logger.error(f"Error updating main config for channel {channel_id}: {e}")

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

                    with open(self.config_file, 'w') as f:
                        json.dump(main_config, f, indent=2)

                    logger.debug(f"Removed channel {channel_id} from main config")

        except Exception as e:
            logger.error(f"Error removing channel {channel_id} from main config: {e}")

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

            # Save back
            with open(self.config_file, 'w') as f:
                json.dump(main_config, f, indent=2)

            logger.info(f"Updated main config with {len(channels)} channels")

        except Exception as e:
            logger.error(f"Error updating main config bulk: {e}")

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

        except Exception as e:
            logger.error(f"Error syncing from main config: {e}")
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