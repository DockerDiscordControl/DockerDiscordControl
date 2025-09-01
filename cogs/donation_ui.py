# -*- coding: utf-8 -*-
"""
Donation UI Components - Discord Views and Modals for donation system
Extracted from docker_control.py (lines 79-510) for better organization
"""

import discord
import asyncio
import logging
import re
from typing import Optional
from utils.logging_utils import setup_logger
from .translation_manager import _

logger = setup_logger('ddc.donation_ui', level=logging.INFO)

class DonationView(discord.ui.View):
    """View with donation buttons that track clicks."""
    
    def __init__(self, donation_manager_available: bool, message=None):
        super().__init__(timeout=890)  # 14.8 minutes (just under Discord's 15-minute limit)
        self.donation_manager_available = donation_manager_available
        self.message = message  # Store reference to the message for auto-delete
        self.auto_delete_task = None
        logger.info(f"DonationView initialized with donation_manager_available: {donation_manager_available}, timeout: 890s")
        
        # Add Buy Me a Coffee button (direct link)
        coffee_button = discord.ui.Button(
            label=_("☕ Buy Me a Coffee"),
            style=discord.ButtonStyle.link,
            url="https://buymeacoffee.com/dockerdiscordcontrol"
        )
        self.add_item(coffee_button)
        
        # Add PayPal button (direct link)
        paypal_button = discord.ui.Button(
            label=_("💳 PayPal"),
            style=discord.ButtonStyle.link,
            url="https://www.paypal.com/donate/?hosted_button_id=XKVC6SFXU2GW4"
        )
        self.add_item(paypal_button)
        
        # Add Broadcast Donation button
        broadcast_button = discord.ui.Button(
            label=_("📢 Broadcast Donation"),
            style=discord.ButtonStyle.success,
            custom_id="donation_broadcast"
        )
        broadcast_button.callback = self.broadcast_clicked
        self.add_item(broadcast_button)

    async def on_timeout(self):
        """Called when the view times out."""
        try:
            # Cancel auto-delete task if it exists
            if self.auto_delete_task and not self.auto_delete_task.done():
                self.auto_delete_task.cancel()
            
            # Delete the message when timeout occurs
            if self.message:
                logger.info("DonationView timeout reached, deleting message to prevent inactive buttons")
                try:
                    await self.message.delete()
                except discord.NotFound:
                    logger.debug("Message already deleted")
                except Exception as e:
                    logger.error(f"Error deleting donation message on timeout: {e}")
        except Exception as e:
            logger.error(f"Error in DonationView.on_timeout: {e}")
    
    async def start_auto_delete_timer(self):
        """Start the auto-delete timer that runs shortly before timeout."""
        try:
            # Wait for 885 seconds (14.75 minutes), then delete message
            # This gives us a 5-second buffer before Discord's timeout
            await asyncio.sleep(885)
            if self.message:
                logger.info("Auto-deleting donation message before Discord timeout")
                try:
                    await self.message.delete()
                except discord.NotFound:
                    logger.debug("Message already deleted")
                except Exception as e:
                    logger.error(f"Error auto-deleting donation message: {e}")
        except asyncio.CancelledError:
            logger.debug("Auto-delete timer cancelled")
        except Exception as e:
            logger.error(f"Error in auto-delete timer: {e}")
    
    async def broadcast_clicked(self, interaction: discord.Interaction):
        """Handle Broadcast Donation button click."""
        try:
            # Show modal for donation details
            modal = DonationBroadcastModal(self.donation_manager_available, interaction.user.name)
            await interaction.response.send_modal(modal)
        except Exception as e:
            logger.error(f"Error in broadcast_clicked: {e}")


