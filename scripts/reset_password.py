#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Password Reset Utility                         #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""
Password Reset Utility for DockerDiscordControl

This script allows administrators to reset the Web UI password when locked out.
Can be run directly inside the Docker container or from the host system.

Usage:
    python3 scripts/reset_password.py
    
Environment:
    DDC_ADMIN_PASSWORD - Set new password (optional, will prompt if not set)
"""

import os
import sys
import getpass
from pathlib import Path
from werkzeug.security import generate_password_hash

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

def reset_password():
    """Reset the Web UI admin password."""
    print("🔐 DockerDiscordControl Password Reset Utility")
    print("=" * 50)
    
    try:
        # Import config service
        from services.config.config_service import load_config, save_config
        
        # Get new password
        new_password = os.environ.get('DDC_ADMIN_PASSWORD')
        if not new_password:
            print("\n💡 No DDC_ADMIN_PASSWORD environment variable found.")
            print("Please enter the new admin password:")
            new_password = getpass.getpass("New password: ")
            
            if not new_password or len(new_password) < 6:
                print("❌ Password must be at least 6 characters long!")
                return False
            
            # Confirm password
            confirm_password = getpass.getpass("Confirm password: ")
            if new_password != confirm_password:
                print("❌ Passwords do not match!")
                return False
        
        # Load current config
        print("\n📄 Loading configuration...")
        config = load_config()
        
        # Show current state
        current_hash = config.get('web_ui_password_hash')
        if current_hash:
            print("✅ Found existing password hash")
        else:
            print("⚠️  No password hash found (first-time setup)")
        
        # Generate new hash using strong parameters
        print("🔒 Generating secure password hash...")
        new_hash = generate_password_hash(new_password, method="pbkdf2:sha256:600000")
        
        # Update config
        config['web_ui_password_hash'] = new_hash
        
        # Ensure user is set to admin
        config['web_ui_user'] = 'admin'
        
        # Save config
        print("💾 Saving configuration...")
        success = save_config(config)
        
        if success:
            print("✅ Password reset successful!")
            print("\nLogin credentials:")
            print(f"  Username: admin")
            print(f"  Password: [your new password]")
            print("\n🚀 You can now access the Web UI with your new password.")
            return True
        else:
            print("❌ Failed to save configuration!")
            return False
            
    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("Make sure you're running this from the DDC project directory.")
        return False
    except (AttributeError, ImportError, KeyError, ModuleNotFoundError, RuntimeError, TypeError) as e:
        print(f"❌ Error: {e}")
        return False

def show_help():
    """Show help information."""
    print("""
🔐 DockerDiscordControl Password Reset Utility

Usage Options:

1. Interactive Mode (recommended):
   python3 scripts/reset_password.py
   
2. Environment Variable Mode:
   DDC_ADMIN_PASSWORD=your_new_password python3 scripts/reset_password.py
   
3. Docker Container Mode:
   docker exec -it dockerdiscordcontrol python3 scripts/reset_password.py
   
4. Docker with Environment Variable:
   docker exec -e DDC_ADMIN_PASSWORD=your_password dockerdiscordcontrol python3 scripts/reset_password.py

Security Notes:
- Passwords are hashed using PBKDF2-SHA256 with 600,000 iterations
- The script will create a new password hash if none exists
- Old sessions will be invalidated after password change
- Always use strong passwords (at least 12 characters recommended)

Troubleshooting:
- If you get permission errors, make sure you have write access to the config directory
- If the script fails, check the Docker container logs for details
- For persistent issues, delete the config files and restart with DDC_ADMIN_PASSWORD
""")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ['--help', '-h', 'help']:
        show_help()
        sys.exit(0)
    
    success = reset_password()
    sys.exit(0 if success else 1)