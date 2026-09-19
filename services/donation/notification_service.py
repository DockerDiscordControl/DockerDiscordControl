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
        self.notification_file = Path(notification_path)

    def check_and_retrieve_notification(self) -> Optional[Dict[str, Any]]:
        """
        Check if a notification file exists, read it, delete it, and return data.
        Returns None if no file exists or error occurs.
        """
        if not self.notification_file.exists():
            return None

        try:
            logger.info(f"Found donation notification file: {self.notification_file}")
            
            # Read data
            data = None
            with open(self.notification_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            logger.info(f"🔔 Notification data loaded: {data}")

            # Delete file immediately to prevent double processing
            try:
                self.notification_file.unlink()
                logger.debug(f"Deleted notification file: {self.notification_file}")
            except OSError as e:
                logger.error(f"Failed to delete notification file after reading: {e}")
                # If we can't delete, we return None to avoid loop processing
                # This is safer than duplicate broadcasts
                return None

            return data

        except (json.JSONDecodeError, OSError, ValueError) as e:
            logger.error(f"Error processing notification file: {e}", exc_info=True)
            # Try to delete corrupted file so we don't get stuck
            try:
                if self.notification_file.exists():
                    self.notification_file.unlink()
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
