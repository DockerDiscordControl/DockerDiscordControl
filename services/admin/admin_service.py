# =============================================================================
# SERVICE FIRST: Admin User Management Service
# =============================================================================

import json
import logging
import os
import stat
import tempfile
from pathlib import Path
from typing import List, Optional, Dict, Any, Union
from datetime import datetime, timedelta
import asyncio
from threading import Lock

logger = logging.getLogger('ddc.admin_service')

def _admins_file() -> Path:
    """admins.json in the config directory - DDC_CONFIG_DIR, else <project>/config.

    Was derived at three places from Path(__file__).parents[2], ignoring the
    variable: a user pointing DDC_CONFIG_DIR at their volume kept the admin list
    outside it and lost it on container re-creation, and in test runs
    save_admin_data wrote into the real config/ (SPEC.md Z2).
    """
    from utils.config_paths import get_config_dir
    return get_config_dir() / 'admins.json'


class AdminService:
    """Service First implementation for admin user management.

    This service handles all admin-related operations including:
    - Loading and caching admin users
    - Checking admin permissions
    - Managing admin configuration
    """

    def __init__(self):
        self._admin_users_cache: Optional[List[str]] = None
        self._admin_containers_cache: Optional[Dict[str, List[str]]] = None
        self._cache_timestamp: Optional[datetime] = None
        self._cache_lock = Lock()
        self._cache_ttl = timedelta(minutes=5)  # Cache for 5 minutes
        self._config: Optional[Dict[str, Any]] = None
        logger.info("AdminService initialized")

    def _load_admin_containers(self) -> Dict[str, List[str]]:
        """The per-admin container assignment from admins.json.

        A user id absent from the mapping means EVERY container - that is the
        upgrade default and it is not negotiable: anything else would silently
        strip every existing admin of their rights the moment this shipped. An
        empty list is a different statement and a deliberate one: "this admin
        may control nothing".

        Any error gives back an empty mapping, which makes every admin
        unscoped - but that is harmless, because the caller has already had to
        get past is_user_admin(), and THAT returns False when the same file
        cannot be read (review F1).
        """
        try:
            admins_file = _admins_file()
            if not admins_file.exists():
                return {}
            with open(admins_file, 'r') as handle:
                content = handle.read()
            if not content.strip():
                return {}
            raw = json.loads(content).get('admin_containers', {})
            if not isinstance(raw, dict):
                logger.warning("admin_containers is not an object - ignoring it")
                return {}
            assignment: Dict[str, List[str]] = {}
            for user_id, containers in raw.items():
                if not isinstance(containers, list):
                    logger.warning(f"admin_containers for {user_id} is not a list - ignoring it")
                    continue
                assignment[str(user_id)] = [str(name) for name in containers
                                            if isinstance(name, (str, int))]
            return assignment
        except (IOError, OSError, PermissionError, RuntimeError, ValueError,
                TypeError, json.JSONDecodeError) as e:
            logger.error(f"Error reading admin_containers: {e}", exc_info=True)
            return {}

    def get_admin_containers(self, user_id: Union[str, int],
                             force_refresh: bool = False) -> Optional[List[str]]:
        """Which containers this admin may control.

        ``None`` means every container - no assignment was made. A list means
        exactly those, and an empty list means none. Somebody who is not an
        admin gets an empty list: this mapping narrows a right, it never grants
        one.
        """
        if not self.is_user_admin(user_id, force_refresh=force_refresh):
            return []

        with self._cache_lock:
            if force_refresh or self._admin_containers_cache is None or not self._is_cache_valid():
                self._admin_containers_cache = self._load_admin_containers()
            assignment = self._admin_containers_cache

        containers = assignment.get(str(user_id))
        return None if containers is None else list(containers)

    def may_control(self, user_id: Union[str, int], docker_name: str,
                    force_refresh: bool = False) -> bool:
        """Whether the admin list lets this user control THIS container (B2).

        This is the B2 branch alone. The channel branch (B1) is decided before
        it and is not touched by any assignment: whoever may write in a control
        channel may still do everything there.
        """
        containers = self.get_admin_containers(user_id, force_refresh=force_refresh)
        if containers is None:
            return True
        return str(docker_name) in containers

    def _load_admin_users(self) -> List[str]:
        """Load admin users from admins.json file.

        Returns:
            List of admin user IDs as strings
        """
        try:
            # Get base directory from config
            from services.config.config_service import load_config
            # Via utils/config_paths.py (DDC_CONFIG_DIR): see _admins_file().
            admins_file = _admins_file()

            if not admins_file.exists():
                logger.info("admins.json not found, no admins configured")
                return []

            try:
                with open(admins_file, 'r') as f:
                    content = f.read()
                    if not content.strip():
                        logger.warning("admins.json is empty")
                        return []

                    admin_data = json.loads(content)
                    admin_users = admin_data.get('discord_admin_users', [])

                    # Validate that all entries are strings
                    validated_users = []
                    for user_id in admin_users:
                        if isinstance(user_id, (str, int)):
                            validated_users.append(str(user_id))
                        else:
                            logger.warning(f"Invalid admin user ID type: {type(user_id)}")

                    logger.info(f"Loaded {len(validated_users)} admin users")
                    return validated_users

            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON in admins.json: {e}")
                return []
            except (IOError, OSError, PermissionError, RuntimeError) as e:
                logger.error(f"Error reading admins.json: {e}", exc_info=True)
                return []

        except (IOError, OSError, PermissionError, RuntimeError, json.JSONDecodeError) as e:
            logger.error(f"Error in _load_admin_users: {e}", exc_info=True)
            return []

    def _is_cache_valid(self) -> bool:
        """Check if the admin users cache is still valid.

        Returns:
            True if cache is valid, False otherwise
        """
        if self._admin_users_cache is None or self._cache_timestamp is None:
            return False

        age = datetime.now() - self._cache_timestamp
        return age < self._cache_ttl

    def get_admin_users(self, force_refresh: bool = False) -> List[str]:
        """Get list of admin user IDs.

        Args:
            force_refresh: If True, bypass cache and reload from file

        Returns:
            List of admin user IDs as strings
        """
        with self._cache_lock:
            if not force_refresh and self._is_cache_valid():
                logger.debug("Returning cached admin users")
                return self._admin_users_cache or []

            logger.debug("Loading admin users from file")
            self._admin_users_cache = self._load_admin_users()
            self._cache_timestamp = datetime.now()
            return self._admin_users_cache or []

    def is_user_admin(self, user_id: Union[str, int], force_refresh: bool = False) -> bool:
        """Check if a user is an admin.

        Args:
            user_id: Discord user ID (string or int)
            force_refresh: If True, bypass cache and reload from file

        Returns:
            True if user is admin, False otherwise
        """
        user_id_str = str(user_id)
        admin_users = self.get_admin_users(force_refresh=force_refresh)
        is_admin = user_id_str in admin_users

        if is_admin:
            logger.debug(f"User {user_id_str} is admin")
        else:
            logger.debug(f"User {user_id_str} is not admin")

        return is_admin

    def clear_cache(self):
        """Clear the admin users cache."""
        with self._cache_lock:
            self._admin_users_cache = None
            self._admin_containers_cache = None
            self._cache_timestamp = None
            logger.info("Admin users cache cleared")

    def get_admin_data(self, force_refresh: bool = False) -> Dict[str, Any]:
        """Get full admin data including notes.

        Args:
            force_refresh: Force reload from disk

        Returns:
            Dict with 'discord_admin_users' and 'admin_notes'
        """
        try:
            from services.config.config_service import load_config
            config = load_config()
            # Via utils/config_paths.py (DDC_CONFIG_DIR): see _admins_file().
            admins_file = _admins_file()

            if not admins_file.exists():
                return {'discord_admin_users': [], 'admin_notes': {}, 'admin_containers': {}}

            try:
                with open(admins_file, 'r') as f:
                    admin_data = json.load(f)
                    return {
                        'discord_admin_users': admin_data.get('discord_admin_users', []),
                        'admin_notes': admin_data.get('admin_notes', {}),
                        'admin_containers': admin_data.get('admin_containers', {})
                    }
            except (AttributeError, IOError, KeyError, OSError, PermissionError, RuntimeError, TypeError, json.JSONDecodeError) as e:
                logger.error(f"Error reading admin data: {e}", exc_info=True)
                return {'discord_admin_users': [], 'admin_notes': {}, 'admin_containers': {}}

        except (IOError, OSError, PermissionError, RuntimeError) as e:
            logger.error(f"Error in get_admin_data: {e}", exc_info=True)
            return {'discord_admin_users': [], 'admin_notes': {}, 'admin_containers': {}}

    def save_admin_data(self, admin_users: List[str], admin_notes: Dict[str, str] = None,
                        admin_containers: Optional[Dict[str, List[str]]] = None) -> bool:
        """Save admin users, notes and container assignments to file.

        Args:
            admin_users: List of Discord user IDs
            admin_notes: Optional dict of user notes
            admin_containers: Optional per-admin container assignment. Left out,
                the assignment already on disk is CARRIED OVER rather than
                dropped - this method knew two keys and writing the whole file
                from them would have silently deleted the third (review F1).

        Returns:
            True if successful, False otherwise
        """
        try:
            from services.config.config_service import load_config
            config = load_config()
            if not config:
                logger.error("Config unavailable, cannot save admin data")
                return False

            # Via utils/config_paths.py (DDC_CONFIG_DIR): see _admins_file().
            admins_file = _admins_file()

            # Ensure directory exists
            admins_file.parent.mkdir(parents=True, exist_ok=True)

            # Prepare data. An assignment that was not passed is read back from
            # the file and kept: this writer replaces the whole document, so
            # leaving it out would delete it.
            if admin_containers is None:
                admin_containers = self._load_admin_containers()

            admin_data = {
                'discord_admin_users': admin_users,
                'admin_notes': admin_notes or {},
                'admin_containers': admin_containers or {}
            }

            # Write atomically (temp file in the same directory + os.replace) so a
            # failed or interrupted write never leaves a truncated admins.json
            fd, temp_path = tempfile.mkstemp(dir=str(admins_file.parent), prefix='.admins_', suffix='.json.tmp')
            try:
                with os.fdopen(fd, 'w') as f:
                    json.dump(admin_data, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                # Keep the permissions of the file being replaced (mkstemp uses 0600)
                if admins_file.exists():
                    os.chmod(temp_path, stat.S_IMODE(admins_file.stat().st_mode))
                os.replace(temp_path, str(admins_file))
            except BaseException:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass  # Best effort cleanup
                raise

            # Invalidate cache
            self._admin_users_cache = None
            self._admin_containers_cache = None
            self._cache_timestamp = None

            logger.info(f"Saved {len(admin_users)} admin users to {admins_file}")
            return True

        except (IOError, OSError, PermissionError) as e:
            logger.error(f"File I/O error saving admin data to {admins_file}: {e}", exc_info=True)
            return False
        except (TypeError, ValueError) as e:
            # json.dump raises TypeError/ValueError for unserializable data
            logger.error(f"JSON encoding error saving admin data: {e}", exc_info=True)
            return False
        except (RuntimeError, asyncio.TimeoutError) as e:
            logger.error(f"Runtime error saving admin data: {e}", exc_info=True)
            return False

    async def is_user_admin_async(self, user_id: Union[str, int], force_refresh: bool = False) -> bool:
        """Async wrapper for is_user_admin.

        Args:
            user_id: Discord user ID (string or int)
            force_refresh: If True, bypass cache and reload from file

        Returns:
            True if user is admin, False otherwise
        """
        # Run synchronous method in executor to avoid blocking
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.is_user_admin, user_id, force_refresh)

    async def get_admin_users_async(self, force_refresh: bool = False) -> List[str]:
        """Async wrapper for get_admin_users.

        Args:
            force_refresh: If True, bypass cache and reload from file

        Returns:
            List of admin user IDs as strings
        """
        # Run synchronous method in executor to avoid blocking
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.get_admin_users, force_refresh)

# Singleton instance
_admin_service_instance = None

def get_admin_service() -> AdminService:
    """Get singleton instance of AdminService.

    Returns:
        AdminService instance
    """
    global _admin_service_instance
    if _admin_service_instance is None:
        _admin_service_instance = AdminService()
    return _admin_service_instance
