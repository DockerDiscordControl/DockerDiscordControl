#!/usr/bin/env python3
import sys
sys.path.insert(0, '/Volumes/appdata/dockerdiscordcontrol')

from utils.donation_manager import get_donation_manager

dm = get_donation_manager()

# Get current state
data = dm.load_data()
print(f"Before: Fuel = ${data['fuel_data']['current_fuel']:.2f}, Total = ${data['fuel_data'].get('total_received_permanent', 0):.2f}")

# Add $5
result = dm.add_fuel(5.0, 'test', 'Manual Test')

# Check result
print(f"After: Fuel = ${result['fuel_data']['current_fuel']:.2f}, Total = ${result['fuel_data'].get('total_received_permanent', 0):.2f}")

# Reload to verify it was saved
data = dm.load_data()
print(f"Reloaded: Fuel = ${data['fuel_data']['current_fuel']:.2f}, Total = ${data['fuel_data'].get('total_received_permanent', 0):.2f}")