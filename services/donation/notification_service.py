# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""
Donation Notification Service - Handles file-based notifications from Web UI
"""

import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

class DonationNotificationService:
    """Service for checking and retrieving donation notifications."""

    def __init__(self, notification_path: Optional[str] = None):
        # Default via utils/config_paths.py (DDC_CONFIG_DIR) - the same place
        # services/web/donation_service.py writes to. Was hard-wired to
        # "/app/config/donation_notification.json".
        if notification_path is None:
            from utils.config_paths import get_config_dir
            notification_path = str(get_config_dir() / "donation_notification.json")
        # The path names the file an older version wrote; its directory is
        # where every announcement lands now, one file each.
        self.notification_file = Path(notification_path)
        self.notification_dir = self.notification_file.parent

    def _waiting(self) -> list:
        """Every announcement not yet told, oldest first.

        The name carries the write time (see donation_service.py), so sorting
        by name is sorting by age. The file an older version left behind has no
        time in its name and sorts first, which is right: it is the oldest.
        """
        try:
            return sorted(self.notification_dir.glob(
                f"{self.notification_file.stem}*{self.notification_file.suffix}"))
        except OSError as e:
            logger.error(f"Cannot look for donation notifications: {e}")
            return []

    def check_and_retrieve_notification(self) -> Optional[Dict[str, Any]]:
        """
        Check if a notification file exists, read it, delete it, and return data.
        Returns None if no file exists or error occurs.
        """
        waiting = self._waiting()
        if not waiting:
            return None
        notification_file = waiting[0]

        try:
            logger.info(f"Found donation notification file: {notification_file}")

            # Read data
            data = None
            with open(notification_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            logger.info(f"🔔 Notification data loaded: {data}")

            # Delete file immediately to prevent double processing
            try:
                notification_file.unlink()
                logger.debug(f"Deleted notification file: {notification_file}")
            except OSError as e:
                logger.error(f"Failed to delete notification file after reading: {e}")
                # If we can't delete, we return None to avoid loop processing
                # This is safer than duplicate broadcasts
                return None

            return data

        except (json.JSONDecodeError, OSError, ValueError) as e:
            logger.error(f"Error processing notification file: {e}", exc_info=True)
            # Try to delete corrupted file so we don't get stuck. The next poll
            # takes the next announcement; one broken file holds up nothing.
            try:
                notification_file.unlink()
            except OSError:
                pass
            return None

# Singleton instance
_service = None

def get_donation_notification_service() -> DonationNotificationService:
    global _service
    if _service is None:
        _service = DonationNotificationService()
    return _service
