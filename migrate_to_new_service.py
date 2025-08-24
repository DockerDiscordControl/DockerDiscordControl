#!/usr/bin/env python3
"""
Migration script to transfer data from old donation.json to new MechService format
"""

import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from services.mech_service import get_mech_service

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def migrate_donation_data():
    """Migrate from old donation.json to new mech service format"""
    
    old_file = Path("config/donation.json")
    new_file = Path("config/mech_donations.json")
    
    if not old_file.exists():
        logger.error(f"Old donation file not found: {old_file}")
        return False
    
    if new_file.exists():
        logger.warning(f"New service file already exists: {new_file}")
        response = input("Overwrite existing new service data? (y/N): ")
        if response.lower() != 'y':
            logger.info("Migration cancelled")
            return False
        # Backup existing new file
        backup_file = new_file.with_suffix(f".backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
        new_file.rename(backup_file)
        logger.info(f"Backed up existing file to: {backup_file}")
    
    try:
        # Load old data
        logger.info(f"Loading old donation data from {old_file}")
        with open(old_file, 'r') as f:
            old_data = json.load(f)
        
        # Extract key information
        fuel_data = old_data.get('fuel_data', {})
        current_fuel = fuel_data.get('current_fuel', 0.0)
        total_donations = fuel_data.get('total_received_permanent', 0.0)
        donation_history = old_data.get('donation_history', [])
        
        logger.info(f"Old system stats:")
        logger.info(f"  Current fuel: ${current_fuel:.2f}")
        logger.info(f"  Total donations: ${total_donations:.2f}")
        logger.info(f"  History entries: {len(donation_history)}")
        
        # Create synthetic donation entries for new service
        # We'll create one big "migration" donation to set the correct totals
        mech_service = get_mech_service()
        
        if total_donations > 0:
            # Add the total amount as a single migration donation
            logger.info(f"Adding migration donation of ${total_donations:.2f}")
            final_state = mech_service.add_donation(
                username="MIGRATION_FROM_OLD_SYSTEM",
                amount=int(total_donations)
            )
            
            logger.info(f"Migration completed!")
            logger.info(f"New service state:")
            logger.info(f"  Level: {final_state.level} ({final_state.level_name})")
            logger.info(f"  Fuel: ${final_state.fuel}")
            logger.info(f"  Total donated: ${final_state.total_donated}")
            logger.info(f"  Glvl: {final_state.glvl}/{final_state.glvl_max}")
        else:
            logger.info("No donations to migrate (total=0)")
        
        # Backup old file
        backup_old = old_file.with_suffix(f".backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
        old_file.rename(backup_old)
        logger.info(f"Backed up old file to: {backup_old}")
        
        return True
        
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        return False

if __name__ == "__main__":
    logger.info("=== DDC Donation Data Migration ===")
    logger.info("Migrating from old donation.json to new MechService format")
    
    success = migrate_donation_data()
    
    if success:
        logger.info("✅ Migration completed successfully!")
        logger.info("The old donation.json has been backed up")
        logger.info("New MechService is ready to use")
    else:
        logger.error("❌ Migration failed!")
        logger.info("Check logs above for details")
    
    print("\nMigration finished.")