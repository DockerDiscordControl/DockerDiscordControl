# =============================================================================
# SERVICE FIRST: Admin User Management Service
# =============================================================================

import json
import logging
from pathlib import Path
from typing import List, Optional, Dict, Any, Union
from datetime import datetime, timedelta
import asyncio
from threading import Lock

logger = logging.getLogger('ddc.admin_service')

class AdminService:
    """Service First implementation for admin user management.

    This service handles all admin-related operations including:
    - Loading and caching admin users
    - Checking admin permissions
    - Managing admin configuration
    """

    def __init__(self):
        self._admin_users_cache: Optional[List[str]] = None
        self._cache_timestamp: Optional[datetime] = None
        self._cache_lock = Lock()
        self._cache_ttl = timedelta(minutes=5)  # Cache for 5 minutes
        self._config: Optional[Dict[str, Any]] = None
        logger.info("AdminService initialized")

    def _load_admin_users(self) -> List[str]:
        """Load admin users from admins.json file.

        Returns:
            List of admin user IDs as strings
        """
        try:
            # Get base directory from config
            from services.config.config_service import load_config
            config = load_config()
            if not config:
                logger.warning("Config unavailable, returning empty admin list")
                return []

            base_dir = config.get('base_dir', '/app')
            admins_file = Path(base_dir) / 'config' / 'admins.json'

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
            except (IOError, OSError, PermissionError, RuntimeError, json.JSONDecodeError) as e:
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
            if not config:
                return {'discord_admin_users': [], 'admin_notes': {}}

            base_dir = config.get('base_dir', '/app')
            admins_file = Path(base_dir) / 'config' / 'admins.json'

            if not admins_file.exists():
                return {'discord_admin_users': [], 'admin_notes': {}}

            try:
                with open(admins_file, 'r') as f:
                    admin_data = json.load(f)
                    return {
                        'discord_admin_users': admin_data.get('discord_admin_users', []),
                        'admin_notes': admin_data.get('admin_notes', {})
                    }
            except (AttributeError, IOError, KeyError, OSError, PermissionError, RuntimeError, TypeError, json.JSONDecodeError) as e:
                logger.error(f"Error reading admin data: {e}", exc_info=True)
                return {'discord_admin_users': [], 'admin_notes': {}}

        except (IOError, OSError, PermissionError, RuntimeError) as e:
            logger.error(f"Error in get_admin_data: {e}", exc_info=True)
            return {'discord_admin_users': [], 'admin_notes': {}}

    def save_admin_data(self, admin_users: List[str], admin_notes: Dict[str, str] = None) -> bool:
        """Save admin users and notes to file.

        Args:
            admin_users: List of Discord user IDs
            admin_notes: Optional dict of user notes

        Returns:
            True if successful, False otherwise
        """
        try:
            from services.config.config_service import load_config
            config = load_config()
            if not config:
                logger.error("Config unavailable, cannot save admin data")
                return False

            base_dir = config.get('base_dir', '/app')
            admins_file = Path(base_dir) / 'config' / 'admins.json'

            # Ensure directory exists
            admins_file.parent.mkdir(parents=True, exist_ok=True)

            # Prepare data
            admin_data = {
                'discord_admin_users': admin_users,
                'admin_notes': admin_notes or {}
            }

            # Write to file
            with open(admins_file, 'w') as f:
                json.dump(admin_data, f, indent=2)

            # Invalidate cache
            self._admin_users_cache = None
            self._cache_timestamp = None

            logger.info(f"Saved {len(admin_users)} admin users to {admins_file}")
            return True

        except (RuntimeError, asyncio.CancelledError, asyncio.TimeoutError) as e:
            logger.error(f"Error saving admin data: {e}", exc_info=True)
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
