# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Configuration Migration Service - Handles all config file migrations
Part of ConfigService refactoring for Single Responsibility Principle
"""

import json
import logging
import re
import shutil
from pathlib import Path
from typing import Dict, Any
from datetime import datetime
from utils.atomic_io import atomic_write_text

logger = logging.getLogger('ddc.config_migration')

_SAFE_NAME_RE = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_.-]*$')
_SAFE_DISCORD_ID_RE = re.compile(r'^\d{17,19}$|^default$')


class ConfigMigrationService:
    """
    Handles all configuration migration operations.

    Responsibilities:
    - Detect migration needs
    - Migrate legacy configs to modular structure
    - Create backups before migration
    - Clean up legacy files after successful migration
    """

    def __init__(self, config_dir: Path, channels_dir: Path, containers_dir: Path):
        """Initialize migration service with directory paths."""
        self.config_dir = config_dir
        self.channels_dir = channels_dir
        self.containers_dir = containers_dir

        # Define file paths
        self.main_config_file = config_dir / "config.json"
        self.auth_config_file = config_dir / "auth.json"
        self.heartbeat_config_file = config_dir / "heartbeat.json"
        self.web_ui_config_file = config_dir / "web_ui.json"
        self.docker_settings_file = config_dir / "docker_settings.json"

        # Legacy file paths
        self.bot_config_file = config_dir / "bot_config.json"
        self.docker_config_file = config_dir / "docker_config.json"
        self.web_config_file = config_dir / "web_config.json"
        self.channels_config_file = config_dir / "channels_config.json"

        # Written only when a migration ran through to the end. "Was it started"
        # is not "was it finished" (review C28).
        self.migration_complete_marker = config_dir / ".modular_migration_complete"

        # Legacy v1.1.x config files
        self.legacy_config_file = config_dir / "config.json"
        self.legacy_alt_config = config_dir / "config_v1.json"

    def ensure_modular_structure(self, load_json_func, save_json_func) -> None:
        """
        Ensure modular structure exists - perform real migration if needed.

        Args:
            load_json_func: Function to load JSON files
            save_json_func: Function to save JSON files
        """
        try:
            if self.needs_real_modular_migration():
                logger.info("🔄 Performing automatic modular migration on startup...")
                self.perform_real_modular_migration(load_json_func, save_json_func)
            else:
                logger.debug("Modular structure already exists or no migration needed")
        except Exception as e:
            # Everything, on purpose. This runs in ConfigService.__init__, so an
            # exception that leaves here makes get_config_service() fail for the
            # whole installation. The clause used to name
            # (OSError, IOError, PermissionError, AttributeError), while
            # perform_real_modular_migration re-raises json.JSONDecodeError,
            # TypeError, ValueError and KeyError as well: one channel entry of
            # the wrong shape in a file from the previous version took the start
            # down, on the very startup that was meant to upgrade it (review
            # C55). The promise of this method is that a failed migration costs
            # the migration and nothing else - the legacy files are still there,
            # the completion marker is not written, and the next start tries
            # again.
            logger.error(f"Error ensuring modular structure: {e}", exc_info=True)
            logger.info("Falling back to virtual modular structure")

    def needs_real_modular_migration(self) -> bool:
        """Check if real modular migration is needed.

        The old question was whether the modular structure EXISTS - any file in
        channels_dir OR containers_dir was enough. A migration that wrote the
        channels and then died on the containers therefore looked finished from
        the second startup on, and was never retried: the container list stayed
        empty for good, with nothing in the log (review C28).
        """
        has_legacy = (self.channels_config_file.exists() or
                     self.docker_config_file.exists() or
                     self.bot_config_file.exists())
        if not has_legacy:
            return False

        if self.migration_complete_marker.exists():
            return False

        return not self._modular_structure_is_complete()

    def _modular_structure_is_complete(self) -> bool:
        """Every legacy file that is still here has its target populated.

        Asked per stage, because that is where the migration can stop. An
        installation migrated before the marker existed answers True here and is
        left alone; one that stopped halfway answers False and is picked up
        again.
        """
        if self.channels_config_file.exists():
            if not (self.channels_dir.exists() and
                    any(self.channels_dir.glob("*.json"))):
                return False

        if self.docker_config_file.exists():
            if not (self.containers_dir.exists() and
                    any(self.containers_dir.glob("*.json"))):
                return False

        if self.bot_config_file.exists() or self.web_config_file.exists():
            if not self.main_config_file.exists():
                return False

        return True

    def perform_real_modular_migration(self, load_json_func, save_json_func) -> None:
        """Perform the real modular migration automatically."""
        try:
            logger.info("🚀 Starting automatic modular config migration...")

            # Create backup first
            self.create_migration_backup()

            # Create modular directories
            self.create_modular_directories()

            # Migrate all configs
            if self.channels_config_file.exists():
                self.migrate_channels_to_files(load_json_func, save_json_func)

            if self.docker_config_file.exists():
                self.migrate_containers_to_files(load_json_func, save_json_func)

            if self.bot_config_file.exists():
                self.migrate_system_configs_to_files(load_json_func, save_json_func)

            if self.web_config_file.exists():
                self.migrate_web_configs_to_files(load_json_func, save_json_func)

            logger.info("✅ Automatic modular migration completed successfully!")
            logger.info("📁 New structure: channels/, containers/, and modular config files")

            # The marker goes down before the cleanup, so that a cleanup which
            # itself fails cannot make the finished migration look unfinished.
            try:
                atomic_write_text(self.migration_complete_marker,
                                  datetime.now().isoformat() + "\n")
            except OSError as e:
                logger.warning(f"Could not write the migration marker: {e}")

            # Clean up old JSON files after successful migration
            self.cleanup_legacy_files_after_migration()

        except (OSError, IOError, PermissionError, json.JSONDecodeError, TypeError, ValueError, KeyError) as e:
            # Migration errors (file I/O, permissions, JSON parsing/serialization, data errors)
            logger.error(f"❌ Error during automatic migration: {e}")
            raise

    def create_migration_backup(self) -> None:
        """Create backup of existing config files before migration."""
        backup_dir = self.config_dir / f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        backup_dir.mkdir(exist_ok=True)

        # Backup all JSON files
        for json_file in self.config_dir.glob("*.json"):
            if json_file.is_file():
                shutil.copy2(json_file, backup_dir)

        logger.info(f"📦 Created backup in: {backup_dir.name}")

    def cleanup_legacy_files_after_migration(self) -> None:
        """Clean up old JSON files after successful migration."""
        try:
            legacy_files_to_remove = [
                'bot_config.json',
                'docker_config.json',
                'web_config.json',
                'channels_config.json',
                'heartbeat.json'
            ]

            removed_files = []
            for filename in legacy_files_to_remove:
                file_path = self.config_dir / filename
                if file_path.exists():
                    try:
                        file_path.unlink()
                        removed_files.append(filename)
                    except (OSError, PermissionError) as e:
                        logger.warning(f"Could not remove {filename}: {e}")

            if removed_files:
                logger.info(f"🧹 Cleaned up legacy files: {', '.join(removed_files)}")
            else:
                logger.debug("No legacy files found to clean up")

        except (OSError, PermissionError) as e:
            # File operation errors (deletion errors, permissions)
            logger.warning(f"File error during cleanup: {e}")

    def create_modular_directories(self) -> None:
        """Create the modular directory structure."""
        self.channels_dir.mkdir(exist_ok=True, parents=True)
        self.containers_dir.mkdir(exist_ok=True, parents=True)
        logger.info("📁 Created modular directories: channels/, containers/")

    def migrate_channels_to_files(self, load_json_func, save_json_func) -> None:
        """Migrate channels_config.json to individual channel files."""
        try:
            channels_data = load_json_func(self.channels_config_file, {})
            channel_permissions = channels_data.get("channel_permissions", {})

            for channel_id, channel_config in channel_permissions.items():
                if not _SAFE_DISCORD_ID_RE.match(str(channel_id)):
                    logger.warning(f"Skipping invalid channel ID during migration: {channel_id!r}")
                    continue
                channel_file = self.channels_dir / f"{channel_id}.json"
                channel_config["channel_id"] = channel_id
                save_json_func(channel_file, channel_config)
                logger.info(f"✅ Migrated channel: {channel_config.get('name', channel_id)}")

            # Create default channel config
            default_config = {
                "name": "Default Channel Settings",
                "commands": {
                    "serverstatus": True,
                    "command": False,
                    "control": False,
                    "schedule": False
                },
                "post_initial": False,
                "update_interval_minutes": 10,
                "inactivity_timeout_minutes": 10,
                "enable_auto_refresh": True,
                "recreate_messages_on_inactivity": True
            }

            default_file = self.channels_dir / "default.json"
            save_json_func(default_file, default_config)

            logger.info(f"✅ Migrated {len(channel_permissions)} channels + default config")

        except (OSError, IOError, PermissionError, TypeError, ValueError, KeyError) as e:
            # Migration errors (file I/O, permissions, JSON serialization, data errors)
            logger.error(f"Migration error for channels to files: {e}")
            raise

    def migrate_containers_to_files(self, load_json_func, save_json_func) -> None:
        """Migrate docker_config.json to individual container files."""
        try:
            docker_data = load_json_func(self.docker_config_file, {})
            servers = docker_data.get("servers", [])

            for server in servers:
                container_name = server.get("docker_name", server.get("name", "unknown"))
                if not _SAFE_NAME_RE.match(container_name):
                    logger.warning(f"Skipping invalid container name during migration: {container_name!r}")
                    continue
                container_file = self.containers_dir / f"{container_name}.json"
                save_json_func(container_file, server)
                logger.info(f"✅ Migrated container: {container_name}")

            # Create docker_settings.json with system settings
            docker_settings = {
                "docker_socket_path": docker_data.get("docker_socket_path", "/var/run/docker.sock"),
                "container_command_cooldown": docker_data.get("container_command_cooldown", 5),
                "docker_api_timeout": docker_data.get("docker_api_timeout", 30),
                "max_log_lines": docker_data.get("max_log_lines", 50)
            }

            save_json_func(self.docker_settings_file, docker_settings)

            logger.info(f"✅ Migrated {len(servers)} containers + docker settings")

        except (OSError, IOError, PermissionError, TypeError, ValueError, KeyError) as e:
            # Migration errors (file I/O, permissions, JSON serialization, data errors)
            logger.error(f"Migration error for containers to files: {e}")
            raise

    def migrate_system_configs_to_files(self, load_json_func, save_json_func) -> None:
        """Migrate bot_config.json to modular system configs."""
        try:
            bot_data = load_json_func(self.bot_config_file, {})

            # Create main config.json
            main_config = {
                "language": bot_data.get("language", "en"),
                "ui_language": bot_data.get("ui_language", "en"),
                "timezone": bot_data.get("timezone", "UTC"),
                "guild_id": bot_data.get("guild_id"),
                "system_logs": {
                    "level": "INFO",
                    "max_file_size_mb": 10,
                    "backup_count": 5,
                    "enable_debug": False
                }
            }
            # Add Status Watchdog config (new format - replaces old heartbeat system)
            # Old heartbeat_channel_id is no longer used - Status Watchdog uses external ping URLs
            main_config["heartbeat"] = {
                "enabled": False,
                "ping_url": "",
                "interval": 5
            }
            save_json_func(self.main_config_file, main_config)

            # Note: heartbeat.json is no longer created - Status Watchdog config is in main config.json

            # Create auth.json
            auth_config = {
                "bot_token": bot_data.get("bot_token"),
                "encryption_enabled": True
            }
            save_json_func(self.auth_config_file, auth_config)

            logger.info("✅ Migrated system configs (config.json, auth.json)")

        except (OSError, IOError, PermissionError, TypeError, ValueError, KeyError) as e:
            # Migration errors (file I/O, permissions, JSON serialization, data errors)
            logger.error(f"Migration error for system configs to files: {e}")
            raise

    def migrate_web_configs_to_files(self, load_json_func, save_json_func) -> None:
        """Migrate web_config.json to modular web configs."""
        try:
            web_data = load_json_func(self.web_config_file, {})

            # Create clean web_ui.json (without advanced_settings)
            web_ui_config = {
                "web_ui_user": web_data.get("web_ui_user", "admin"),
                "web_ui_password_hash": web_data.get("web_ui_password_hash"),
                "admin_enabled": web_data.get("admin_enabled", True),
                "session_timeout": web_data.get("session_timeout", 3600),
                "donation_disable_key": web_data.get("donation_disable_key", ""),
                "scheduler_debug_mode": web_data.get("scheduler_debug_mode", False)
            }
            save_json_func(self.web_ui_config_file, web_ui_config)

            logger.info("✅ Migrated web configs (web_ui.json) - advanced_settings kept in web_config.json")

        except (OSError, IOError, PermissionError, TypeError, ValueError, KeyError) as e:
            # Migration errors (file I/O, permissions, JSON serialization, data errors)
            logger.error(f"Migration error for web configs to files: {e}")
            raise

    def migrate_legacy_v1_config_if_needed(self, load_json_func, save_json_func,
                                          extract_bot_config_func, extract_docker_config_func,
                                          extract_web_config_func, extract_channels_config_func) -> None:
        """
        Migrate v1.1.x config.json to v2.0 modular structure.
        Only performs migration if needed, safe to call multiple times.
        """
        # Check both possible legacy config locations
        legacy_file = None
        if self.legacy_config_file.exists() and self.legacy_config_file.name == "config.json":
            # Check if it's the old monolithic config
            try:
                with open(self.legacy_config_file, 'r', encoding='utf-8') as f:
                    test_data = json.load(f)
                    if 'servers' in test_data or 'docker_name' in test_data:
                        legacy_file = self.legacy_config_file
            except (OSError, ValueError) as exc:
                # Say something. Swallowing this made an UNREADABLE legacy config
                # indistinguishable from "there is no legacy config": the method
                # falls through to `if not legacy_file: return` and the user comes
                # up with an empty configuration - no containers, no channel
                # permissions - without ever learning why. This runs on every
                # get_config() (config_service.py:322), so it is the first thing
                # that happens after an upgrade from v1.1.x.
                #
                # Deliberately only the file NAME, never its content: a v1.1.x
                # config.json carries the bot token, and a log file is disk.
                # See SPEC.md Z9.
                logger.warning(
                    "Legacy config %s exists but could not be read (%s: %s) - "
                    "migration skipped. If this is a v1.1.x config, fix or remove "
                    "the file; otherwise DDC starts with an empty configuration.",
                    self.legacy_config_file.name, type(exc).__name__, exc,
                )
        elif self.legacy_alt_config.exists():
            legacy_file = self.legacy_alt_config

        if not legacy_file:
            return  # No migration needed

        logger.info(f"Found legacy v1.1.x config at {legacy_file.name} - performing automatic migration to v2.0")

        try:
            # Load legacy config
            with open(legacy_file, 'r', encoding='utf-8') as f:
                legacy_config = json.load(f)

            logger.info(f"Migrating v1.1.3D configuration with {len(legacy_config)} settings")

            # Split into modular files
            bot_config = extract_bot_config_func(legacy_config)
            docker_config = extract_docker_config_func(legacy_config)
            web_config = extract_web_config_func(legacy_config)
            channels_config = extract_channels_config_func(legacy_config)

            # Only save if we have data for each section
            if bot_config and any(v for v in bot_config.values() if v is not None):
                save_json_func(self.bot_config_file, bot_config)

            if docker_config:
                save_json_func(self.docker_config_file, docker_config)

            if web_config and any(v for v in web_config.values() if v is not None):
                save_json_func(self.web_config_file, web_config)

            if channels_config:
                save_json_func(self.channels_config_file, channels_config)

            # Create backup of legacy config
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_file = self.config_dir / f"{legacy_file.name}.v1.1.x.backup_{timestamp}"
            legacy_file.rename(backup_file)

            logger.info("✅ v1.1.3D → v2.0 migration completed successfully!")
            logger.info(f"   - Legacy config backed up to: {backup_file.name}")
            logger.info(f"   - Created modular config files: bot_config.json, docker_config.json, web_config.json, channels_config.json")

            # NO cleanup here. cleanup_legacy_files_after_migration() removes exactly
            # bot_config.json, docker_config.json, web_config.json and
            # channels_config.json - which are the files this migration has just
            # WRITTEN. For the other caller, perform_real_modular_migration(), those
            # four are genuinely leftovers; here they are the result, and deleting
            # them left an operator upgrading from v1.1.x with nothing but the
            # backup: no containers, no channel permissions (review C3). The legacy
            # file is already dealt with - it was renamed to the backup above.

            # Handle password migration
            if legacy_config.get('web_ui_password_hash'):
                logger.info("   - Web UI password migrated successfully")
            else:
                logger.warning("   - No web UI password found in legacy config")
                logger.warning("   - Use /setup or set DDC_ADMIN_PASSWORD for first login")

        except (IOError, OSError, PermissionError, json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError, KeyError, AttributeError) as e:
            # Migration errors (file I/O, permissions, JSON parsing, encoding, data errors, function calls)
            logger.error(f"❌ Migration failed: {e}")
            logger.error("Manual migration may be required")
