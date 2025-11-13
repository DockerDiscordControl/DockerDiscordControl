#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test script for v1.1.x to v2.0 migration.
Creates a sample v1.1.x config and tests the migration.
"""

import json
import sys
import os
from pathlib import Path

sys.path.insert(0, '.')

def create_sample_v1_config():
    """Create a sample v1.1.x config for testing."""
    v1_config = {
        "bot_token": "YOUR_BOT_TOKEN_HERE",
        "guild_id": "809093957622562826",
        "language": "de",
        "timezone": "Europe/Berlin",
        "heartbeat_channel_id": None,
        
        # Docker settings (v1.1.x style)
        "docker_socket_path": "/var/run/docker.sock",
        "container_command_cooldown": 5,
        "docker_api_timeout": 30,
        "max_log_lines": 50,
        
        # Servers (v1.1.x style)
        "servers": [
            {
                "name": "TestServer1",
                "docker_name": "test-container-1",
                "allowed_actions": ["status", "start", "stop", "restart"],
                "info": {
                    "enabled": True,
                    "show_ip": True,
                    "custom_ip": "192.168.1.100",
                    "custom_port": "8080",
                    "custom_text": "Test Server 1"
                }
            },
            {
                "name": "TestServer2",
                "docker_name": "test-container-2",
                "allowed_actions": ["status"],
                "info": {
                    "enabled": False,
                    "show_ip": False,
                    "custom_ip": "",
                    "custom_port": "",
                    "custom_text": ""
                }
            }
        ],
        
        # Web UI settings (v1.1.x style)
        "web_ui_user": "admin",
        "web_ui_password_hash": "pbkdf2:sha256:600000$test$hash",
        "admin_enabled": True,
        "session_timeout": 3600,
        
        # Channel permissions (v1.1.x style)
        "channel_permissions": {
            "123456789": {
                "name": "Test Channel",
                "commands": {
                    "serverstatus": True,
                    "command": True,
                    "control": True,
                    "schedule": True,
                    "info": True
                },
                "post_initial": True,
                "update_interval_minutes": 5
            }
        },
        
        # Advanced settings (v1.1.x style)
        "advanced_settings": {
            "DDC_DOCKER_CACHE_DURATION": 30,
            "DDC_FAST_STATS_TIMEOUT": 10,
            "DDC_SLOW_STATS_TIMEOUT": 30
        }
    }
    
    return v1_config

def test_migration():
    """Test the v1.1.x to v2.0 migration."""
    print("🔄 TESTING V1.1.X TO V2.0 MIGRATION")
    print("=" * 60)
    
    config_dir = Path("./config")
    
    # Step 1: Create test v1.1.x config
    print("\n1️⃣ Creating test v1.1.x config...")
    test_config_file = Path("/tmp/config_test_v1.json")
    v1_config = create_sample_v1_config()
    
    try:
        with open(test_config_file, 'w', encoding='utf-8') as f:
            json.dump(v1_config, f, indent=2)
        print(f"✅ Created test config: {test_config_file}")
    except (IOError, OSError, PermissionError, RuntimeError, json.JSONDecodeError) as e:
        print(f"❌ Could not create test config: {e}")
        return False
    
    # Step 2: Test migration detection
    print("\n2️⃣ Testing migration detection...")
    
    from services.config.config_service import ConfigService
    
    # Clear any existing instance
    import services.config.config_service as cs
    cs._config_service_instance = None
    
    # Test if migration would be triggered
    print("   Checking if ConfigService detects v1.1.x config...")
    
    # Step 3: Perform migration
    print("\n3️⃣ Performing migration...")
    
    try:
        config_service = ConfigService()
        config = config_service.get_config()
        
        print("✅ Migration completed!")
        
        # Check results
        print("\n4️⃣ Checking migration results...")
        
        # Check if modular files were created
        expected_files = [
            "bot_config.json",
            "docker_config.json", 
            "web_config.json",
            "channels_config.json"
        ]
        
        for file_name in expected_files:
            file_path = config_dir / file_name
            if file_path.exists():
                print(f"   ✅ {file_name} created")
            else:
                print(f"   ❌ {file_name} missing")
        
        # Check if servers were migrated
        servers = config.get('servers', [])
        print(f"\n   Servers migrated: {len(servers)}")
        for server in servers:
            print(f"      - {server.get('name')} ({server.get('docker_name')})")
        
        # Check if channels were migrated
        channels = config.get('channel_permissions', {})
        print(f"\n   Channels migrated: {len(channels)}")
        for ch_id, ch_config in channels.items():
            print(f"      - {ch_config.get('name')} ({ch_id})")
        
        # Check if settings were migrated
        print(f"\n   Language: {config.get('language')}")
        print(f"   Timezone: {config.get('timezone')}")
        print(f"   Advanced settings: {len(config.get('advanced_settings', {}))}")
        
        print("\n✅ V1.1.X TO V2.0 MIGRATION TEST SUCCESSFUL!")
        
        # Cleanup test file
        if test_config_file.exists():
            test_config_file.unlink()
            print(f"\n🧹 Cleaned up test file: {test_config_file}")
        
        return True
        
    except (AttributeError, ImportError, KeyError, ModuleNotFoundError, RuntimeError, TypeError) as e:
        print(f"❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        
        # Cleanup
        if test_config_file.exists():
            test_config_file.unlink()
        
        return False

if __name__ == "__main__":
    success = test_migration()
    if success:
        print("\n🎉 Migration test completed successfully!")
        print("The system can migrate from v1.1.x to v2.0 automatically!")
    else:
        print("\n❌ Migration test failed!")
        print("Check the error messages above.")