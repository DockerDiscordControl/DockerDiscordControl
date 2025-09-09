#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Web-based migration script that runs inside the web application context.
This should have the correct permissions to create directories and files.
"""

import sys
import os
sys.path.insert(0, '.')

import json
from pathlib import Path

def migrate_with_web_permissions():
    """Run migration with web application permissions."""
    print("🚀 RUNNING MIGRATION WITH WEB PERMISSIONS")
    print("=" * 50)
    
    config_dir = Path("./config")
    
    # Test if we can create directories
    try:
        channels_dir = config_dir / "channels"
        containers_dir = config_dir / "containers"
        
        print(f"📁 Creating directories...")
        channels_dir.mkdir(exist_ok=True)
        containers_dir.mkdir(exist_ok=True)
        print(f"✅ Created: {channels_dir}")
        print(f"✅ Created: {containers_dir}")
        
    except Exception as e:
        print(f"❌ Could not create directories: {e}")
        return False
    
    # Migrate channels_config.json
    print(f"\n🔄 MIGRATING CHANNELS...")
    channels_file = config_dir / "channels_config.json"
    
    if channels_file.exists():
        try:
            with open(channels_file, 'r', encoding='utf-8') as f:
                channels_data = json.load(f)
            
            channel_permissions = channels_data.get("channel_permissions", {})
            
            for channel_id, channel_config in channel_permissions.items():
                channel_file = channels_dir / f"{channel_id}.json"
                channel_config["channel_id"] = channel_id
                
                with open(channel_file, 'w', encoding='utf-8') as f:
                    json.dump(channel_config, f, indent=2, ensure_ascii=False)
                print(f"✅ Migrated: {channel_config.get('name', channel_id)}")
            
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
            with open(default_file, 'w', encoding='utf-8') as f:
                json.dump(default_config, f, indent=2, ensure_ascii=False)
            
            print(f"✅ Migrated {len(channel_permissions)} channels + default config")
            
        except Exception as e:
            print(f"❌ Error migrating channels: {e}")
            return False
    
    # Migrate docker_config.json
    print(f"\n🔄 MIGRATING CONTAINERS...")
    docker_file = config_dir / "docker_config.json"
    
    if docker_file.exists():
        try:
            with open(docker_file, 'r', encoding='utf-8') as f:
                docker_data = json.load(f)
            
            servers = docker_data.get("servers", [])
            
            for server in servers:
                container_name = server.get("docker_name", server.get("name", "unknown"))
                container_file = containers_dir / f"{container_name}.json"
                
                with open(container_file, 'w', encoding='utf-8') as f:
                    json.dump(server, f, indent=2, ensure_ascii=False)
                print(f"✅ Migrated: {container_name}")
            
            # Create docker_settings.json
            docker_settings = {
                "docker_socket_path": docker_data.get("docker_socket_path", "/var/run/docker.sock"),
                "container_command_cooldown": docker_data.get("container_command_cooldown", 5),
                "docker_api_timeout": docker_data.get("docker_api_timeout", 30),
                "max_log_lines": docker_data.get("max_log_lines", 50)
            }
            
            settings_file = config_dir / "docker_settings.json"
            with open(settings_file, 'w', encoding='utf-8') as f:
                json.dump(docker_settings, f, indent=2, ensure_ascii=False)
            
            print(f"✅ Migrated {len(servers)} containers + docker settings")
            
        except Exception as e:
            print(f"❌ Error migrating containers: {e}")
            return False
    
    # Migrate bot_config.json to system configs
    print(f"\n🔄 MIGRATING SYSTEM CONFIGS...")
    bot_config_file = config_dir / "bot_config.json"
    
    if bot_config_file.exists():
        try:
            with open(bot_config_file, 'r', encoding='utf-8') as f:
                bot_data = json.load(f)
            
            # Create config.json
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
            
            with open(config_dir / "config.json", 'w', encoding='utf-8') as f:
                json.dump(main_config, f, indent=2, ensure_ascii=False)
            print("✅ Created: config.json")
            
            # Create heartbeat.json
            heartbeat_config = {
                "heartbeat_channel_id": bot_data.get("heartbeat_channel_id"),
                "enabled": bot_data.get("heartbeat_channel_id") is not None,
                "interval_minutes": 30,
                "message_template": "🤖 DDC Heartbeat - All systems operational"
            }
            
            with open(config_dir / "heartbeat.json", 'w', encoding='utf-8') as f:
                json.dump(heartbeat_config, f, indent=2, ensure_ascii=False)
            print("✅ Created: heartbeat.json")
            
            # Create auth.json
            auth_config = {
                "bot_token": bot_data.get("bot_token"),
                "encryption_enabled": True
            }
            
            with open(config_dir / "auth.json", 'w', encoding='utf-8') as f:
                json.dump(auth_config, f, indent=2, ensure_ascii=False)
            print("✅ Created: auth.json")
            
        except Exception as e:
            print(f"❌ Error migrating system configs: {e}")
            return False
    
    # Migrate web_config.json
    print(f"\n🔄 MIGRATING WEB CONFIGS...")
    web_config_file = config_dir / "web_config.json"
    
    if web_config_file.exists():
        try:
            with open(web_config_file, 'r', encoding='utf-8') as f:
                web_data = json.load(f)
            
            # Create advanced_settings.json
            advanced_settings = web_data.get("advanced_settings", {})
            with open(config_dir / "advanced_settings.json", 'w', encoding='utf-8') as f:
                json.dump(advanced_settings, f, indent=2, ensure_ascii=False)
            print("✅ Created: advanced_settings.json")
            
            # Create web_ui.json
            web_ui_config = {
                "web_ui_user": web_data.get("web_ui_user", "admin"),
                "web_ui_password_hash": web_data.get("web_ui_password_hash"),
                "admin_enabled": web_data.get("admin_enabled", True),
                "session_timeout": web_data.get("session_timeout", 3600),
                "donation_disable_key": web_data.get("donation_disable_key", ""),
                "scheduler_debug_mode": web_data.get("scheduler_debug_mode", False)
            }
            
            with open(config_dir / "web_ui.json", 'w', encoding='utf-8') as f:
                json.dump(web_ui_config, f, indent=2, ensure_ascii=False)
            print("✅ Created: web_ui.json")
            
        except Exception as e:
            print(f"❌ Error migrating web configs: {e}")
            return False
    
    print("\n🎉 MIGRATION COMPLETED SUCCESSFULLY!")
    print("\nNew modular structure:")
    
    # List created files
    if channels_dir.exists():
        channel_files = list(channels_dir.glob("*.json"))
        print(f"📁 channels/ ({len(channel_files)} files)")
        for f in channel_files:
            print(f"   - {f.name}")
    
    if containers_dir.exists():
        container_files = list(containers_dir.glob("*.json"))
        print(f"📁 containers/ ({len(container_files)} files)")
        for f in container_files:
            print(f"   - {f.name}")
    
    new_config_files = ["config.json", "heartbeat.json", "auth.json", "advanced_settings.json", "web_ui.json", "docker_settings.json"]
    print(f"📄 New config files:")
    for filename in new_config_files:
        if (config_dir / filename).exists():
            print(f"   - {filename} ✅")
        else:
            print(f"   - {filename} ❌")
    
    return True

if __name__ == "__main__":
    success = migrate_with_web_permissions()
    if success:
        print(f"\n✅ Ready to test new modular config system!")
    else:
        print(f"\n❌ Migration failed - check errors above")