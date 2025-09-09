#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Migration script to convert current config structure to new modular structure.
Creates individual JSON files for each channel and container.
"""

import json
import os
from pathlib import Path
from typing import Dict, Any

def create_directory_safe(path: Path) -> bool:
    """Create directory if it doesn't exist, handling permissions."""
    try:
        path.mkdir(exist_ok=True, parents=True)
        print(f"✅ Created directory: {path}")
        return True
    except Exception as e:
        print(f"❌ Could not create {path}: {e}")
        return False

def save_json_safe(file_path: Path, data: Dict[str, Any]) -> bool:
    """Save JSON data with proper error handling."""
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"✅ Created: {file_path}")
        return True
    except Exception as e:
        print(f"❌ Could not create {file_path}: {e}")
        return False

def migrate_channels_config():
    """Migrate channels_config.json to individual channel files."""
    print("\n🔄 MIGRATING CHANNELS CONFIG...")
    
    config_dir = Path("./config")
    channels_dir = config_dir / "channels"
    channels_file = config_dir / "channels_config.json"
    
    if not channels_file.exists():
        print(f"❌ {channels_file} not found")
        return False
    
    # Create channels directory
    if not create_directory_safe(channels_dir):
        return False
    
    # Load current channels config
    try:
        with open(channels_file, 'r', encoding='utf-8') as f:
            channels_data = json.load(f)
    except Exception as e:
        print(f"❌ Could not read {channels_file}: {e}")
        return False
    
    # Extract individual channels
    channel_permissions = channels_data.get("channel_permissions", {})
    
    for channel_id, channel_config in channel_permissions.items():
        channel_file = channels_dir / f"{channel_id}.json"
        
        # Add channel_id to the config for reference
        channel_config["channel_id"] = channel_id
        
        if not save_json_safe(channel_file, channel_config):
            return False
    
    # Create default channel config
    default_config = {
        "name": "Default Channel Settings",
        "commands": {
            "serverstatus": True,
            "command": False,
            "control": False,
            "schedule": False
        },
        "post_initial": False,
        "update_interval_minutes": 10,
        "inactivity_timeout_minutes": 10,
        "enable_auto_refresh": True,
        "recreate_messages_on_inactivity": True
    }
    
    default_file = channels_dir / "default.json"
    save_json_safe(default_file, default_config)
    
    print(f"✅ Migrated {len(channel_permissions)} channels + default config")
    return True

def migrate_docker_config():
    """Migrate docker_config.json to individual container files + docker_settings.json."""
    print("\n🔄 MIGRATING DOCKER CONFIG...")
    
    config_dir = Path("./config")
    containers_dir = config_dir / "containers"
    docker_file = config_dir / "docker_config.json"
    
    if not docker_file.exists():
        print(f"❌ {docker_file} not found")
        return False
    
    # Create containers directory
    if not create_directory_safe(containers_dir):
        return False
    
    # Load current docker config
    try:
        with open(docker_file, 'r', encoding='utf-8') as f:
            docker_data = json.load(f)
    except Exception as e:
        print(f"❌ Could not read {docker_file}: {e}")
        return False
    
    # Extract individual containers
    servers = docker_data.get("servers", [])
    
    for server in servers:
        container_name = server.get("docker_name", server.get("name", "unknown"))
        container_file = containers_dir / f"{container_name}.json"
        
        if not save_json_safe(container_file, server):
            return False
    
    # Create docker_settings.json with system settings
    docker_settings = {
        "docker_socket_path": docker_data.get("docker_socket_path", "/var/run/docker.sock"),
        "container_command_cooldown": docker_data.get("container_command_cooldown", 5),
        "docker_api_timeout": docker_data.get("docker_api_timeout", 30),
        "max_log_lines": docker_data.get("max_log_lines", 50)
    }
    
    settings_file = config_dir / "docker_settings.json"
    save_json_safe(settings_file, docker_settings)
    
    print(f"✅ Migrated {len(servers)} containers + docker settings")
    return True

