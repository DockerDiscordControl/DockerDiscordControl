#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Script to reactivate all inactive containers.
This sets 'active': true in all container JSON files in config/containers/
"""

import json
from pathlib import Path

def reactivate_all_containers():
    """Set all containers to active=true."""
    containers_dir = Path('config/containers')

    if not containers_dir.exists():
        print(f"❌ Error: {containers_dir} does not exist!")
        return

    print("🔄 Reactivating all containers...\n")

    updated_count = 0
    already_active = 0

    for container_file in sorted(containers_dir.glob('*.json')):
        try:
            # Read container config
            with open(container_file, 'r') as f:
                container_config = json.load(f)

            container_name = container_config.get('container_name', container_file.stem)
            was_active = container_config.get('active', False)

            if was_active:
                print(f"✓ {container_name:<30} Already active")
                already_active += 1
            else:
                # Set to active
                container_config['active'] = True

                # Save back
                with open(container_file, 'w') as f:
                    json.dump(container_config, f, indent=2, ensure_ascii=False)

                print(f"✅ {container_name:<30} Reactivated!")
                updated_count += 1

        except (IOError, OSError, PermissionError, RuntimeError, docker.errors.APIError, docker.errors.DockerException, json.JSONDecodeError) as e:
            print(f"❌ Error processing {container_file.name}: {e}")

    print(f"\n📊 Summary:")
    print(f"   - Already active: {already_active}")
    print(f"   - Reactivated: {updated_count}")
    print(f"   - Total containers: {already_active + updated_count}")

    if updated_count > 0:
        print(f"\n🔄 Please restart the Discord bot for changes to take effect:")
        print(f"   docker restart dockerdiscordcontrol")

if __name__ == '__main__':
    reactivate_all_containers()
