#!/usr/bin/env python3
"""
Debug script to check container_info directory permissions
"""

import os
import sys
from pathlib import Path

def check_permissions():
    # Get the config directory path
    config_dir = Path("config/container_info")
    
    print(f"Checking permissions for: {config_dir.absolute()}")
    print("-" * 50)
    
    # Create directory if it doesn't exist
    config_dir.mkdir(parents=True, exist_ok=True)
    
    # Check if directory exists
    print(f"Directory exists: {config_dir.exists()}")
    
    # Check permissions
    print(f"Directory readable: {os.access(config_dir, os.R_OK)}")
    print(f"Directory writable: {os.access(config_dir, os.W_OK)}")
    print(f"Directory executable: {os.access(config_dir, os.X_OK)}")
    
    # Try to create a test file
    test_file = config_dir / "test_write.json"
    try:
        with open(test_file, 'w') as f:
            f.write('{"test": true}')
        print(f"Test file creation: SUCCESS")
        
        # Clean up test file
        test_file.unlink()
        print(f"Test file cleanup: SUCCESS")
        
    except Exception as e:
        print(f"Test file creation: FAILED - {e}")
    
    # Check ownership (if on Unix-like system)
    if hasattr(os, 'getuid'):
        import stat
        try:
            stat_info = config_dir.stat()
            print(f"Directory owner UID: {stat_info.st_uid}")
            print(f"Directory group GID: {stat_info.st_gid}")
            print(f"Current process UID: {os.getuid()}")
            print(f"Current process GID: {os.getgid()}")
            print(f"Directory permissions: {oct(stat_info.st_mode)}")
        except Exception as e:
            print(f"Could not get ownership info: {e}")

if __name__ == "__main__":
    check_permissions()