def create_new_config_files():
    """Create new config files that don't exist yet."""
    print("\n🔄 CREATING NEW CONFIG FILES...")
    
    config_dir = Path("./config")
    
    # Load current bot_config to extract data
    bot_config_file = config_dir / "bot_config.json"
    bot_data = {}
    
    if bot_config_file.exists():
        try:
            with open(bot_config_file, 'r', encoding='utf-8') as f:
                bot_data = json.load(f)
        except Exception as e:
            print(f"❌ Could not read bot_config.json: {e}")
    
    # 1. Create main config.json (system settings)
    main_config = {
        "language": bot_data.get("language", "en"),
        "timezone": bot_data.get("timezone", "UTC"),
        "guild_id": bot_data.get("guild_id"),
        "system_logs": {
            "level": "INFO",
            "max_file_size_mb": 10,
            "backup_count": 5,
            "enable_debug": False
        }
    }
    
    config_file = config_dir / "config.json"
    save_json_safe(config_file, main_config)
    
    # 2. Create heartbeat.json
    heartbeat_config = {
        "heartbeat_channel_id": bot_data.get("heartbeat_channel_id"),
        "enabled": bot_data.get("heartbeat_channel_id") is not None,
        "interval_minutes": 30,
        "message_template": "🤖 DDC Heartbeat - All systems operational"
    }
    
    heartbeat_file = config_dir / "heartbeat.json"
    save_json_safe(heartbeat_file, heartbeat_config)
    
    # 3. Create auth.json (sensitive data)
    auth_config = {
        "bot_token": bot_data.get("bot_token"),
        "encryption_enabled": True
    }
    
    auth_file = config_dir / "auth.json"
    save_json_safe(auth_file, auth_config)
    
    # 4. Extract advanced_settings.json from web_config
    web_config_file = config_dir / "web_config.json"
    advanced_settings = {}
    
    if web_config_file.exists():
        try:
            with open(web_config_file, 'r', encoding='utf-8') as f:
                web_data = json.load(f)
                advanced_settings = web_data.get("advanced_settings", {})
        except Exception as e:
            print(f"❌ Could not read web_config.json: {e}")
    
    advanced_file = config_dir / "advanced_settings.json"
    save_json_safe(advanced_file, advanced_settings)
    
    # 5. Create web_ui.json (without advanced_settings)
    web_ui_config = {
        "web_ui_user": "admin",
        "web_ui_password_hash": None,  # Will be set during first setup
        "admin_enabled": True,
        "session_timeout": 3600,
        "donation_disable_key": ""
    }
    
    web_ui_file = config_dir / "web_ui.json"
    save_json_safe(web_ui_file, web_ui_config)
    
    # 6. Rename tasks.json to system_tasks.json
    tasks_file = config_dir / "tasks.json"
    system_tasks_file = config_dir / "system_tasks.json"
    
    if tasks_file.exists() and not system_tasks_file.exists():
        try:
            # Copy content
            with open(tasks_file, 'r', encoding='utf-8') as f:
                tasks_data = json.load(f)
            
            with open(system_tasks_file, 'w', encoding='utf-8') as f:
                json.dump(tasks_data, f, indent=2, ensure_ascii=False)
            
            print(f"✅ Renamed tasks.json to system_tasks.json")
        except Exception as e:
            print(f"❌ Could not rename tasks.json: {e}")
    
    print("✅ Created all new config files")
    return True

def main():
    """Main migration function."""
    print("🚀 STARTING MODULAR CONFIG MIGRATION")
    print("=" * 50)
    
    # Change to the correct directory
    os.chdir("/Volumes/appdata/dockerdiscordcontrol")
    
    success = True
    
    # Step 1: Migrate channels
    if not migrate_channels_config():
        success = False
    
    # Step 2: Migrate docker/containers
    if not migrate_docker_config():
        success = False
    
    # Step 3: Create new config files
    if not create_new_config_files():
        success = False
    
    if success:
        print("\n🎉 MIGRATION COMPLETED SUCCESSFULLY!")
        print("New structure:")
        print("  config/")
        print("  ├── channels/")
        print("  │   ├── 1283494245235294258.json")
        print("  │   ├── 1360187769682657293.json")
        print("  │   └── default.json")
        print("  ├── containers/")
        print("  │   ├── Icarus.json")
        print("  │   ├── Icarus2.json")
        print("  │   └── ...")
        print("  ├── config.json")
        print("  ├── heartbeat.json")
        print("  ├── auth.json")
        print("  ├── advanced_settings.json")
        print("  ├── web_ui.json")
        print("  ├── docker_settings.json")
        print("  └── system_tasks.json")
    else:
        print("\n❌ MIGRATION FAILED!")
        print("Check error messages above.")

if __name__ == "__main__":
    main()