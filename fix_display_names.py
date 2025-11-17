#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Fix display_name format in container JSON files.
Converts display_name from list format to single string.
"""

import json
import os
from pathlib import Path
import shutil
from datetime import datetime

def fix_display_name(config_dir='config/containers'):
    """Fix display_name format in all container configuration files."""

    containers_dir = Path(config_dir)
    if not containers_dir.exists():
        print(f"❌ Directory {config_dir} not found!")
        return

    # Create backup directory
    backup_dir = Path(f"config.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    backup_dir.mkdir(exist_ok=True)

    fixed_count = 0
    skipped_count = 0

    # Process each JSON file
    for json_file in containers_dir.glob('*.json'):
        try:
            # Read current configuration
            with open(json_file, 'r') as f:
                data = json.load(f)

            # Check if display_name needs fixing
            if 'display_name' in data:
                current_display = data['display_name']

                # If it's a list, convert to string
                if isinstance(current_display, list):
                    # Take the first element if it exists, otherwise use container name
                    if len(current_display) > 0:
                        new_display_name = str(current_display[0])
                    else:
                        # Fallback to container_name or docker_name
                        new_display_name = data.get('container_name') or data.get('docker_name') or json_file.stem

                    print(f"📝 {json_file.name}: Converting {current_display} → '{new_display_name}'")

                    # Backup original file
                    backup_file = backup_dir / json_file.name
                    shutil.copy2(json_file, backup_file)

                    # Update display_name
                    data['display_name'] = new_display_name

                    # Write updated configuration
                    with open(json_file, 'w') as f:
                        json.dump(data, f, indent=2)

                    fixed_count += 1

                elif isinstance(current_display, str):
                    print(f"✅ {json_file.name}: Already a string ('{current_display}')")
                    skipped_count += 1
                else:
                    print(f"⚠️  {json_file.name}: Unknown display_name type: {type(current_display)}")
                    skipped_count += 1
            else:
                print(f"ℹ️  {json_file.name}: No display_name field")
                skipped_count += 1

        except (RuntimeError) as e:
            print(f"❌ Error processing {json_file.name}: {e}")

    print(f"\n📊 Summary:")
    print(f"  - Fixed: {fixed_count} files")
    print(f"  - Skipped: {skipped_count} files")
    if fixed_count > 0:
        print(f"  - Backup saved to: {backup_dir}")

    return fixed_count > 0

if __name__ == "__main__":
    print("🔧 Fixing display_name format in container JSON files...")
    print("-" * 50)

    if fix_display_name():
        print("\n✨ Display names have been fixed!")
        print("Please restart the Web UI to see the changes.")
    else:
        print("\n✅ No changes needed - all display names are already in correct format!")