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
            },
            "fuel_data": {
                "current_fuel": 0.0,  # Current fuel amount in euros
                "last_update": None,  # Last time fuel was updated
                "donation_amounts": [],  # List of actual donation amounts
                "total_received_permanent": 0.0  # Permanent record of total donations (never decreases)
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
    
    def save_data(self, data: Dict[str, Any], silent: bool = False) -> bool:
        """Save donation data to file.
        
        Args:
            data: Donation data to save
            silent: If True, use DEBUG instead of INFO for success logging
            
        Returns:
            True if successful, False otherwise
        """
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            if silent:
                logger.debug("Donation data saved successfully")
            else:
                logger.info("Donation data saved successfully")
            return True
        except Exception as e:
            logger.error(f"Error saving donation data: {e}")
            return False
    
    def update_fuel(self, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Update fuel based on time passed (consume 1€ per day).
        
        Args:
            data: Optional existing data to update
            
        Returns:
            Updated data with current fuel level
        """
        if data is None:
            data = self.load_data()
        
        # Initialize fuel_data if not present
        if "fuel_data" not in data:
            data["fuel_data"] = {
                "current_fuel": 0.0,
                "last_update": None,
                "donation_amounts": []
            }
        
        fuel_data = data["fuel_data"]
        now = datetime.now(timezone.utc)
        
        # If we have a last update time, calculate fuel consumption
        if fuel_data["last_update"]:
            last_update = datetime.fromisoformat(fuel_data["last_update"])
            days_passed = (now - last_update).total_seconds() / (60 * 60 * 24)
            
            # Consume 1€ per day
            fuel_consumed = days_passed * 1.0
            fuel_data["current_fuel"] = max(0, fuel_data["current_fuel"] - fuel_consumed)
            
            logger.debug(f"Fuel consumption: {fuel_consumed:.2f}€ over {days_passed:.2f} days")
        
        # Update timestamp
        fuel_data["last_update"] = now.isoformat()
        
        return data
    
    def add_fuel(self, amount: float, donation_type: str = "manual", user_identifier: Optional[str] = None) -> Dict[str, Any]:
        """Add fuel (donation amount) to the system.
        
        Args:
            amount: Amount in euros to add
            donation_type: Type of donation
            user_identifier: User identifier
            
        Returns:
            Updated data
        """
        data = self.load_data()
        
        # Update fuel first (to consume any time-based reduction)
        data = self.update_fuel(data)
        
        # Add new fuel
        if "fuel_data" not in data:
            data["fuel_data"] = {
                "current_fuel": 0.0,
                "last_update": None,
                "donation_amounts": []
            }
        
        data["fuel_data"]["current_fuel"] += amount
        
        # If it's a positive amount (donation), handle evolution and fuel logic like gas tank
        if amount > 0:
            # Store old total for evolution level comparison
            old_total = data["fuel_data"].get("total_received_permanent", 0.0)
            
            if "total_received_permanent" not in data["fuel_data"]:
                # Calculate from history if not present
                total = 0.0
                for donation in data["fuel_data"].get("donation_amounts", []):
                    if donation.get("amount", 0) > 0:
                        total += donation["amount"]
                data["fuel_data"]["total_received_permanent"] = total
                old_total = total
            
            new_total = old_total + amount
            data["fuel_data"]["total_received_permanent"] = new_total
            
            # Import evolution thresholds for level-up detection
            from utils.mech_evolutions import EVOLUTION_THRESHOLDS
            
            # Calculate what evolution levels can be reached with this total
            old_level = 0
            new_level = 0
            
            for level in range(9, -1, -1):  # Check from highest to lowest
                if old_total >= EVOLUTION_THRESHOLDS[level]:
                    old_level = level
                    break
            
            for level in range(9, -1, -1):  # Check from highest to lowest
                if new_total >= EVOLUTION_THRESHOLDS[level]:
                    new_level = level
                    break
            
            # Check for evolution level up
            evolution_level_up = new_level > old_level
            
            if evolution_level_up:
                logger.info(f"Evolution level up from {old_level} to {new_level}!")
                
                # When evolution happens, reset fuel to $10 minimum
                # The evolution "costs" all accumulated fuel
                MINIMUM_FUEL_AFTER_EVOLUTION = 10.0
                
                # Calculate what the new fuel should be after evolution
                # Start with the amount that pushed us over the threshold
                overflow = new_total - EVOLUTION_THRESHOLDS[new_level]
                
                # Set fuel to overflow amount or minimum, whichever is higher
                new_fuel_amount = max(overflow, MINIMUM_FUEL_AFTER_EVOLUTION)
                
                # Set the fuel directly (don't add to existing)
                data["fuel_data"]["current_fuel"] = new_fuel_amount
                
                logger.info(f"Fuel after evolution: ${new_fuel_amount:.2f} (overflow: ${overflow:.2f}, minimum: ${MINIMUM_FUEL_AFTER_EVOLUTION:.2f})")
            else:
                # No evolution, fuel just increases normally (already added above)
                logger.info(f"Fuel increased by: ${amount:.2f}")
            
            logger.info(f"Total donations received (permanent): ${new_total:.2f}")
        
        # Record the donation amount
        data["fuel_data"]["donation_amounts"].append({
            "amount": amount,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": donation_type,
            "user": user_identifier
        })
        
        # Keep only last 100 donation amounts
        data["fuel_data"]["donation_amounts"] = data["fuel_data"]["donation_amounts"][-100:]
        
        # Use silent save for consumption to reduce log spam
        is_consumption = donation_type == "consumption"
        self.save_data(data, silent=is_consumption)
        
        # Use DEBUG for consumption to reduce log spam, INFO for actual donations
        log_level = logger.debug if is_consumption else logger.info
        log_level(f"Added {amount}€ fuel. New total: {data['fuel_data']['current_fuel']:.2f}€")
        
        return data
    
    def record_donation(self, donation_type: str, user_identifier: Optional[str] = None, amount: Optional[float] = None) -> Dict[str, Any]:
        """Record a new donation click.
        
        Args:
            donation_type: Type of donation (coffee/paypal/discord_*)
            user_identifier: User identifier (username, IP, Discord user, etc.)
            amount: Optional donation amount in euros
            
        Returns:
            Updated donation data
        """
        data = self.load_data()
        timestamp = datetime.now(timezone.utc).timestamp() * 1000  # JavaScript compatible timestamp
        
        # If amount is provided, add it as fuel
        if amount and amount > 0:
            data = self.add_fuel(amount, donation_type, user_identifier)
        else:
            # Just update fuel to apply time-based consumption
            data = self.update_fuel(data)
        
        # Update last donation timestamp
        data["last_donation_timestamp"] = timestamp
        
        # Add to history (keep last 100 entries)
        donation_event = {
            "timestamp": timestamp,
            "type": donation_type,
            "date": datetime.now(timezone.utc).isoformat(),
            "user": user_identifier,
            "amount": amount
        }
        data["donation_history"].insert(0, donation_event)
        data["donation_history"] = data["donation_history"][:100]  # Keep only last 100
        
        # Update stats
        data["total_donations"] += 1
        if donation_type in data["donation_stats"]:
            data["donation_stats"][donation_type] += 1
        
        # Save and log
        self.save_data(data)
        logger.info(f"Donation recorded: {donation_type} at {donation_event['date']} by {user_identifier}, amount: {amount}€")
        
        return data
    
    def get_status(self) -> Dict[str, Any]:
        """Get current donation status for mech display.
        
        Returns:
            Dictionary with donation status info including fuel data
        """
        data = self.load_data()
        
        # Update fuel to get current amount after consumption
        data = self.update_fuel(data)
        self.save_data(data)  # Save the updated fuel
        
        # Get current fuel amount
        current_fuel = 0.0
        if "fuel_data" in data:
            current_fuel = data["fuel_data"].get("current_fuel", 0.0)
        
        # Get permanent total donations (for evolution level - never decreases)
        total_donations_received = 0.0
        if "fuel_data" in data:
            # Use permanent total if available
            if "total_received_permanent" in data["fuel_data"]:
                total_donations_received = data["fuel_data"]["total_received_permanent"]
            else:
                # Calculate from history if not present (backwards compatibility)
                for donation in data["fuel_data"].get("donation_amounts", []):
                    if donation.get("amount", 0) > 0:
                        total_donations_received += donation["amount"]
                # Store it for next time
                data["fuel_data"]["total_received_permanent"] = total_donations_received
        
        result = {
            "has_donated": data["last_donation_timestamp"] is not None,
            "timestamp": data["last_donation_timestamp"],
            "total_donations": data["total_donations"],
            "stats": data["donation_stats"],
            "total_amount": current_fuel,  # Current fuel level in euros (for speed)
            "total_donations_received": total_donations_received,  # Total ever donated (for evolution)
            "fuel_data": data.get("fuel_data", {})
        }
        
        # Calculate days since last donation if applicable
        if data["last_donation_timestamp"]:
            now = datetime.now(timezone.utc).timestamp() * 1000
            days_since = (now - data["last_donation_timestamp"]) / (1000 * 60 * 60 * 24)
            result["days_since_donation"] = days_since
        else:
            result["days_since_donation"] = None
        
        return result
    
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