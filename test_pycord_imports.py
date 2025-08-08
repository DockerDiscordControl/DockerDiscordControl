#!/usr/bin/env python3
"""Test py-cord import structure"""

print("Testing py-cord imports...")

try:
    import discord
    print(f"✅ discord module imported, version: {discord.__version__}")
except Exception as e:
    print(f"❌ Failed to import discord: {e}")

try:
    from discord.ui import Modal
    print("✅ Modal imported from discord.ui")
except Exception as e:
    print(f"❌ Failed to import Modal: {e}")

try:
    from discord import InputTextStyle
    print("✅ InputTextStyle imported from discord")
except Exception as e:
    print(f"❌ Failed to import InputTextStyle: {e}")

try:
    import discord.ui
    print("✅ discord.ui module exists")
    print(f"   Available: {[x for x in dir(discord.ui) if not x.startswith('_')]}")
except Exception as e:
    print(f"❌ Failed to access discord.ui: {e}")

try:
    # Test creating InputText
    test_input = discord.ui.InputText(
        label="Test",
        style=InputTextStyle.short
    )
    print("✅ InputText created successfully")
except Exception as e:
    print(f"❌ Failed to create InputText: {e}")