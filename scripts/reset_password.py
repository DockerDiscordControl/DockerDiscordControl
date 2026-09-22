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
Run it inside the container as the ddc user (so no root-owned files are created):

    docker exec -it -u ddc dockerdiscordcontrol python3 scripts/reset_password.py

Environment:
    DDC_ADMIN_PASSWORD - Set new password (optional, will prompt if not set)
"""

import os
import sys
import getpass
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

def reset_password():
    """Reset the Web UI admin password."""
    print("🔐 DockerDiscordControl Password Reset Utility")
    print("=" * 50)

    try:
        # change_web_ui_password() validates and hashes the password and re-encrypts
        # the stored bot token with the new key, so the token stays decryptable.
        from services.config.config_service import change_web_ui_password
        from services.exceptions import ConfigServiceError
    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("Make sure you're running this from the DDC project directory.")
        return False

    # Get new password
    new_password = os.environ.get('DDC_ADMIN_PASSWORD')
    if not new_password:
        print("\n💡 No DDC_ADMIN_PASSWORD environment variable found.")
        print("Please enter the new admin password:")
        new_password = getpass.getpass("New password: ")

        # Confirm password
        confirm_password = getpass.getpass("Confirm password: ")
        if new_password != confirm_password:
            print("❌ Passwords do not match!")
            return False

    try:
        print("\n🔒 Setting new password (hash + bot token re-encryption)...")
        change_web_ui_password(new_password)
    except ValueError as e:
        # Password validation failed - the message is meant for the user
        print(f"❌ {e}")
        return False
    except (ConfigServiceError, OSError, RuntimeError) as e:
        print(f"❌ Failed to save configuration: {e}")
        return False

    print("✅ Password reset successful!")
    print("\nLogin credentials:")
    print("  Username: admin")
    print("  Password: [your new password]")
    print("\n🚀 You can now access the Web UI with your new password.")
    return True

def show_help():
    """Show help information."""
    print("""
🔐 DockerDiscordControl Password Reset Utility

Usage Options:

1. Interactive Mode (recommended):
   python3 scripts/reset_password.py

2. Environment Variable Mode:
   DDC_ADMIN_PASSWORD=your_new_password python3 scripts/reset_password.py

3. Docker Container Mode (always run as the ddc user):
   docker exec -it -u ddc dockerdiscordcontrol python3 scripts/reset_password.py

4. Docker with Environment Variable:
   docker exec -u ddc -e DDC_ADMIN_PASSWORD=your_password dockerdiscordcontrol python3 scripts/reset_password.py

Security Notes:
- Passwords are stored as salted hashes, never in plaintext
- The stored bot token is re-encrypted with the new password
- Always use strong passwords (at least 12 characters recommended)

Troubleshooting:
- If you get permission errors, make sure you run the command with "-u ddc"
- If the script fails, check the Docker container logs for details
- For persistent issues, delete the config files and restart with DDC_ADMIN_PASSWORD
""")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ['--help', '-h', 'help']:
        show_help()
        sys.exit(0)

    success = reset_password()
    sys.exit(0 if success else 1)
