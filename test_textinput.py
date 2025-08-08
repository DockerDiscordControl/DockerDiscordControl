#!/usr/bin/env python3
"""
Simple test script to verify Discord TextInput import compatibility
"""

def test_textinput_import():
    """Test different TextInput import patterns"""
    
    print("Testing Discord TextInput import patterns...")
    
    try:
        import discord
        print(f"Discord version: {discord.__version__}")
        print(f"Discord module location: {discord.__file__}")
    except ImportError as e:
        print(f"Could not import discord: {e}")
        return False
    
    # Test pattern 1: Direct import from discord.ui
    try:
        from discord.ui import TextInput
        from discord import TextStyle
        print("✅ SUCCESS: Imported TextInput and TextStyle from discord.ui and discord")
        return True
    except ImportError as e:
        print(f"❌ FAILED: Direct import failed: {e}")
    
    # Test pattern 2: Access through discord module
    try:
        TextInput = discord.ui.TextInput
        TextStyle = discord.TextStyle
        print("✅ SUCCESS: Accessed TextInput and TextStyle through discord module")
        return True
    except AttributeError as e:
        print(f"❌ FAILED: Module access failed: {e}")
    
    # Check what's available in discord.ui
    try:
        ui_attrs = dir(discord.ui)
        print(f"Available in discord.ui: {[attr for attr in ui_attrs if 'Text' in attr]}")
    except:
        pass
    
    # Check what's available in discord
    try:
        discord_attrs = dir(discord)
        print(f"Available in discord: {[attr for attr in discord_attrs if 'Text' in attr]}")
    except:
        pass
        
    print("❌ FAILED: No working TextInput import pattern found")
    return False

if __name__ == "__main__":
    test_textinput_import()