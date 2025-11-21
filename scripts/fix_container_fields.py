#!/usr/bin/env python3
"""
Fix missing docker_name and name fields in container JSON files.
This script adds the required fields for compatibility with status handlers.
"""

import json
from pathlib import Path
import docker

def fix_container_files():
    """Add docker_name and name fields to all container JSON files."""
    containers_dir = Path('/app/config/containers')

    if not containers_dir.exists():
        print(f"❌ Containers directory not found: {containers_dir}")
        return False

    fixed_count = 0
    error_count = 0

    for file in containers_dir.glob('*.json'):
        try:
            with open(file, 'r') as f:
                data = json.load(f)

            # Check if fix is needed
            needs_fix = False

            if 'container_name' in data:
                if 'docker_name' not in data:
                    data['docker_name'] = data['container_name']
                    needs_fix = True

                if 'name' not in data:
                    data['name'] = data['container_name']
                    needs_fix = True

            if needs_fix:
                with open(file, 'w') as f:
                    json.dump(data, f, indent=2)

                print(f'✅ Fixed {file.name}: docker_name={data.get("docker_name")}, name={data.get("name")}')
                fixed_count += 1
            else:
                print(f'✓ {file.name} already has required fields')

        except (AttributeError, IOError, KeyError, OSError, PermissionError, RuntimeError, TypeError, docker.errors.APIError, docker.errors.DockerException) as e:
            print(f'❌ Error processing {file.name}: {e}')
            error_count += 1

    print(f'\n📊 Summary: {fixed_count} files fixed, {error_count} errors')
    return error_count == 0

if __name__ == '__main__':
    success = fix_container_files()
    exit(0 if success else 1)
