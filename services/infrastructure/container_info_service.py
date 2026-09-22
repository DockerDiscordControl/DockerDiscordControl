# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Container Info Service - Manages container metadata with clean service architecture
"""

import docker
import docker.errors  # explicit submodule import — ``import docker`` alone
                      # does not eagerly bind ``docker.errors``, but the
                      # ``except`` tuples below reference its exception types.
import os
import re
import json
from typing import Dict, Any, Optional, List
from pathlib import Path

from utils.atomic_io import atomic_write_json
from dataclasses import dataclass
from utils.logging_utils import get_module_logger
from services.config.server_config_service import get_server_config_service

logger = get_module_logger('container_info_service')

_SAFE_NAME_RE = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_.-]*$')


def _validate_path_safety(name: str, base_dir: Path) -> None:
    """Validate that a name is safe and the resulting path stays within base_dir."""
    if not _SAFE_NAME_RE.match(name):
        raise ValueError(f"Invalid container name: {name!r}")
    resolved = (base_dir / f"{name}.json").resolve()
    if not str(resolved).startswith(str(base_dir.resolve())):
        raise ValueError(f"Path traversal detected: {name!r}")

# What the protected info fields may hold. They were written into from_dict as
# bare slices, where they silently shortened on READ while both writers kept
# whatever they were given (review D18).
MAX_PROTECTED_CONTENT = 250
MAX_PROTECTED_PASSWORD = 60
# The info text everybody sees. The web form says 250 to the browser and the
# Discord modal enforces 250, but the save path enforced nothing - and this
# text goes into an embed DESCRIPTION, which Discord refuses beyond 4096
# characters, so a long one hid the container's whole info behind an error.
MAX_CUSTOM_TEXT = 250


@dataclass(frozen=True)
class ContainerInfo:
    """Immutable container information data structure."""
    enabled: bool
    show_ip: bool
    custom_ip: str
    custom_port: str
    custom_text: str
    # Protected information fields
    protected_enabled: bool
    protected_content: str
    protected_password: str

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ContainerInfo':
        """Create ContainerInfo from dictionary data."""
        return cls(
            enabled=bool(data.get('enabled', False)),
            show_ip=bool(data.get('show_ip', False)),
            custom_ip=str(data.get('custom_ip', '')),
            custom_port=str(data.get('custom_port', '')),
            custom_text=str(data.get('custom_text', '')),
            protected_enabled=bool(data.get('protected_enabled', False)),
            # What is stored, unchanged. These used to be bare slices here, so a
            # value the writers had kept in full came back shorter on every
            # read - the operator saved 300 characters, saw them saved, and
            # found 250 the next time the panel loaded them. A reader that
            # edits its data is how the two came to disagree; the limit is
            # applied once, at the save below (review D18).
            protected_content=str(data.get('protected_content', '')),
            protected_password=str(data.get('protected_password', ''))
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert ContainerInfo to dictionary for storage."""
        return {
            'enabled': self.enabled,
            'show_ip': self.show_ip,
            'custom_ip': self.custom_ip,
            'custom_port': self.custom_port,
            'custom_text': self.custom_text,
            'protected_enabled': self.protected_enabled,
            'protected_content': self.protected_content,
            'protected_password': self.protected_password
        }

@dataclass(frozen=True)
class ServiceResult:
    """Standard service result wrapper."""
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None

