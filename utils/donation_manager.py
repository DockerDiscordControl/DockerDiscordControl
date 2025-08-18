# -*- coding: utf-8 -*-
"""
Donation Manager - Tracks and manages donation status across all devices
"""

import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from utils.logging_utils import get_module_logger

logger = get_module_logger('donation_manager')

class DonationManager:
    """Manages donation tracking and status."""
    
    def __init__(self, config_dir: str = "config"):
        """Initialize the donation manager.
        
        Args:
            config_dir: Directory where donation.json will be stored
        """
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.config_dir / "donation.json"
        logger.info(f"Donation config file: {self.config_file}")
    
    def get_default_data(self) -> Dict[str, Any]:
        """Get default donation data structure."""
        return {
            "last_donation_timestamp": None,
            "donation_history": [],  # List of donation events with timestamps
            "total_donations": 0,
            "donation_stats": {
                "coffee": 0,
                "paypal": 0,
                "discord_coffee": 0,
                "discord_paypal": 0,
                "discord_broadcast": 0
            }
        }
    
    def load_data(self) -> Dict[str, Any]:
        """Load donation data from file.
        
        Returns:
            Dictionary containing donation data
        """
        default_data = self.get_default_data()
        
        if not self.config_file.exists():
            logger.info("Donation data not found, creating new file")
            self.save_data(default_data)
            return default_data
        
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Ensure all keys exist
            for key, default_value in default_data.items():
                if key not in data:
                    data[key] = default_value
            
            return data
        except Exception as e:
            logger.error(f"Error loading donation data: {e}")
            return default_data
    
    def save_data(self, data: Dict[str, Any]) -> bool:
        """Save donation data to file.
        
        Args:
            data: Donation data to save
            
        Returns:
            True if successful, False otherwise
        """
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.info("Donation data saved successfully")
            return True
        except Exception as e:
            logger.error(f"Error saving donation data: {e}")
            return False
    
    def record_donation(self, donation_type: str, user_identifier: Optional[str] = None) -> Dict[str, Any]:
        """Record a new donation click.
        
        Args:
            donation_type: Type of donation (coffee/paypal/discord_*)
            user_identifier: User identifier (username, IP, Discord user, etc.)
            
        Returns:
            Updated donation data
        """
        data = self.load_data()
        timestamp = datetime.now(timezone.utc).timestamp() * 1000  # JavaScript compatible timestamp
        
        # Update last donation timestamp
        data["last_donation_timestamp"] = timestamp
        
        # Add to history (keep last 100 entries)
        donation_event = {
            "timestamp": timestamp,
            "type": donation_type,
            "date": datetime.now(timezone.utc).isoformat(),
            "user": user_identifier
        }
        data["donation_history"].insert(0, donation_event)
        data["donation_history"] = data["donation_history"][:100]  # Keep only last 100
        
        # Update stats
        data["total_donations"] += 1
        if donation_type in data["donation_stats"]:
            data["donation_stats"][donation_type] += 1
        
        # Save and log
        self.save_data(data)
        logger.info(f"Donation recorded: {donation_type} at {donation_event['date']} by {user_identifier}")
        
        return data
    
    def get_status(self) -> Dict[str, Any]:
        """Get current donation status for heart display.
        
        Returns:
            Dictionary with donation status info
        """
        data = self.load_data()
        
        if not data["last_donation_timestamp"]:
            return {
                "has_donated": False,
                "days_since_donation": None,
                "timestamp": None
            }
        
        # Calculate days since last donation
        now = datetime.now(timezone.utc).timestamp() * 1000
        days_since = (now - data["last_donation_timestamp"]) / (1000 * 60 * 60 * 24)
        
        return {
            "has_donated": True,
            "days_since_donation": days_since,
            "timestamp": data["last_donation_timestamp"],
            "total_donations": data["total_donations"],
            "stats": data["donation_stats"]
        }
    
    def get_history(self, limit: int = 10) -> list:
        """Get recent donation history.
        
        Args:
            limit: Number of entries to return
            
        Returns:
            List of recent donation events
        """
        data = self.load_data()
        return data["donation_history"][:limit]
    
    async def send_donation_message(self, bot) -> Dict[str, Any]:
        """Stub method for Discord donation message functionality.
        
        This is a placeholder for future Discord integration.
        Currently only returns success=False to prevent errors.
        
        Args:
            bot: Discord bot instance
            
        Returns:
            Dictionary with success status and message
        """
        return {
            "success": False,
            "message": "Discord donation messages not implemented yet"
        }

# Singleton instance
_donation_manager = None

def get_donation_manager() -> DonationManager:
    """Get or create the singleton donation manager instance."""
    global _donation_manager
    if _donation_manager is None:
        _donation_manager = DonationManager()
    return _donation_manager