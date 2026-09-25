# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Donation views and the /addadmin modal of DockerControlCog.

Moved out of cogs/docker_control.py unchanged on 2026-09-22 (roadmap Phase 3,
the cog split): DonationView (the donate buttons), DonationBroadcastModal
(recording a donation and announcing it) and AddAdminModal. docker_control.py
re-exports the three names.
"""

import asyncio
import logging

import discord

from services.config.config_service import load_config
from utils.logging_utils import setup_logger

from .ddc_ui import NOTICE_STAYS_FOR, DDCModal, DDCView, CloseButton
from .translation_manager import _

# Same logger name as the cog: log lines and log-based tests read as before the move.
logger = setup_logger('ddc.docker_control', level=logging.INFO)


class DonationView(DDCView):
    """View with donation buttons that track clicks."""

    def __init__(self, donation_manager_available: bool, message=None, bot=None,
                 private: bool = False):
        super().__init__(timeout=890)  # 14.8 minutes (just under Discord's 15-minute limit)
        self.donation_manager_available = donation_manager_available
        self.message = message  # Store reference to the message for auto-delete
        self.auto_delete_task = None
        self.bot = bot  # Store bot instance for modal access
        logger.info(f"DonationView initialized with donation_manager_available: {donation_manager_available}, timeout: 890s")

        # Import translation function
        from .translation_manager import _

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

        # THE WAY OUT, BUT ONLY WHEN THIS ONE IS PRIVATE. This view goes out
        # three times: twice as an ephemeral panel, and once from /donate as a
        # public message with an auto-delete timer. A close button on the
        # public one would sit there refusing every press, because it asks the
        # message's own ephemeral flag before deleting anything - and the
        # operator's rule is that a message everybody reads carries none.
        if private:
            self.add_item(CloseButton())

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
                except (discord.errors.DiscordException, RuntimeError, OSError) as e:
                    logger.error(f"Error deleting donation message on timeout: {e}", exc_info=True)
        except (discord.errors.DiscordException, RuntimeError, ValueError) as e:
            logger.error(f"Error in DonationView.on_timeout: {e}", exc_info=True)

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
                except (discord.errors.DiscordException, RuntimeError, OSError) as e:
                    logger.error(f"Error auto-deleting donation message: {e}", exc_info=True)
        except asyncio.CancelledError:
            logger.debug("Auto-delete timer cancelled")
        except (discord.errors.DiscordException, RuntimeError, ValueError) as e:
            logger.error(f"Error in auto-delete timer: {e}", exc_info=True)

    async def broadcast_clicked(self, interaction: discord.Interaction):
        """Handle Broadcast Donation button click."""
        try:
            # /donate posts this view NON-ephemerally for 890 seconds, so everyone
            # in the channel can press this. Each press opens a modal that books a
            # real DonationAdded event with a FRESH interaction.id, so the ledger's
            # idempotency never bites - it was the one mech button the operator's
            # donate slider did not reach. Under mech_donate, the same bucket as
            # the Power/Donate button: get_button_cooldown derives the slider only
            # from a name starting with "mech_".
            from cogs.control_ui import _mech_button_braked

            if await _mech_button_braked(interaction, f"mech_donate_{interaction.channel_id}"):
                return
            # Show modal for donation details
            modal = DonationBroadcastModal(self.donation_manager_available, interaction.user.name, self.bot)
            await interaction.response.send_modal(modal)
        except (discord.errors.DiscordException, RuntimeError, ValueError) as e:
            logger.error(f"Error in broadcast_clicked: {e}", exc_info=True)


class DonationBroadcastModal(DDCModal):
    """Modal for donation broadcast details."""

    def __init__(self, donation_manager_available: bool, default_name: str, bot=None):
        from .translation_manager import _
        super().__init__(title=_("📢 Broadcast Your Donation"))
        self.donation_manager_available = donation_manager_available
        self.bot = bot  # Store bot instance for mech service access

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

        # Get dynamic placeholder for amount field with next level info
        amount_placeholder = self._get_dynamic_amount_placeholder()

        # Amount field (optional) with dynamic placeholder showing next level goal
        self.amount_input = discord.ui.InputText(
            label=_("💰 Donation Amount (optional)"),
            placeholder=amount_placeholder,
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

    def _get_dynamic_amount_placeholder(self) -> str:
        """Get dynamic placeholder text showing how much is needed for next level."""
        from .translation_manager import _

        try:
            # Get current mech state from progress_service (includes member-based dynamic costs)
            from services.mech.progress_service import get_progress_service

            progress_service = get_progress_service()
            state = progress_service.get_state()

            # Calculate remaining amount needed for next level
            needed_amount = state.evo_max - state.evo_current

            if needed_amount > 0 and state.level < 11:
                # Format amount (remove trailing zeros)
                formatted_amount = f"{needed_amount:.2f}".rstrip('0').rstrip('.')
                formatted_amount = formatted_amount.replace('.00', '')

                next_level = state.level + 1

                # Return dynamic placeholder with motivation text
                return f"💎 Need ${formatted_amount} for Level {next_level}! (e.g. {formatted_amount})"
            else:
                # At max level or no next level info
                return _("🎯 Support DDC development! (e.g. 10.50)")

        except (discord.errors.DiscordException, RuntimeError, ValueError, OSError) as e:
            logger.error(f"Error getting dynamic amount placeholder: {e}", exc_info=True)
            # Fallback to default placeholder
            return _("10.50 (numbers only, $ will be added automatically)")

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle modal submission."""
        logger.info(f"=== DONATION MODAL CALLBACK STARTED ===")
        logger.info(f"User: {interaction.user.name}, Raw inputs: name={self.name_input.value}, amount={self.amount_input.value}")

        # Send immediate acknowledgment to avoid timeout (will be replaced quickly)
        from .translation_manager import _
        await interaction.response.send_message(
            _("⏳ Processing..."),  # Shortened processing message
            ephemeral=True, delete_after=NOTICE_STAYS_FOR
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
            import re
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
                    ephemeral=True, delete_after=NOTICE_STAYS_FOR
                )
                return

            # Process donation through mech service
            donation_amount_euros = None
            processing_msg = None  # Initialize for later deletion
            # Set only after the ledger confirmed the booking. Previously the
            # broadcast below ran regardless: an exception was swallowed at the
            # "except" further down (evolution_occurred = False) and execution fell
            # through, and with donation_manager_available False nothing was booked
            # at all - both ways thanked the donor for money the ledger never saw.
            # SPEC.md Z3/Z8.
            donation_booked = False
            evolution_occurred = False
            old_evolution_level = None
            new_evolution_level = None

            if self.donation_manager_available:
                try:
                    from services.mech.mech_service import get_mech_service
                    mech_service = get_mech_service()

                    # Get old state before donation using SERVICE FIRST
                    from services.mech.mech_service import GetMechStateRequest
                    old_state_request = GetMechStateRequest(include_decimals=False)
                    old_state_result = mech_service.get_mech_state_service(old_state_request)
                    if not old_state_result.success:
                        logger.error("Failed to get old mech state")
                        # This used to be a bare return. The callback has already
                        # answered "⏳ Processing..." to close the modal, so every
                        # path after it owes the donor a replacement - and the
                        # booking failure three branches down does exactly that.
                        # Somebody who has just given money and is told nothing
                        # assumes it did not work, and gives again (review E19).
                        await interaction.edit_original_response(
                            content=_("❌ Donation processing failed: {error}").format(
                                error=_("the mech state could not be read")))
                        return
                    old_evolution_level = old_state_result.level

                    # Parse amount if provided
                    if amount:
                        amount_match = re.search(r'(\d+(?:\.\d+)?)', amount)
                        if amount_match:
                            donation_amount_euros = float(amount_match.group(1))

                    # Record donation if amount > 0
                    if donation_amount_euros and donation_amount_euros > 0:
                        amount_dollars = float(donation_amount_euros)  # Keep decimal precision

                        # Quick feedback to user first (store message to delete later)
                        processing_msg = await interaction.followup.send(
                            _("💰 Processing ${amount} donation...").format(amount=f"{amount_dollars:.2f}"),
                            ephemeral=False  # Make it visible so we can delete it
                        )

                        # UNIFIED DONATION SERVICE: Single clean path with guaranteed events
                        from services.donation.unified_donation_service import process_discord_donation

                        donation_result = await process_discord_donation(
                            discord_username=interaction.user.name,
                            amount=amount_dollars,
                            user_id=str(interaction.user.id),
                            guild_id=str(interaction.guild.id) if interaction.guild else None,
                            channel_id=str(interaction.channel.id) if interaction.channel else None,
                            bot_instance=self.bot,
                            # Unique per submission: if the same interaction reaches
                            # the service twice, it is booked once. SPEC.md Z4.
                            idempotency_key=str(interaction.id),
                        )

                        if not donation_result.success:
                            logger.error(f"Donation failed: {donation_result.error_message}")
                            # The PUBLIC "Processing..." message must go: this early
                            # return used to skip both places that delete it, so the
                            # channel kept reading "Processing a $X donation" for a
                            # donation that never happened (SPEC.md Z8, review B14).
                            if processing_msg:
                                try:
                                    await processing_msg.delete()
                                except (discord.NotFound, discord.HTTPException) as e:
                                    logger.warning(f"Could not remove the processing message: {e}")
                            await interaction.followup.send(
                                _("❌ Donation processing failed: {error}").format(error=donation_result.error_message),
                                ephemeral=True, delete_after=NOTICE_STAYS_FOR
                            )
                            return

                        new_state = donation_result.new_state
                        donation_booked = True
                        logger.info(f"Donation recorded via unified service: ${amount_dollars:.2f}")
                    else:
                        # Get current state using SERVICE FIRST
                        new_state_request = GetMechStateRequest(include_decimals=False)
                        new_state_result = mech_service.get_mech_state_service(new_state_request)
                        if not new_state_result.success:
                            logger.error("Failed to get new mech state")
                            # Same as above (review E19): a bare return left the
                            # donor at "⏳ Processing..." for ever.
                            await interaction.edit_original_response(
                                content=_("❌ Donation processing failed: {error}").format(
                                    error=_("the mech state could not be read")))
                            return

                    # For donation cases, the new_state is returned from add_donation methods
                    # For non-donation cases, we use the SERVICE FIRST result
                    if 'new_state' not in locals():
                        new_evolution_level = new_state_result.level
                        evolution_occurred = new_evolution_level > old_evolution_level
                        old_power = old_state_result.power
                        new_power = new_state_result.power
                    else:
                        # Check if evolution occurred (donation cases)
                        evolution_occurred = new_state.level > old_evolution_level
                        new_evolution_level = new_state.level
                        old_power = old_state_result.power
                        new_power = new_state.Power

                    if evolution_occurred:
                        logger.info(f"EVOLUTION! Level {old_evolution_level} → {new_evolution_level}")

                    # Force update of mech animation when level OR power changes.
                    # new_power is already set by BOTH branches above (:4866 from
                    # new_state_result, :4872 from new_state), so re-reading it from
                    # new_state here was redundant - and fatal when no amount was named:
                    # that path never assigns new_state, and the UnboundLocalError fell
                    # through both except blocks (:4885 and :4973 list neither), so the
                    # final response at :4964 was never sent and the user kept staring at
                    # "Processing..." while the supporter message never went out.
                    # new_evolution_level is set by both branches, so it is used instead.
                    # SPEC.md Z3.
                    level_changed = new_evolution_level != old_state_result.level
                    power_changed = new_power != old_power

                    if level_changed or power_changed:
                        if level_changed:
                            logger.info(f"Level changed from {old_state_result.level} to {new_evolution_level} - updating mech animations")
                        if power_changed:
                            logger.info(f"Power changed from {old_power} to {new_power} - updating mech animations")

                        # Events are now automatically handled by UnifiedDonationService
                        # No manual event emission needed - prevents duplicate events

                        # REMOVED: Manual update call to prevent duplicate updates
                        # The donation_event already triggers automatic updates via event system
                        # Manual update here caused double-updates and race conditions
                        logger.info("Donation event will trigger automatic overview updates via event system")

                except (discord.errors.DiscordException, RuntimeError, OSError) as e:
                    logger.error(f"Error processing donation: {e}", exc_info=True)
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
                # Say what happens to the power, otherwise the level-up looks like lost money:
                # on level-up the surplus above the goal becomes the new power (plus $1 on an
                # exact hit), so a donation that just barely reaches the goal leaves the mech
                # near zero and offline immediately afterwards.
                evolution_status += "\n" + _("Surplus carried over as new power: {power}").format(
                    power=f"${new_power:.2f}"
                )

            # Send to channels if sharing publicly
            sent_count = 0
            failed_count = 0

            # "The user named no amount" and "the amount was never processed" are two
            # different things, and conflating them defeated this guard once already:
            # donation_amount_euros is assigned only INSIDE the booking block above,
            # so it stays None whenever booking is skipped - which let an unbooked
            # donation broadcast through. The user's own input decides instead. With
            # an amount a confirmed booking is required; without one there is nothing
            # to book and the "X supports DDC" message may go out. `amount` is also
            # what the message below branches on, so guard and message agree.
            broadcast_allowed = donation_booked or not amount
            if should_share_publicly and not broadcast_allowed:
                logger.warning(
                    "Donation broadcast suppressed: the ledger did not confirm the booking"
                )

            if should_share_publicly and broadcast_allowed:
                config = load_config()
                channels_config = config.get('channel_permissions', {})

                opted_out_count = 0

                for channel_id_str, channel_info in channels_config.items():
                    try:
                        channel_id = int(channel_id_str)
                        channel = interaction.client.get_channel(channel_id)

                        # Same rule the notification loop already applies further
                        # down: a channel that opted out of donation broadcasts gets
                        # nothing. This path used to ignore the flag entirely.
                        if channel and channel_info.get('donation_broadcasts', True):
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
                        elif channel is not None:
                            # Opted out in the web panel - counted on its own. It used
                            # to raise failed_count like a channel that could not be
                            # reached, and the admin was told deliveries had failed
                            # when nothing had (review B36).
                            opted_out_count += 1
                            logger.info(f"Donation notice not sent to channel {channel_id_str}: "
                                        f"the channel opted out of donation broadcasts")
                        else:
                            failed_count += 1

                    except (discord.errors.DiscordException, RuntimeError) as channel_error:
                        failed_count += 1
                        logger.error(f"Error sending to channel {channel_id_str}: {channel_error}", exc_info=True)

            # Respond to user
            if should_share_publicly and not broadcast_allowed:
                response_text = _("⚠️ **Donation could not be recorded**") + "\n\n"
                response_text += _("Nothing was sent to any channel. Please try again later.")
            elif should_share_publicly:
                # Channels that opted out are neither a delivery nor a failure, so
                # they appear in the log and not in this summary (review B36).
                logger.info(f"Donation broadcast: {sent_count} sent, {failed_count} failed, "
                            f"{opted_out_count} opted out")
                response_text = _("✅ **Donation broadcast sent!**") + "\n\n"
                response_text += _("📢 Sent to **{count}** channels").format(count=sent_count) + "\n"
                if failed_count > 0:
                    response_text += _("⚠️ Failed to send to {count} channels").format(count=failed_count) + "\n"
                response_text += "\n" + _("Thank you **{donor_name}** for your generosity! 🙏").format(donor_name=donor_name)
            else:
                response_text = _("✅ **Donation recorded privately!**") + "\n\n"
                response_text += _("Thank you **{donor_name}** for your generous support! 🙏").format(donor_name=donor_name) + "\n"
                response_text += _("Your donation has been recorded and helps power the Donation Engine.")

            # Replace the processing message with the final result
            await interaction.edit_original_response(content=response_text)

            # Clean up processing message if donation was processed
            if processing_msg:
                try:
                    await processing_msg.delete()
                except Exception:
                    pass  # Ignore if already deleted or expired

        except Exception as e:  # noqa: BLE001
            # Broad on purpose. Everything below this line exists to give the
            # donor an answer and to remove the public "Processing a $X
            # donation" message, and the tuple that stood here - (DiscordException,
            # RuntimeError, ValueError) - did not include what the mech service
            # actually raises: MechStateError -> MechServiceError ->
            # DDCBaseException. So a mech failure left the callback entirely,
            # past the cleanup and past the answer, and the donor watched
            # "⏳ Processing..." for ever (review E19).
            logger.error("Error in donation broadcast modal: %s: %s",
                         type(e).__name__, e, exc_info=True)

            # Clean up processing message even if error occurred
            if processing_msg:
                try:
                    await processing_msg.delete()
                except Exception:
                    pass

            # "Please try again later" is the one thing that must NOT be said for
            # money the ledger already took: the Discord path keys its idempotency
            # on interaction.id, and resubmitting the modal is a NEW interaction -
            # so a second attempt books the same donation a second time.
            if locals().get('donation_booked'):
                message = _("⚠️ Your donation **was recorded** - only the announcement "
                            "failed. Please do NOT submit it again.")
            else:
                message = _("❌ Error sending donation broadcast. Please try again later.")
            try:
                await interaction.edit_original_response(content=message)
            except (discord.errors.HTTPException, discord.errors.Forbidden) as edit_error:
                logger.error(f"Could not send error response: {edit_error}", exc_info=True)


