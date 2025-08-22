#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
One-time migration script to add historical donations to fuel_data
"""

import json
from datetime import datetime, timezone
from pathlib import Path

def migrate_donations():
    """Migrate historical donations to fuel_data."""
    
    config_file = Path("config/donation.json")
    
    # Read the current donation file
    with open(config_file, 'r') as f:
        data = json.load(f)
    
    print('=== Migrating historical donations to fuel_data ===')
    
    # Ensure fuel_data exists
    if 'fuel_data' not in data:
        data['fuel_data'] = {
            'current_fuel': 0.0,
            'last_update': None,
            'donation_amounts': []
        }
    
    # Add the historical donations to fuel_data if not already there
    added_count = 0
    for event in data.get('donation_history', []):
        if event.get('amount') and event['amount'] > 0:
            # Check if this donation is already in fuel_data by checking date and amount
            timestamp_str = event.get('date', '')
            found = False
            
            for fuel in data['fuel_data']['donation_amounts']:
                if (fuel.get('type') != 'consumption' and 
                    fuel.get('amount') == event['amount'] and
                    fuel.get('timestamp', '').startswith(timestamp_str[:10])):  # Check same day
                    found = True
                    break
            
            if not found:
                # Add to fuel_data
                fuel_entry = {
                    'amount': event['amount'],
                    'timestamp': event.get('date', datetime.now(timezone.utc).isoformat()),
                    'type': event.get('type', 'donation'),
                    'user': event.get('user', 'Historical')
                }
                data['fuel_data']['donation_amounts'].insert(0, fuel_entry)
                print(f"Added ${event['amount']:.2f} donation to fuel_data from {event.get('user', 'unknown')}")
                added_count += 1
    
    if added_count > 0:
        # Sort by timestamp (oldest first)
        data['fuel_data']['donation_amounts'].sort(key=lambda x: x.get('timestamp', ''))
        
        # Recalculate current fuel (sum of all positive minus all negative)
        current_fuel = 0
        total_donated = 0
        for fuel in data['fuel_data']['donation_amounts']:
            amount = fuel.get('amount', 0)
            if amount > 0:
                total_donated += amount
            current_fuel += amount  # This includes consumption (negative values)
        
        # Update current fuel
        data['fuel_data']['current_fuel'] = max(0, current_fuel)  # Don't go negative
        data['fuel_data']['last_update'] = datetime.now(timezone.utc).isoformat()
        
        print(f'\nMigration complete! Added {added_count} donations')
        print(f'Total donations tracked: ${total_donated:.2f}')
        print(f'Current fuel level: ${current_fuel:.2f}')
        
        # Create a backup
        backup_file = config_file.with_suffix('.json.backup')
        with open(backup_file, 'w') as f:
            json.dump(data, f, indent=2)
        print(f'Backup saved to {backup_file}')
        
        # Try to save (this might fail due to permissions)
        try:
            with open(config_file, 'w') as f:
                json.dump(data, f, indent=2)
            print(f'Successfully updated {config_file}')
        except PermissionError:
            print(f'\n⚠️  Could not update {config_file} due to permissions')
            print('Updated data saved to backup file instead')
            print('\nTo apply changes, run:')
            print(f'  cp {backup_file} {config_file}')
    else:
        print('No migrations needed - all donations already tracked')
        
        # Calculate totals for info
        total_donated = 0
        for fuel in data['fuel_data']['donation_amounts']:
            if fuel.get('amount', 0) > 0:
                total_donated += fuel['amount']
        
        print(f'Total donations in fuel_data: ${total_donated:.2f}')
        print(f'Current fuel level: ${data["fuel_data"]["current_fuel"]:.2f}')

if __name__ == "__main__":
    migrate_donations()