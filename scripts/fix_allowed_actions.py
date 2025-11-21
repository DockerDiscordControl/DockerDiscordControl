#!/usr/bin/env python3
"""
Fix allowed_actions in container JSON files.
Ensures each container has at least 'status' permission.
"""

import json
from pathlib import Path

def fix_container_actions():
    """Fix allowed_actions in all container JSON files."""
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

    fixed_count = 0
    error_count = 0

    for file in containers_dir.glob('*.json'):
        try:
            with open(file, 'r') as f:
                data = json.load(f)

            # Check if allowed_actions needs fixing
            if 'allowed_actions' in data:
                if not data['allowed_actions']:
                    # Empty array, add default actions
                    data['allowed_actions'] = ['status', 'start', 'stop', 'restart']
                    with open(file, 'w') as f:
                        json.dump(data, f, indent=2)
                    print(f'✅ Fixed {file.name}: allowed_actions={data["allowed_actions"]}')
                    fixed_count += 1
                else:
                    print(f'✓ {file.name} already has allowed_actions: {data["allowed_actions"]}')
            else:
                # Missing allowed_actions, add it
                data['allowed_actions'] = ['status', 'start', 'stop', 'restart']
                with open(file, 'w') as f:
                    json.dump(data, f, indent=2)
                print(f'✅ Added allowed_actions to {file.name}: {data["allowed_actions"]}')
                fixed_count += 1

        except (IOError, OSError, PermissionError, RuntimeError, json.JSONDecodeError) as e:
            print(f'❌ Error processing {file.name}: {e}')
            error_count += 1

    print(f'\n📊 Summary: {fixed_count} files fixed, {error_count} errors')
    return error_count == 0

if __name__ == '__main__':
    success = fix_container_actions()
    exit(0 if success else 1)
