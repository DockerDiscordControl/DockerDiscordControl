#!/usr/bin/env python3
"""Test modal creation step by step"""

import sys
sys.path.insert(0, '/app')

print("Testing modal creation...")
print("=" * 60)

# Step 1: Import discord
try:
    import discord
    print(f"✅ Step 1: discord imported, version: {discord.__version__}")
except Exception as e:
    print(f"❌ Step 1 FAILED: {e}")
    sys.exit(1)

# Step 2: Import InputTextStyle
try:
    from discord import InputTextStyle
    print("✅ Step 2: InputTextStyle imported")
except Exception as e:
    print(f"❌ Step 2 FAILED: {e}")
    sys.exit(1)

# Step 3: Test InputText creation
try:
    test_input = discord.ui.InputText(
        label="Test",
        style=InputTextStyle.short,
        value="",
        max_length=10,
        required=False,
        placeholder="test"
    )
    print("✅ Step 3: InputText created successfully")
except Exception as e:
    print(f"❌ Step 3 FAILED: {e}")
    import traceback
    traceback.print_exc()

# Step 4: Test Modal creation
try:
    class TestModal(discord.ui.Modal):
        def __init__(self):
            super().__init__(title="Test", timeout=300)
            
            self.test_field = discord.ui.InputText(
                label="Test Field",
                style=InputTextStyle.short,
                value="",
                max_length=10,
                required=False
            )
            self.add_item(self.test_field)
        
        async def on_submit(self, interaction):
            await interaction.response.send_message("Success!", ephemeral=True)
    
    modal = TestModal()
    print("✅ Step 4: Modal created successfully")
    print(f"   Modal title: {modal.title}")
    print(f"   Modal items: {len(modal.children)}")
except Exception as e:
    print(f"❌ Step 4 FAILED: {e}")
    import traceback
    traceback.print_exc()

# Step 5: Test our actual modal
try:
    from cogs.enhanced_info_modal_simple import SimplifiedContainerInfoModal
    print("✅ Step 5: SimplifiedContainerInfoModal imported")
    
    # Mock cog instance
    class MockCog:
        pass
    
    modal = SimplifiedContainerInfoModal(MockCog(), "test_container", "Test Display")
    print("✅ Step 5b: Modal instance created")
    print(f"   Modal title: {modal.title}")
    print(f"   Modal items: {len(modal.children)}")
    
except Exception as e:
    print(f"❌ Step 5 FAILED: {e}")
    import traceback
    traceback.print_exc()

print("=" * 60)
print("Test complete!")