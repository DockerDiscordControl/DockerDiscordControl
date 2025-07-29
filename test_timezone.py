#!/usr/bin/env python3
import sys
sys.path.append('.')
from datetime import datetime, timezone
from utils.time_utils import format_datetime_with_timezone

print("=== TIMEZONE CONVERSION TEST ===")

# Test current time
utc_now = datetime.now(timezone.utc)
print(f"UTC time: {utc_now.strftime('%H:%M:%S')}")

# Test Berlin conversion (should be +2 hours in summer)
berlin_time = format_datetime_with_timezone(utc_now, 'Europe/Berlin', '%H:%M:%S')
print(f"Berlin time: {berlin_time}")

# Test auto conversion (from config)
auto_time = format_datetime_with_timezone(utc_now, None, '%H:%M:%S')
print(f"Auto time (config): {auto_time}")

# Calculate expected
expected_hour = (utc_now.hour + 2) % 24
print(f"Expected Berlin: {expected_hour:02d}:XX:XX")

if berlin_time.startswith(f"{expected_hour:02d}:"):
    print("✅ TIMEZONE CONVERSION WORKS!")
else:
    print("❌ TIMEZONE CONVERSION FAILED!")