class DonationBroadcastModal(discord.ui.Modal):
    """Modal for donation broadcast details."""

    def __init__(self, donation_manager_available: bool, default_name: str):
        super().__init__(title=_("📢 Broadcast Your Donation"))
        self.donation_manager_available = donation_manager_available
        
        # Name field (pre-filled with Discord username)
        self.name_input = discord.ui.InputText(
            label=_("Your Name") + " *",
            placeholder=_("How should we display your name?"),
            value=default_name,
            style=discord.InputTextStyle.short,
            required=True,
            max_length=50
        )
        self.add_item(self.name_input)
        
        # Amount field (optional)
        self.amount_input = discord.ui.InputText(
            label=_("💰 Donation Amount (optional)"),
            placeholder=_("10.50 (numbers only, $ will be added automatically)"),
            style=discord.InputTextStyle.short,
            required=False,
            max_length=10
        )
        self.add_item(self.amount_input)
        
        # Public sharing field
        self.share_input = discord.ui.InputText(
            label=_("📢 Share donation publicly?"),
            placeholder=_("Remove X to keep private"),
            value="X",  # Default to sharing
            style=discord.InputTextStyle.short,
            required=False,
            max_length=10
        )
        self.add_item(self.share_input)

    async def callback(self, interaction: discord.Interaction):
        """Handle modal submission."""
        logger.info(f"=== DONATION MODAL CALLBACK STARTED ===")
        logger.info(f"User: {interaction.user.name}, Raw inputs: name={self.name_input.value}, amount={self.amount_input.value}")
        
        # Send immediate acknowledgment to avoid timeout
        await interaction.response.send_message(
            _("⏳ Processing your donation... Please wait a moment."),
            ephemeral=True
        )
        
        try:
            # Get values from modal
            donor_name = self.name_input.value or interaction.user.name
            raw_amount = self.amount_input.value.strip() if self.amount_input.value else ""
            logger.info(f"Processed values: donor_name={donor_name}, raw_amount={raw_amount}")
            
            # Check sharing preference
            share_preference = self.share_input.value.strip() if self.share_input.value else ""
            should_share_publicly = "X" in share_preference.upper() or "x" in share_preference
            
            # Validate and format amount
            amount = ""
            amount_validation_error = None
            if raw_amount:
                if '-' in raw_amount:
                    amount_validation_error = f"⚠️ Invalid amount: '{raw_amount}' - negative amounts not allowed"
                else:
                    cleaned_amount = re.sub(r'[^\d.,]', '', raw_amount)
                    cleaned_amount = cleaned_amount.replace(',', '.')
                    
                    try:
                        numeric_value = float(cleaned_amount)
                        if numeric_value > 0:
                            amount = f"${numeric_value:.2f}"
                        elif numeric_value == 0:
                            amount_validation_error = f"⚠️ Invalid amount: '{raw_amount}' - must be greater than 0"
                        else:
                            amount_validation_error = f"⚠️ Invalid amount: '{raw_amount}' - please use only numbers"
                    except ValueError:
                        amount_validation_error = f"⚠️ Invalid amount: '{raw_amount}' - please use only numbers (e.g. 10.50)"
            
            if amount_validation_error:
                await interaction.followup.send(
                    amount_validation_error + _("\n\nTip: Use format like: 10.50 or 5 ($ will be added automatically)"),
                    ephemeral=True
                )
                return
            
            # Process donation through mech service
            donation_amount_euros = None
            evolution_occurred = False
            old_evolution_level = None
            new_evolution_level = None
            
            if self.donation_manager_available:
                try:
                    from services.mech.mech_service import get_mech_service
                    mech_service = get_mech_service()
                    
                    # Get old state before donation
                    old_state = mech_service.get_state()
                    old_evolution_level = old_state.level
                    
                    # Parse amount if provided
                    if amount:
                        amount_match = re.search(r'(\d+(?:\.\d+)?)', amount)
                        if amount_match:
                            donation_amount_euros = float(amount_match.group(1))
                    
                    # Record donation if amount > 0
                    if donation_amount_euros and donation_amount_euros > 0:
                        amount_dollars = int(donation_amount_euros)
                        new_state = mech_service.add_donation(
                            username=f"Discord:{interaction.user.name}",
                            amount=amount_dollars
                        )
                        logger.info(f"Donation recorded: ${amount_dollars}")
                    else:
                        new_state = mech_service.get_state()
                    
                    # Check if evolution occurred
                    evolution_occurred = new_state.level > old_state.level
                    new_evolution_level = new_state.level
                    
                    if evolution_occurred:
                        logger.info(f"EVOLUTION! Level {old_evolution_level} → {new_evolution_level}")
                        
                except Exception as e:
                    logger.error(f"Error processing donation: {e}")
                    evolution_occurred = False
            
            # Create broadcast message
            if amount:
                broadcast_text = _("{donor_name} donated {amount} to DDC – thank you so much ❤️").format(
                    donor_name=f"**{donor_name}**",
                    amount=f"**{amount}**"
                )
            else:
                broadcast_text = _("{donor_name} supports DDC – thank you so much ❤️").format(
                    donor_name=f"**{donor_name}**"
                )
            
            # Create evolution status
            evolution_status = ""
            if evolution_occurred:
                evolution_status = _("**Evolution: Level {old} → {new}!**").format(
                    old=old_evolution_level, 
                    new=new_evolution_level
                )
            
            # Send to channels if sharing publicly
            sent_count = 0
            failed_count = 0
            
            if should_share_publicly:
                from utils.config_cache import get_cached_config
                config = get_cached_config()
                channels_config = config.get('channel_permissions', {})
                
                for channel_id_str, channel_info in channels_config.items():
                    try:
                        channel_id = int(channel_id_str)
                        channel = interaction.client.get_channel(channel_id)
                        
                        if channel:
                            embed = discord.Embed(
                                title=_("💝 Donation received"),
                                description=broadcast_text,
                                color=0x00ff41
                            )
                            
                            if evolution_status:
                                embed.add_field(name=_("Mech Status"), value=evolution_status, inline=False)
                            
                            embed.set_footer(text="https://ddc.bot")
                            await channel.send(embed=embed)
                            sent_count += 1
                        else:
                            failed_count += 1
                            
                    except Exception as channel_error:
                        failed_count += 1
                        logger.error(f"Error sending to channel {channel_id_str}: {channel_error}")
            
            # Respond to user
            if should_share_publicly:
                response_text = _("✅ **Donation broadcast sent!**") + "\n\n"
                response_text += _("📢 Sent to **{count}** channels").format(count=sent_count) + "\n"
                if failed_count > 0:
                    response_text += _("⚠️ Failed to send to {count} channels").format(count=failed_count) + "\n"
                response_text += "\n" + _("Thank you **{donor_name}** for your generosity! 🙏").format(donor_name=donor_name)
            else:
                response_text = _("✅ **Donation recorded privately!**") + "\n\n"
                response_text += _("Thank you **{donor_name}** for your generous support! 🙏").format(donor_name=donor_name) + "\n"
                response_text += _("Your donation has been recorded and helps fuel the Donation Engine.")
            
            # Use followup for final response
            await interaction.followup.send(response_text, ephemeral=True)
            
            # Clean up processing message
            try:
                await interaction.delete_original_response()
            except:
                pass  # Ignore if already deleted or expired
            
        except Exception as e:
            logger.error(f"Error in donation broadcast modal: {e}")
            try:
                await interaction.followup.send(
                    _("❌ Error sending donation broadcast. Please try again later."),
                    ephemeral=True
                )
            except Exception as followup_error:
                logger.error(f"Could not send error response: {followup_error}")