#!/usr/bin/env python3
"""
Set the active flag on container JSON files.
This script marks containers as active/inactive based on current configuration.
"""

import json
from pathlib import Path
import sys
import docker

def set_active_containers(mark_all_active=False):
    """
    Set active flag on container files.

    Args:
        mark_all_active: If True, mark all containers as active (for initial migration)
                        If False, read from main config to determine active containers
    """
    # Try multiple possible paths
    possible_paths = [
        Path('/app/config/containers'),
        Path('/mnt/user/appdata/dockerdiscordcontrol/config/containers'),
        Path('config/containers'),
        Path('/Volumes/appdata/dockerdiscordcontrol/config/containers')
    ]

    containers_dir = None
    for path in possible_paths:
        if path.exists():
            containers_dir = path
            print(f"Using containers directory: {containers_dir}")
            break

    if not containers_dir:
        print(f"❌ Containers directory not found in any of: {possible_paths}")
        return False

    if mark_all_active:
        print("📝 Marking ALL containers as active (initial migration)")
        active_containers = None  # Mark all as active
    else:
        # Load active containers from main config
        config_path = containers_dir.parent / 'config.json'
        if config_path.exists():
            try:
                with open(config_path, 'r') as f:
                    config = json.load(f)
                servers = config.get('servers', [])
                active_containers = set()
                for server in servers:
                    container_name = server.get('docker_name') or server.get('container_name')
                    if container_name:
                        active_containers.add(container_name)
                print(f"📝 Found {len(active_containers)} active containers in config")
            except (AttributeError, IOError, KeyError, OSError, PermissionError, RuntimeError, TypeError, docker.errors.APIError, docker.errors.DockerException, json.JSONDecodeError) as e:
                print(f"❌ Error loading config: {e}")
                return False
        else:
            print("⚠️ No config.json found, marking all as active")
            active_containers = None

    updated_count = 0
    error_count = 0

    for file in containers_dir.glob('*.json'):
        try:
            with open(file, 'r') as f:
                data = json.load(f)

            container_name = data.get('container_name') or file.stem

            # Determine if container should be active
            if active_containers is None:
                # Mark all as active (initial migration)
                should_be_active = True
            else:
                # Check if in active list
                should_be_active = container_name in active_containers

            # Update active flag if needed
            current_active = data.get('active')
            if current_active != should_be_active:
                data['active'] = should_be_active
                with open(file, 'w') as f:
                    json.dump(data, f, indent=2)
                status = "✅ ACTIVE" if should_be_active else "⛔ INACTIVE"
                print(f'{status} {file.name}: active={should_be_active}')
                updated_count += 1
            else:
                status = "✓ " if should_be_active else "○ "
                print(f'{status} {file.name} already correct: active={should_be_active}')

        except (IOError, OSError, PermissionError, RuntimeError) as e:
            print(f'❌ Error processing {file.name}: {e}')
            error_count += 1

    print(f'\n📊 Summary: {updated_count} files updated, {error_count} errors')
    return error_count == 0

if __name__ == '__main__':
    # Check command line arguments
    mark_all = '--all' in sys.argv or '-a' in sys.argv

    if mark_all:
        print("🚀 Running in MIGRATION mode - marking ALL containers as active")
        print("   Use this for initial setup to preserve existing containers")
    else:
        print("🔄 Running in SYNC mode - syncing active status from config")
        print("   Use --all or -a to mark all containers as active")

    success = set_active_containers(mark_all_active=mark_all)
    exit(0 if success else 1)
