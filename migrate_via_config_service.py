#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Migration script using ConfigService to handle permissions correctly.
"""

import sys
import os

# Add current directory to path
sys.path.insert(0, '.')

from services.config.config_service import get_config_service
from pathlib import Path
import json

def migrate_to_modular_structure():
    """Migrate using ConfigService to handle permissions correctly."""
    print("🚀 STARTING MODULAR CONFIG MIGRATION VIA CONFIG SERVICE")
    print("=" * 60)
    
    config_service = get_config_service()
    config_dir = Path("./config")
    
    # Create directories first
    channels_dir = config_dir / "channels"
    containers_dir = config_dir / "containers"
    
    print("\n📁 Creating directory structure...")
    try:
        channels_dir.mkdir(exist_ok=True)
        print(f"✅ Created: {channels_dir}")
    except Exception as e:
        print(f"❌ Could not create {channels_dir}: {e}")
        
    try:
        containers_dir.mkdir(exist_ok=True)
        print(f"✅ Created: {containers_dir}")
    except Exception as e:
        print(f"❌ Could not create {containers_dir}: {e}")
    
    # 1. Migrate channels_config.json to individual files
    print("\n🔄 MIGRATING CHANNELS CONFIG...")
    
    channels_file = config_dir / "channels_config.json"
    if channels_file.exists():
        try:
            with open(channels_file, 'r', encoding='utf-8') as f:
                channels_data = json.load(f)
                
            channel_permissions = channels_data.get("channel_permissions", {})
            
            for channel_id, channel_config in channel_permissions.items():
                channel_file = channels_dir / f"{channel_id}.json"
                channel_config["channel_id"] = channel_id
                
                try:
                    config_service._save_json_file(channel_file, channel_config)
                    print(f"✅ Created: {channel_file}")
                except Exception as e:
                    print(f"❌ Failed to create {channel_file}: {e}")
            
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
            try:
                config_service._save_json_file(default_file, default_config)
                print(f"✅ Created: {default_file}")
            except Exception as e:
                print(f"❌ Failed to create {default_file}: {e}")
                
            print(f"✅ Migrated {len(channel_permissions)} channels + default config")
            
        except Exception as e:
            print(f"❌ Error reading channels_config.json: {e}")
    
    # 2. Migrate docker_config.json to individual container files
    print("\n🔄 MIGRATING DOCKER CONFIG...")
    
    docker_file = config_dir / "docker_config.json"
    if docker_file.exists():
        try:
            with open(docker_file, 'r', encoding='utf-8') as f:
                docker_data = json.load(f)
                
            servers = docker_data.get("servers", [])
            
            for server in servers:
                container_name = server.get("docker_name", server.get("name", "unknown"))
                container_file = containers_dir / f"{container_name}.json"
                
                try:
                    config_service._save_json_file(container_file, server)
                    print(f"✅ Created: {container_file}")
                except Exception as e:
                    print(f"❌ Failed to create {container_file}: {e}")
            
            # Create docker_settings.json
            docker_settings = {
                "docker_socket_path": docker_data.get("docker_socket_path", "/var/run/docker.sock"),
                "container_command_cooldown": docker_data.get("container_command_cooldown", 5),
                "docker_api_timeout": docker_data.get("docker_api_timeout", 30),
                "max_log_lines": docker_data.get("max_log_lines", 50)
            }
            
            settings_file = config_dir / "docker_settings.json"
            try:
                config_service._save_json_file(settings_file, docker_settings)
                print(f"✅ Created: {settings_file}")
            except Exception as e:
                print(f"❌ Failed to create {settings_file}: {e}")
                
            print(f"✅ Migrated {len(servers)} containers + docker settings")
            
        except Exception as e:
            print(f"❌ Error reading docker_config.json: {e}")
    
    # 3. Create new config files
    print("\n🔄 CREATING NEW CONFIG FILES...")
    
    # Load current bot_config
    bot_config_file = config_dir / "bot_config.json"
    bot_data = {}
    
    if bot_config_file.exists():
        try:
            with open(bot_config_file, 'r', encoding='utf-8') as f:
                bot_data = json.load(f)
        except Exception as e:
            print(f"❌ Could not read bot_config.json: {e}")
    
    # Create config.json (main system config)
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
    
    try:
        config_service._save_json_file(config_dir / "config.json", main_config)
        print("✅ Created: config.json")
    except Exception as e:
        print(f"❌ Failed to create config.json: {e}")
    
    # Create heartbeat.json
    heartbeat_config = {
        "heartbeat_channel_id": bot_data.get("heartbeat_channel_id"),
        "enabled": bot_data.get("heartbeat_channel_id") is not None,
        "interval_minutes": 30,
        "message_template": "🤖 DDC Heartbeat - All systems operational"
    }
    
    try:
        config_service._save_json_file(config_dir / "heartbeat.json", heartbeat_config)
        print("✅ Created: heartbeat.json")
    except Exception as e:
        print(f"❌ Failed to create heartbeat.json: {e}")
    
    # Create auth.json
    auth_config = {
        "bot_token": bot_data.get("bot_token"),
        "encryption_enabled": True
    }
    
    try:
        config_service._save_json_file(config_dir / "auth.json", auth_config)
        print("✅ Created: auth.json")
    except Exception as e:
        print(f"❌ Failed to create auth.json: {e}")
    
    # Extract and create advanced_settings.json
    web_config_file = config_dir / "web_config.json"
    advanced_settings = {}
    
    if web_config_file.exists():
        try:
            with open(web_config_file, 'r', encoding='utf-8') as f:
                web_data = json.load(f)
                advanced_settings = web_data.get("advanced_settings", {})
        except Exception as e:
            print(f"❌ Could not read web_config.json: {e}")
    
    try:
        config_service._save_json_file(config_dir / "advanced_settings.json", advanced_settings)
        print("✅ Created: advanced_settings.json")
    except Exception as e:
        print(f"❌ Failed to create advanced_settings.json: {e}")
    
    # Create web_ui.json (clean version without advanced_settings)
    web_ui_config = {
        "web_ui_user": "admin", 
        "web_ui_password_hash": bot_data.get("web_ui_password_hash"),
        "admin_enabled": True,
        "session_timeout": 3600,
        "donation_disable_key": ""
    }
    
    try:
        config_service._save_json_file(config_dir / "web_ui.json", web_ui_config)
        print("✅ Created: web_ui.json")
    except Exception as e:
        print(f"❌ Failed to create web_ui.json: {e}")
    
    print("\n🎉 MIGRATION COMPLETED!")
    print("\nNew modular structure created:")
    print("  config/")
    print("  ├── channels/")
    print("  │   ├── 1283494245235294258.json (Status Kanal)")
    print("  │   ├── 1360187769682657293.json (Kontroll Kanal)")
    print("  │   └── default.json")
    print("  ├── containers/")
    print("  │   ├── Icarus.json")
    print("  │   ├── Icarus2.json")
    print("  │   ├── ProjectZomboid.json")
    print("  │   ├── Satisfactory.json")
    print("  │   ├── V-Rising.json")
    print("  │   └── Valheim.json")
    print("  ├── config.json (language, timezone, system logs)")
    print("  ├── heartbeat.json (heartbeat settings)")
    print("  ├── auth.json (bot token)")
    print("  ├── advanced_settings.json (DDC_* settings)")
    print("  ├── web_ui.json (web interface settings)")
    print("  ├── docker_settings.json (Docker daemon settings)")
    print("  └── system_tasks.json (bereits vorhanden als tasks.json)")
    
if __name__ == "__main__":
    migrate_to_modular_structure()