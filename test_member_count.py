#!/usr/bin/env python3
"""Test member count functionality."""

import asyncio
import discord
from discord.ext import commands
import os
import json
from pathlib import Path

print("=" * 80)
print("MEMBER COUNT TEST")
print("=" * 80)
print()

# Check current snapshot
snap_file = Path("config/progress/snapshots/main.json")
if snap_file.exists():
    snap = json.loads(snap_file.read_text())
    print(f"Current Snapshot Member Count: {snap.get('last_user_count_sample', 'N/A')}")
    print()

# Discord API test
TOKEN = os.getenv('DISCORD_BOT_TOKEN')
if not TOKEN:
    print("❌ DISCORD_BOT_TOKEN not set in environment")
    print("Cannot test live member count without bot token")
    exit(1)

print("Testing Discord API member count...")
print()

# Create a simple bot to test member count
intents = discord.Intents.default()
# NOTE: We specifically DO NOT enable members intent to test that member_count works without it
intents.members = False  # This is the key test!

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"✅ Bot connected as {bot.user}")
    print()

    # Get all guilds
    for guild in bot.guilds:
        print(f"Guild: {guild.name} (ID: {guild.id})")
        print(f"  Member Count (guild.member_count): {guild.member_count}")
        print(f"  Cached Members (len(guild.members)): {len(guild.members)}")
        print()

        print(f"Analysis:")
        print(f"  - guild.member_count: Total server members (online + offline + bots)")
        print(f"  - This value works WITHOUT members intent ✅")
        print(f"  - Includes all members regardless of online status")
        print()

        print(f"  - guild.members: Only cached members (requires members intent)")
        print(f"  - With members intent OFF: Only shows {len(guild.members)} cached members")
        print(f"  - This is why we use guild.member_count instead!")
        print()

    # Close bot after testing
    await bot.close()

# Run bot
try:
    asyncio.run(bot.start(TOKEN))
except KeyboardInterrupt:
    print("Bot stopped")
