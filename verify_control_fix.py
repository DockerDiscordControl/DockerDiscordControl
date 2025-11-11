#!/usr/bin/env python3
"""Verify that the duplicate /control command issue is fixed."""

import re
import sys

def check_control_commands():
    """Check for duplicate /control command registrations."""

    with open('cogs/docker_control.py', 'r') as f:
        content = f.read()

    # Find all slash command decorators for control (excluding comments)
    pattern = r'^[^#]*@commands\.slash_command\(name="control"'
    matches = re.findall(pattern, content, re.MULTILINE)

    active_count = len(matches)

    print("=" * 60)
    print("Control Command Registration Check")
    print("=" * 60)

    if active_count == 0:
        print("❌ ERROR: No active /control commands found!")
        return False
    elif active_count == 1:
        print("✅ SUCCESS: Exactly 1 active /control command found")

        # Show which one is active
        lines = content.split('\n')
        for i, line in enumerate(lines, 1):
            if '@commands.slash_command(name="control"' in line and not line.strip().startswith('#'):
                print(f"   Line {i}: Active /control command (Admin View)")
                # Get description
                desc_match = re.search(r'description=_\("([^"]+)"\)', line)
                if desc_match:
                    print(f"   Description: '{desc_match.group(1)}'")

        # Show commented ones
        for i, line in enumerate(lines, 1):
            if '# @commands.slash_command(name="control"' in line:
                print(f"   Line {i}: Commented out (old single-message version)")

        return True
    else:
        print(f"❌ ERROR: Found {active_count} active /control commands!")
        print("   This will cause 'Application command names must be unique' error")
        return False

def check_private_messages():
    """Verify private message functionality is not affected."""

    print("\n" + "=" * 60)
    print("Private Message Functionality Check")
    print("=" * 60)

    with open('cogs/control_ui.py', 'r') as f:
        content = f.read()

    # Check for MechDetailsButton which handles private messages
    if 'class MechDetailsButton' in content:
        print("✅ MechDetailsButton class found (handles private messages)")
    else:
        print("⚠️  WARNING: MechDetailsButton class not found")
        return False

    # Check for private message callback
    if 'sending private status message' in content or 'ephemeral=True' in content:
        print("✅ Private message functionality appears intact")
        return True
    else:
        print("⚠️  WARNING: Private message functionality may be affected")
        return False

if __name__ == "__main__":
    print("\n🔍 Verifying /control Command Fix\n")

    control_ok = check_control_commands()
    private_ok = check_private_messages()

    print("\n" + "=" * 60)
    print("FINAL RESULT")
    print("=" * 60)

    if control_ok and private_ok:
        print("✅ All checks passed! The fix is successful.")
        print("\nNext steps:")
        print("1. Restart the Discord bot to apply changes")
        print("2. The Admin View /control command will be available")
        print("3. Private messages for container control remain functional")
        sys.exit(0)
    else:
        print("❌ Some checks failed. Please review the issues above.")
        sys.exit(1)