class AddAdminModal(DDCModal):
    """Modal for adding a new admin user."""

    def __init__(self):
        from .translation_manager import _
        super().__init__(title=_("➕ Add Admin User"))

        # Discord User ID field
        self.user_id_input = discord.ui.InputText(
            label=_("Discord User ID"),
            placeholder=_("Enter the Discord User ID (e.g., 123456789012345678)"),
            style=discord.InputTextStyle.short,
            required=True,
            min_length=17,
            max_length=20
        )
        self.add_item(self.user_id_input)

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle modal submission."""
        from .translation_manager import _
        logger.info(f"=== ADD ADMIN MODAL CALLBACK STARTED ===")
        logger.info(f"User: {interaction.user.name}, Raw input: user_id={self.user_id_input.value}")

        try:
            # Get and validate the user ID
            raw_user_id = self.user_id_input.value.strip()

            # Validate: must be numeric and valid Discord snowflake format
            if not raw_user_id.isdigit():
                await interaction.response.send_message(
                    _("❌ Invalid User ID. Please enter only numbers (e.g., 123456789012345678)."),
                    ephemeral=True, delete_after=NOTICE_STAYS_FOR
                )
                return

            user_id = raw_user_id

            # Check if ID is in valid Discord snowflake range (>= Discord epoch)
            if int(user_id) < 21154535154122752:  # Minimum valid Discord snowflake
                await interaction.response.send_message(
                    _("❌ Invalid Discord User ID. The ID appears to be too small."),
                    ephemeral=True, delete_after=NOTICE_STAYS_FOR
                )
                return

            # Get admin service and current admins
            from services.admin.admin_service import get_admin_service
            admin_service = get_admin_service()
            # ONE step: read, check and write under the file lock. Doing the
            # cycle here meant a panel save could land between the read and the
            # write, and the list written had never seen it - both sides
            # answered success and one admin was gone. add_admin_user answers
            # False when the user is already there, which is the same check,
            # only inside the lock where it cannot go stale.
            note = f"Added via Discord by {interaction.user.name}"
            if not admin_service.add_admin_user(user_id, note):
                await interaction.response.send_message(
                    _("⚠️ This user is already an admin."),
                    ephemeral=True, delete_after=NOTICE_STAYS_FOR
                )
                return
            current_admins = admin_service.get_admin_data(
                force_refresh=True).get('discord_admin_users', [])
            success = True

            if success:
                logger.info(f"Admin added successfully: {user_id} by {interaction.user.id}")
                await interaction.response.send_message(
                    _("✅ Admin added successfully!\n\nUser ID: `{user_id}`\nTotal admins: {count}").format(
                        user_id=user_id,
                        count=len(current_admins)
                    ),
                    ephemeral=True, delete_after=NOTICE_STAYS_FOR
                )
            else:
                logger.error(f"Failed to save admin data when adding {user_id}")
                await interaction.response.send_message(
                    _("❌ Failed to save admin data. Please try again."),
                    ephemeral=True, delete_after=NOTICE_STAYS_FOR
                )

        except Exception as e:
            logger.error(f"Error in AddAdminModal callback: {e}", exc_info=True)
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        _("❌ An error occurred while adding the admin. Please try again."),
                        ephemeral=True, delete_after=NOTICE_STAYS_FOR
                    )
            except (discord.errors.DiscordException, RuntimeError):
                pass
