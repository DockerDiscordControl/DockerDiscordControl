#!/usr/bin/env python3
"""
Fix corrupted display_name fields in container JSON files.
This script cleans up recursive string conversions.
"""

import json
import ast
from pathlib import Path
import docker

def fix_display_name(display_name_raw, container_name=None):
    """Clean up a corrupted display_name field."""
    import re

    # If it's already a proper list of 2 strings, return it
    if isinstance(display_name_raw, list) and len(display_name_raw) == 2:
        if all(isinstance(x, str) for x in display_name_raw):
            # Check if they're not stringified lists
            if not (display_name_raw[0].startswith('[') or display_name_raw[1].startswith('[')):
                return display_name_raw

    # Convert to string and try to extract actual names
    raw_str = str(display_name_raw)

    # Common patterns to look for actual names
    patterns = [
        r"'([A-Za-z0-9\-_\s]+)'",  # Single quoted strings
        r'"([A-Za-z0-9\-_\s]+)"',  # Double quoted strings
        r'\\\'([A-Za-z0-9\-_\s]+)\\\'',  # Escaped quotes
    ]

    extracted_names = []
    for pattern in patterns:
        matches = re.findall(pattern, raw_str)
        for match in matches:
            # Skip generic patterns and focus on actual names
            if match and not match.startswith('[') and len(match) > 1:
                # Clean the name
                clean_name = match.strip()
                if clean_name not in extracted_names and clean_name != '':
                    extracted_names.append(clean_name)

    # Look for specific known container names in the mess
    if container_name:
        # Try to find display names that aren't just the container name
        valid_names = []
        for name in extracted_names:
            # Skip escaped versions and focus on clean names
            if '\\' not in name and '[' not in name:
                valid_names.append(name)

        if len(valid_names) >= 2:
            return [valid_names[0], valid_names[1]]
        elif len(valid_names) == 1:
            return [valid_names[0], valid_names[0]]

    # Fallback to container name if available
    if container_name:
        # Use proper display names based on container
        display_map = {
            'Icarus': ['Icarus Server', 'Icarus'],
            'Icarus2': ['Icarus 2 Server', 'Icarus 2'],
            'ProjectZomboid': ['Project Zomboid', 'PZ Server'],
            'Satisfactory': ['Satisfactory Server', 'Satisfactory'],
            'Valheim': ['Valheim Server', 'Valheim'],
            'V-Rising': ['V-Rising Server', 'V-Rising'],
            'duckdns': ['DuckDNS', 'DuckDNS'],
            'AdGuard-Home': ['AdGuard Home', 'AdGuard Home'],
            'dockerdiscordcontrol': ['Discord Control Bot', 'Discord Control Bot'],
            'NginxProxyManager': ['Nginx Proxy Manager', 'Nginx Proxy Manager'],
            'plex': ['Plex Media Server', 'Plex Media Server'],
            'transmission': ['Transmission', 'Transmission']
        }

        if container_name in display_map:
            return display_map[container_name]
        else:
            return [container_name, container_name]

    # Last resort
    return None

def fix_container_files():
    """Fix display_name fields in all container JSON files."""
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

            # Check if display_name needs fixing
            if 'display_name' in data:
                original = data['display_name']
                container_name = data.get('container_name', file.stem)
                fixed = fix_display_name(original, container_name)

                if fixed and fixed != original:
                    data['display_name'] = fixed
                    with open(file, 'w') as f:
                        json.dump(data, f, indent=2)

                    print(f'✅ Fixed {file.name}: display_name={fixed}')
                    fixed_count += 1
                elif fixed:
                    print(f'✓ {file.name} display_name already correct: {fixed}')
                else:
                    # Use container_name as fallback
                    container_name = data.get('container_name', file.stem)
                    data['display_name'] = [container_name, container_name]
                    with open(file, 'w') as f:
                        json.dump(data, f, indent=2)
                    print(f'✅ Fixed {file.name}: display_name={[container_name, container_name]} (fallback)')
                    fixed_count += 1

        except (IOError, OSError, PermissionError, RuntimeError, docker.errors.APIError, docker.errors.DockerException, json.JSONDecodeError) as e:
            print(f'❌ Error processing {file.name}: {e}')
            error_count += 1

    print(f'\n📊 Summary: {fixed_count} files fixed, {error_count} errors')
    return error_count == 0

if __name__ == '__main__':
    success = fix_container_files()
    exit(0 if success else 1)