class ContainerInfoService:
    """Clean service for managing container information using individual container JSON files."""

    def __init__(self, config_file: Optional[str] = None):
        """Initialize the container info service.

        Args:
            config_file: Path to docker config file (kept for compatibility, not used)
        """
        # DDC_CONFIG_DIR via utils/config_paths.py - see there (split config, SPEC.md Z2).
        from utils.config_paths import get_config_dir
        self.containers_dir = get_config_dir() / "containers"
        self.config_file = get_config_dir() / "docker_config.json"  # Keep for backward compatibility
        logger.info(f"Container info service initialized using container files in: {self.containers_dir}")

    def _find_by_stored_name(self, container_name: str) -> Optional[Path]:
        """The container's file when it is not stored under its own name.

        This scan reads files belonging to OTHER containers, so one of them
        being unreadable must not decide this container's fate. The loop used
        to open and parse each file unguarded, three times over in this class:
        a half-written legacy leftover or a hand-edited file raised out of the
        loop, and the caller's own handler turned that into "not found" or a
        failed save for a container whose file was perfectly fine (review D19).
        """
        for file in sorted(self.containers_dir.glob("*.json")):
            try:
                with open(file, 'r', encoding='utf-8') as handle:
                    data = json.load(handle)
            except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
                logger.warning(f"Skipping {file.name} while looking for "
                               f"'{container_name}': {e}")
                continue
            if not isinstance(data, dict):
                logger.warning(f"Skipping {file.name} while looking for "
                               f"'{container_name}': not an object")
                continue
            if (data.get('container_name') == container_name or
                    data.get('docker_name') == container_name or
                    data.get('name') == container_name):
                return file
        return None

    def get_container_info(self, container_name: str) -> ServiceResult:
        """Get container information by name from individual container JSON file.

        Args:
            container_name: Name of the container

        Returns:
            ServiceResult with ContainerInfo data or error
        """
        try:
            _validate_path_safety(container_name, self.containers_dir)

            # Try to find container JSON file
            container_file = self.containers_dir / f"{container_name}.json"

            if not container_file.exists():
                # Try alternative naming patterns
                container_file = self._find_by_stored_name(container_name)
                if container_file is None:
                    # Container not found - return default info
                    default_info = ContainerInfo(
                        enabled=False,
                        show_ip=False,
                        custom_ip='',
                        custom_port='',
                        custom_text='',
                        protected_enabled=False,
                        protected_content='',
                        protected_password=''
                    )
                    logger.debug(f"Container file not found for: {container_name}")
                    return ServiceResult(success=True, data=default_info)

            # Read container configuration
            with open(container_file, 'r', encoding='utf-8') as f:
                container_data = json.load(f)

            # Extract info section
            info_data = container_data.get('info', {})
            container_info = ContainerInfo.from_dict(info_data)
            logger.debug(f"Loaded info for container {container_name} from {container_file.name}: enabled={container_info.enabled}")
            return ServiceResult(success=True, data=container_info)

        except (AttributeError, IOError, KeyError, OSError, PermissionError, RuntimeError, TypeError, ValueError, json.JSONDecodeError, docker.errors.APIError, docker.errors.DockerException) as e:
            error_msg = f"Error loading info for {container_name}: {e}"
            logger.error(error_msg)
            return ServiceResult(success=False, error=error_msg)

    def _within_limits(self, container_name: str, info: ContainerInfo) -> ContainerInfo:
        """The one place the protected-info limits are applied - and said aloud.

        They used to be applied on READ, inside ContainerInfo.from_dict, while
        neither writer enforced anything: the web handler passes the form field
        through untouched, and an HTML maxlength is a suggestion to the browser,
        not a rule for the server. So a value was stored in full and came back
        shortened, without a word to anybody (review D18).
        """
        from dataclasses import replace

        trimmed = {}
        for field, limit in (("protected_content", MAX_PROTECTED_CONTENT),
                             ("protected_password", MAX_PROTECTED_PASSWORD),
                             ("custom_text", MAX_CUSTOM_TEXT)):
            value = getattr(info, field)
            if len(value) > limit:
                logger.warning(f"{field} for {container_name} is {len(value)} characters "
                               f"and is stored shortened to {limit}")
                trimmed[field] = value[:limit]
        return replace(info, **trimmed) if trimmed else info

    def save_container_info(self, container_name: str, container_info: ContainerInfo) -> ServiceResult:
        """Save container information to individual container JSON file.

        Args:
            container_name: Name of the container
            container_info: Container information to save

        Returns:
            ServiceResult indicating success or failure
        """
        try:
            container_info = self._within_limits(container_name, container_info)
            _validate_path_safety(container_name, self.containers_dir)

            # Find container JSON file
            container_file = self.containers_dir / f"{container_name}.json"

            if not container_file.exists():
                # Try alternative naming patterns
                container_file = self._find_by_stored_name(container_name)
                if container_file is None:
                    error_msg = f"Container file not found for: {container_name}"
                    logger.error(error_msg)
                    return ServiceResult(success=False, error=error_msg)

            # Read current container data
            with open(container_file, 'r', encoding='utf-8') as f:
                container_data = json.load(f)

            # Update info section
            container_data['info'] = container_info.to_dict()

            # The shared helper, not a hand-rolled temp-then-rename. This used
            # a FIXED temp name per container, `container_file.with_suffix('.tmp')`,
            # and container info is written from BOTH processes - the web panel
            # through container_info_web_handler and the bot through the Edit Info
            # modal. Two savers for the same container aimed at the same path, one
            # renamed it away while the other still held it, and that other one's
            # rename hit a file that was no longer there. Measured: 3 of 30
            # concurrent saves failed with "No such file or directory: web.tmp".
            # Same shape as review C29 on the game query verdicts.
            # atomic_write_json also fsyncs and keeps the target's permissions,
            # neither of which the hand-rolled version did (review D7).
            atomic_write_json(container_file, container_data)

            logger.info(f"Saved container info to {container_file.name}: {container_name}")
            return ServiceResult(success=True, data=container_info)

        except (IOError, OSError, PermissionError, RuntimeError, TypeError, ValueError, json.JSONDecodeError, docker.errors.APIError, docker.errors.DockerException) as e:
            error_msg = f"Error saving info for {container_name}: {e}"
            logger.error(error_msg)
            return ServiceResult(success=False, error=error_msg)

    def delete_container_info(self, container_name: str) -> ServiceResult:
        """Reset container information to defaults in individual container JSON file.

        Args:
            container_name: Name of the container

        Returns:
            ServiceResult indicating success or failure
        """
        try:
            _validate_path_safety(container_name, self.containers_dir)

            # Find container JSON file
            container_file = self.containers_dir / f"{container_name}.json"

            if not container_file.exists():
                # Try alternative naming patterns
                container_file = self._find_by_stored_name(container_name)
                if container_file is None:
                    logger.debug(f"Container file not found for: {container_name}")
                    return ServiceResult(success=True)  # Not an error if container doesn't exist

            # Read current container data
            with open(container_file, 'r', encoding='utf-8') as f:
                container_data = json.load(f)

            # Reset info section to defaults
            container_data['info'] = {
                'enabled': False,
                'show_ip': False,
                'custom_ip': '',
                'custom_port': '',
                'custom_text': '',
                'protected_enabled': False,
                'protected_content': '',
                'protected_password': ''
            }

            # The shared helper - see the reason at save_container_info (review D7).
            atomic_write_json(container_file, container_data)

            logger.info(f"Reset container info to defaults: {container_name}")
            return ServiceResult(success=True)

        except (IOError, OSError, PermissionError, RuntimeError, TypeError, ValueError, json.JSONDecodeError, docker.errors.APIError, docker.errors.DockerException) as e:
            error_msg = f"Error resetting info for {container_name}: {e}"
            logger.error(error_msg)
            return ServiceResult(success=False, error=error_msg)

# Singleton instance
_container_info_service = None

def get_container_info_service() -> ContainerInfoService:
    """Get the global container info service instance.

    Returns:
        ContainerInfoService instance
    """
    global _container_info_service
    if _container_info_service is None:
        _container_info_service = ContainerInfoService()
    return _container_info_service
