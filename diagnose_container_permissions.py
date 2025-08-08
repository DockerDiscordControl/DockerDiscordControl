#!/usr/bin/env python3
"""
Container permissions diagnostics - Run this inside the Docker container
"""

import os
import sys
import json
from pathlib import Path
import pwd
import grp
import stat

def diagnose_permissions():
    print("🔍 Container Permissions Diagnosis")
    print("=" * 60)
    
    # Current user info
    try:
        current_uid = os.getuid()
        current_gid = os.getgid()
        user_info = pwd.getpwuid(current_uid)
        group_info = grp.getgrgid(current_gid)
        
        print(f"Current User: {user_info.pw_name} (UID: {current_uid})")
        print(f"Current Group: {group_info.gr_name} (GID: {current_gid})")
        print(f"Home Directory: {user_info.pw_dir}")
        print(f"Shell: {user_info.pw_shell}")
    except Exception as e:
        print(f"❌ Error getting user info: {e}")
    
    print("-" * 60)
    
    # Check directories
    directories_to_check = [
        "/app",
        "/app/config",
        "/app/config/container_info",
        "/app/logs"
    ]
    
    for dir_path in directories_to_check:
        path = Path(dir_path)
        print(f"\n📁 Directory: {dir_path}")
        
        if path.exists():
            try:
                stat_info = path.stat()
                owner_name = pwd.getpwuid(stat_info.st_uid).pw_name
                group_name = grp.getgrgid(stat_info.st_gid).gr_name
                
                print(f"  ✅ Exists: Yes")
                print(f"  👤 Owner: {owner_name} (UID: {stat_info.st_uid})")
                print(f"  👥 Group: {group_name} (GID: {stat_info.st_gid})")
                print(f"  🔐 Permissions: {oct(stat_info.st_mode)}")
                print(f"  📖 Readable: {os.access(path, os.R_OK)}")
                print(f"  ✏️  Writable: {os.access(path, os.W_OK)}")
                print(f"  🚀 Executable: {os.access(path, os.X_OK)}")
                
                # Try to create a test file if writable
                if os.access(path, os.W_OK):
                    test_file = path / "test_permissions.tmp"
                    try:
                        with open(test_file, 'w') as f:
                            f.write("test")
                        test_file.unlink()
                        print(f"  ✅ Write Test: SUCCESS")
                    except Exception as e:
                        print(f"  ❌ Write Test: FAILED - {e}")
                
            except Exception as e:
                print(f"  ❌ Error checking {dir_path}: {e}")
        else:
            print(f"  ❌ Exists: No")
            # Try to create it
            try:
                path.mkdir(parents=True, exist_ok=True)
                print(f"  ✅ Created successfully")
            except Exception as e:
                print(f"  ❌ Creation failed: {e}")
    
    print("\n" + "=" * 60)
    
    # Test container info manager
    print("\n🧪 Testing Container Info Manager")
    try:
        sys.path.insert(0, '/app')
        from utils.container_info_manager import get_container_info_manager
        
        manager = get_container_info_manager()
        print(f"✅ Manager created successfully")
        print(f"📁 Config directory: {manager.config_dir}")
        print(f"📁 Config dir exists: {manager.config_dir.exists()}")
        
        # Test save/load
        test_data = {
            'enabled': True,
            'show_ip': False,
            'custom_ip': 'test.example.com:8080',
            'custom_text': 'This is a test'
        }
        
        success = manager.save_container_info('test_container', test_data)
        print(f"💾 Save test: {'SUCCESS' if success else 'FAILED'}")
        
        if success:
            loaded_data = manager.load_container_info('test_container')
            print(f"📖 Load test: {'SUCCESS' if loaded_data else 'FAILED'}")
            print(f"📋 Loaded data: {loaded_data}")
            
            # Clean up test file
            test_file = manager._get_info_file_path('test_container')
            if test_file.exists():
                test_file.unlink()
                print(f"🧹 Cleanup: SUCCESS")
        
    except Exception as e:
        print(f"❌ Container Info Manager test failed: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 60)
    print("🎯 Diagnosis complete!")

if __name__ == "__main__":
    diagnose_permissions()