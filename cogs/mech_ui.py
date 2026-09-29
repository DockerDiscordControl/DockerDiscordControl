# -*- coding: utf-8 -*-
"""The mech panel: the view under the overview and its buttons - details, donate,
history, the story, the song.

Moved out of cogs/control_ui.py on 2026-09-28 (that file stood at 2,608 lines on
the ceiling list, tests/spec/test_no_file_or_class_grows_past_its_ceiling.py).
The code is unchanged; it takes the Help and Info buttons from control_ui and
the Admin button from admin_ui, neither of which imports this module back.
"""

import io
from typing import TYPE_CHECKING

import discord
from discord.ui import Button

from services.donation.donation_utils import is_donations_disabled
from utils.logging_utils import get_module_logger

from .admin_ui import AdminButton
from .control_ui import HelpButton, InfoDropdownButton
from .ddc_ui import NOTICE_STAYS_FOR, DDCView, PrivateView
from .translation_manager import _

if TYPE_CHECKING:
    from .docker_control import DockerControlCog

logger = get_module_logger('mech_ui')

# TaskDeletePanelView and MechControlsLabelButton stood here: a view and a
# disabled label button that nothing ever built, and whose callback said of
# itself "This should never be called since button is disabled" (review B22).

class MechView(DDCView):
    """View with simplified buttons for Mech status in /ss command."""

    def __init__(self, cog_instance: 'DockerControlCog', channel_id: int):
        super().__init__(timeout=None)  # Persistent view
        self.cog = cog_instance
        self.channel_id = channel_id

        # Check if donations are disabled
        donations_disabled = is_donations_disabled()

        # Button order: 1. Mech, 2. Info, 3. Admin, 4. Help

        # Button 1: Mech (only if donations enabled)
        if not donations_disabled:
            self.add_item(MechDetailsButton(cog_instance, channel_id))

        # Button 2: Info button for container information
        self.add_item(InfoDropdownButton(cog_instance, channel_id))

        # Button 3: Admin button for administrative control
        self.add_item(AdminButton(cog_instance, channel_id))

        # Button 4: Help button (always shown)
        self.add_item(HelpButton(cog_instance, channel_id))


class MechDetailsButton(Button):
    """Button to show detailed mech status in private message."""

    def __init__(self, cog_instance: 'DockerControlCog', channel_id: int):
        super().__init__(
            style=discord.ButtonStyle.primary,
            label="Mech",
            custom_id=f"mech_details_{channel_id}"
        )
        self.cog = cog_instance
        self.channel_id = channel_id

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle mech details button click by sending private status message."""
        try:
            logger.info(f"Mech details requested by user {interaction.user.name} in channel {self.channel_id}")

            # self.custom_id = mech_details_<channel> -> slider mech_details.
            # Unbraked and without a slider before; see _mech_button_braked.
            if await _mech_button_braked(interaction, self.custom_id):
                return

            # Defer the response as ephemeral (private message)
            await interaction.response.defer(ephemeral=True)

            # Get mech status details from service (using high resolution for private view)
            from services.web.mech_status_details_service import get_mech_status_details_service, MechStatusDetailsRequest

            service = get_mech_status_details_service()
            request = MechStatusDetailsRequest(use_high_resolution=True)  # Use big mechs for private details
            result = service.get_mech_status_details(request)

            if not result.success:
                await interaction.followup.send(
                    _("❌ Error retrieving mech status details. Please try again later."),
                    ephemeral=True, delete_after=NOTICE_STAYS_FOR
                )
                return

            # Use embed.description instead of add_field() to eliminate A-spacing!
            description_parts = []

            # Level and Speed section
            if result.level_text:
                description_parts.append(result.level_text)
            if result.speed_text:
                description_parts.append(result.speed_text)

            # Add spacing before power section
            description_parts.append("")

            # Power section
            if result.power_text:
                description_parts.append(result.power_text)
            if result.power_bar:
                description_parts.append(f"`{result.power_bar}`")
            if result.energy_consumption:
                description_parts.append(result.energy_consumption)

            # Add spacing before evolution section
            description_parts.append("")

            # Evolution section
            if result.next_evolution and result.evolution_bar:
                description_parts.append(result.next_evolution)
                description_parts.append(f"`{result.evolution_bar}`")

            # Create embed with description (NO A-spacing!) - DISCORD LIMIT: 4096 chars
            full_description = "\n".join(description_parts)

            # Discord embed description limit is 4096 characters
            if len(full_description) > 4096:
                # Truncate but keep important information visible
                truncated_description = full_description[:4000] + "\n\n*[Description truncated]*"
                logger.warning(f"Mech description truncated: {len(full_description)} -> {len(truncated_description)} chars")
            else:
                truncated_description = full_description

            embed = discord.Embed(
                title=_("Mech Status"),
                description=truncated_description,
                color=0x00ff88
            )

            embed.set_footer(text="https://ddc.bot")

            # Create view with donate and history buttons
            view = MechDetailsView(self.cog, self.channel_id)

            # Attach animation if available
            files = []
            if result.animation_bytes and result.content_type:
                # Create unique filename to prevent Discord caching issues
                # Include level and power to ensure cache busting when mech evolves
                # PERFORMANCE: Use data from result instead of making extra service calls
                unique_filename = f"mech_level_{result.level}_power_{result.power_decimal:.2f}.webp"

                file = discord.File(
                    io.BytesIO(result.animation_bytes),
                    filename=unique_filename
                )
                files.append(file)
                embed.set_image(url=f"attachment://{unique_filename}")

            # Send the private message
            await interaction.followup.send(
                embed=embed,
                view=view,
                files=files,
                ephemeral=True
            )

            logger.info(f"Mech details sent to user {interaction.user.name}")

        except (RuntimeError, ValueError, KeyError) as e:
            logger.error(f"Error showing mech details: {e}", exc_info=True)
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(
                        _("❌ Error retrieving mech details. Please try again later."),
                        ephemeral=True, delete_after=NOTICE_STAYS_FOR
                    )
                else:
                    await interaction.response.send_message(
                        _("❌ Error retrieving mech details. Please try again later."),
                        ephemeral=True, delete_after=NOTICE_STAYS_FOR
                    )
            except (discord.errors.DiscordException, RuntimeError):
                # Interaction may have already been responded to or expired
                pass

async def _mech_button_braked(interaction: discord.Interaction, name: str) -> bool:
    """Spam brake for mech buttons that have not responded yet.

    True means: refused, the callback returns. These buttons used not to ask
    the service at all - their sliders in the panel (mech_donate, mech_display,
    mech_story, mech_music) moved nothing, and the per-minute limit did not
    reach them. The name must start with "mech_<slider>_": get_button_cooldown
    derives the slider only from that. As for the other buttons: an error in the
    service does not lock.
    """
    from services.infrastructure.spam_protection_service import get_spam_protection_service
    spam_service = get_spam_protection_service()
    if not spam_service.is_enabled():
        return False
    try:
        if spam_service.is_on_cooldown(interaction.user.id, name):
            remaining = spam_service.get_remaining_cooldown(interaction.user.id, name)
            await interaction.response.send_message(
                _("⏰ Please wait {remaining:.1f} more seconds before using this button again.").format(
                    remaining=remaining
                ),
                ephemeral=True, delete_after=NOTICE_STAYS_FOR
            )
            return True
        spam_service.add_user_cooldown(interaction.user.id, name)
    except (RuntimeError, AttributeError, KeyError) as e:
        logger.error(f"Spam protection error for button '{name}': {e}", exc_info=True)
    return False


class MechDonateButton(Button):
    """Button to trigger donation functionality from expanded mech view."""

    def __init__(self, cog_instance: 'DockerControlCog', channel_id: int):
        self.cog = cog_instance
        self.channel_id = channel_id

        super().__init__(
            style=discord.ButtonStyle.green,
            label=_("Power/Donate"),
            custom_id=f"mech_donate_{channel_id}",
            row=0  # Row 0: All buttons in one row
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Trigger the donate functionality."""
        try:
            # self.custom_id = mech_donate_<channel>. The private donate button
            # forwards here and so shares this bucket.
            if await _mech_button_braked(interaction, self.custom_id):
                return

            # Call the existing donate interaction handler
            await self.cog._handle_donate_interaction(interaction)

        except (RuntimeError, ValueError, KeyError) as e:
            logger.error(f"Error in mech donate button: {e}", exc_info=True)
            try:
                # Smart error response - check if interaction was already handled by _handle_donate_interaction
                if interaction.response.is_done():
                    await interaction.followup.send(_("❌ Error processing donation. Please try `/donate` directly."), ephemeral=True, delete_after=NOTICE_STAYS_FOR)
                else:
                    await interaction.response.send_message(_("❌ Error processing donation. Please try `/donate` directly."), ephemeral=True, delete_after=NOTICE_STAYS_FOR)
            except discord.errors.NotFound:
                logger.warning("Cannot send error message - interaction expired")
            except (discord.errors.DiscordException, RuntimeError):
                pass

# DonationView has been moved back to docker_control.py where it belongs


# =============================================================================
# MECH HISTORY BUTTON FOR EXPANDED VIEW
# =============================================================================

class MechHistoryButton(Button):
    """Button to show mech evolution history with unlocked/locked visualization."""

    def __init__(self, cog_instance: 'DockerControlCog', channel_id: int):
        self.cog = cog_instance
        self.channel_id = channel_id

        super().__init__(
            style=discord.ButtonStyle.secondary,
            emoji="📖",  # Book - Mech evolution history
            custom_id=f"mech_history_{channel_id}",
            row=0  # Row 0: All buttons in one row
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Show mech selection buttons."""
        try:
            # Apply spam protection
            from services.infrastructure.spam_protection_service import get_spam_protection_service
            spam_service = get_spam_protection_service()

            # CRITICAL: Defer IMMEDIATELY to avoid "Unknown interaction" errors
            # ROBUST: Handle interaction expiration (15 min timeout) gracefully
            # Outside the spam block since 2026-09-20: it used to sit inside
            # "if spam_service.is_enabled()", and everything below answers through
            # followup, which needs this acknowledgement. With spam protection
            # switched off the button failed on every press and the user saw
            # Discord's "This interaction failed" (review B4). The comment here
            # called that "current behaviour, a separate decision" - it was a bug.
            try:
                await interaction.response.defer(ephemeral=True)
            except discord.NotFound as e:
                if e.code == 10062:  # Unknown interaction (expired after 15 minutes)
                    logger.info(f"⏱️ Mech History: Interaction expired (user waited >15 min). User: {interaction.user.name}")
                    # Cannot respond - interaction is dead. User needs to re-open mech details
                    return
                else:
                    raise  # Re-raise other NotFound errors

            if spam_service.is_enabled():
                # self.custom_id, not "info": the mech_history slider in the
                # panel (default 5) moved nothing, because braking used the
                # info slider (3). Through the service rather than an
                # attribute on the button, so the panel's value is the one
                # that applies.
                try:
                    if spam_service.is_on_cooldown(interaction.user.id, self.custom_id):
                        remaining = spam_service.get_remaining_cooldown(interaction.user.id, self.custom_id)
                        await interaction.followup.send(
                            _("⏰ Please wait {remaining:.1f} more seconds before using this button again.").format(
                                remaining=remaining
                            ),
                            ephemeral=True, delete_after=NOTICE_STAYS_FOR
                        )
                        return
                    spam_service.add_user_cooldown(interaction.user.id, self.custom_id)
                except (RuntimeError, AttributeError, KeyError) as e:
                    logger.error(f"Spam protection error for mech history button: {e}", exc_info=True)

            # Check if donations are disabled (after defer, use followup)
            if is_donations_disabled():
                await interaction.followup.send(_("❌ Mech system is currently disabled."), ephemeral=True, delete_after=NOTICE_STAYS_FOR)
                return

            # Get current mech state using SERVICE FIRST
            from services.mech.mech_service import get_mech_service, GetMechStateRequest
            mech_service = get_mech_service()
            mech_state_request = GetMechStateRequest(include_decimals=False)
            mech_state_result = mech_service.get_mech_state_service(mech_state_request)
            if not mech_state_result.success:
                logger.error("[MECH] The mech state could not be read - "
                             "the selection cannot be shown")
                await interaction.followup.send(
                    _("❌ An error occurred. Please try again."), ephemeral=True, delete_after=NOTICE_STAYS_FOR)
                return
            current_level = mech_state_result.level

            # Create mech selection view
            await self._show_mech_selection(interaction, current_level)

        except (RuntimeError, ValueError, KeyError) as e:
            logger.error(f"Error in mech history button: {e}", exc_info=True)
            # After defer(), we have 15 minutes - use followup for error messages
            try:
                await interaction.followup.send(_("❌ Error loading mech history."), ephemeral=True, delete_after=NOTICE_STAYS_FOR)
            except discord.errors.NotFound:
                # Interaction expired - log but don't crash (should not happen within 15 min)
                logger.warning(f"Interaction expired unexpectedly: {e}")
            except (discord.errors.HTTPException, discord.errors.DiscordException) as error_ex:
                logger.error(f"Failed to send error message: {error_ex}", exc_info=True)

    async def _show_mech_selection(self, interaction: discord.Interaction, current_level: int):
        """Show buttons for each unlocked mech + next shadow mech."""
        import discord
        from discord.ui import View, Button

        embed = discord.Embed(
            title=_("🛡️ Mech Evolution History"),
            description=f"**{_('The Song of Steel and Stars')}**\n*{_('A Chronicle of the Mech Ascension')}*\n\n{_('Select a mech to view')}",
            color=0x00ff41
        )

        view = MechSelectionView(self.cog, current_level)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

        # History display complete


    def _load_epic_story_chapters(self) -> dict:
        """Load and parse the epic story chapters using MechStoryService."""
        from services.mech.mech_story_service import get_mech_story_service

        story_service = get_mech_story_service()
        # The bot's language - get_all_chapters() defaults to 'de', so every server
        # got the German story. Languages without a story file fall back to English.
        from .translation_manager import translation_manager
        return story_service.get_all_chapters(translation_manager.get_current_language())

    def _get_chapter_key_for_level(self, level: int) -> str:
        """Map mech level to story chapter key using MechStoryService."""
        from services.mech.mech_story_service import get_mech_story_service

        story_service = get_mech_story_service()
        return story_service.get_chapter_key_for_level(level)


class MechSelectionView(PrivateView):
    """View with buttons for each unlocked mech."""

    def __init__(self, cog_instance: 'DockerControlCog', current_level: int):
        super().__init__(timeout=None)
        self.cog = cog_instance
        self.current_level = current_level

        # SERVICE FIRST: Use unified evolution system
        from services.mech.mech_evolutions import get_evolution_level_info

        # Add button for each unlocked mech (Level 1-11)
        for level in range(1, min(current_level + 1, 12)):  # 12 to include up to Level 11
            evolution_info = get_evolution_level_info(level)
            if evolution_info:
                button = MechDisplayButton(cog_instance, level, evolution_info.name, unlocked=True)
                self.add_item(button)

        # Add "Next" button for shadow preview (only for levels < 10)
        # Level 10+ gets Epilogue instead of Next button
        next_level = current_level + 1
        if next_level <= 11 and current_level < 10:
            evolution_info = get_evolution_level_info(next_level)
            if evolution_info:
                button = MechDisplayButton(cog_instance, next_level, "Next", unlocked=False)
                self.add_item(button)

        # Show Epilogue button starting at Level 10 (final stages)
        if current_level >= 10:
            button = EpilogueButton(cog_instance)
            self.add_item(button)


class MechDisplayButton(Button):
    """Button to display a specific mech."""

    def __init__(self, cog_instance: 'DockerControlCog', level: int, label_text: str, unlocked: bool):
        self.cog = cog_instance
        self.level = level
        self.unlocked = unlocked

        super().__init__(
            style=discord.ButtonStyle.primary if unlocked else discord.ButtonStyle.secondary,
            label=f"{level}" if unlocked else label_text,
            custom_id=f"mech_display_{level}"
        )

    def _is_unlocked_now(self) -> bool:
        """Check the unlock state against the live mech level.

        The custom_id is the same for unlocked buttons and the locked "Next" button, so a
        persistent view re-registered after a restart can't know which one was clicked.
        Falls back to the flag given at construction if the level can't be read.
        """
        try:
            from services.mech.mech_service import get_mech_service, GetMechStateRequest
            state = get_mech_service().get_mech_state_service(GetMechStateRequest(include_decimals=False))
            if state.success:
                return self.level <= state.level
            logger.warning(f"Could not read mech level to verify unlock state of level {self.level}")
        except (ImportError, AttributeError, RuntimeError, ValueError) as e:
            logger.warning(f"Could not verify unlock state of mech level {self.level}: {e}")
        return self.unlocked

    async def callback(self, interaction: discord.Interaction) -> None:
        """Display the mech using pre-rendered cached images."""
        try:
            # Check if donations are disabled
            if is_donations_disabled():
                await interaction.response.send_message(_("❌ Mech system is currently disabled."), ephemeral=True, delete_after=NOTICE_STAYS_FOR)
                return

            # self.custom_id = mech_display_<level> -> slider mech_display.
            if await _mech_button_braked(interaction, self.custom_id):
                return

            # Defer response to prevent Discord interaction timeout
            await interaction.response.defer(ephemeral=True)

            # SERVICE FIRST: Use unified evolution system
            from services.mech.mech_display_cache_service import get_mech_display_cache_service, MechDisplayImageRequest
            import io

            from services.mech.mech_evolutions import get_evolution_level_info
            display_cache_service = get_mech_display_cache_service()
            evolution_info = get_evolution_level_info(self.level)

            if not evolution_info:
                await interaction.followup.send(_("❌ Mech data not found."), ephemeral=True, delete_after=NOTICE_STAYS_FOR)
                return

            if self._is_unlocked_now():
                # Load pre-rendered unlocked mech from cache
                image_request = MechDisplayImageRequest(
                    evolution_level=self.level,
                    image_type='unlocked'
                )
                image_result = display_cache_service.get_mech_display_image(image_request)

                if not image_result.success:
                    logger.error(f"Failed to load unlocked mech {self.level}: {image_result.error_message}")
                    await interaction.followup.send(_("❌ Error loading mech animation."), ephemeral=True, delete_after=NOTICE_STAYS_FOR)
                    return

                embed = discord.Embed(
                    title=f"✅ Level {self.level}: {_(evolution_info.name)}",
                    description=f"*{_(evolution_info.description)}*",
                    color=int(evolution_info.color.replace('#', ''), 16)
                )

                file = discord.File(io.BytesIO(image_result.image_bytes), filename=image_result.filename)

                # Create view with Read Story and Music buttons (unlocked mech)
                view = MechStoryView(self.cog, self.level, unlocked=True)
                await interaction.followup.send(embed=embed, file=file, view=view, ephemeral=True)
            else:
                # Load pre-rendered shadow mech from cache
                image_request = MechDisplayImageRequest(
                    evolution_level=self.level,
                    image_type='shadow'
                )
                image_result = display_cache_service.get_mech_display_image(image_request)

                if not image_result.success:
                    logger.error(f"Failed to load shadow mech {self.level}: {image_result.error_message}")
                    await interaction.followup.send(_("❌ Error loading mech preview."), ephemeral=True, delete_after=NOTICE_STAYS_FOR)
                    return

                # Calculate remaining amount using evolution state (same as Spenden Modal)
                from services.mech.progress_service import get_progress_service

                progress_service = get_progress_service()
                state = progress_service.get_state()

                # Use evolution-based calculation (evo_max - evo_current) - includes dynamic member costs
                needed_amount = state.evo_max - state.evo_current

                if needed_amount > 0:
                    formatted_amount = f"{needed_amount:.2f}".rstrip('0').rstrip('.')
                    formatted_amount = formatted_amount.replace('.00', '')
                    needed_text = f"**{_('Need $')}{formatted_amount} {_('more to unlock')}**"
                else:
                    needed_text = f"**{_('Ready to unlock!')}**"

                embed = discord.Embed(
                    title=f"🔒 Level {self.level}: {_(evolution_info.name)}",
                    description=f"*{_('Next Evolution')}: {_(evolution_info.description)}*\n{needed_text}",
                    color=0x444444
                )

                file = discord.File(io.BytesIO(image_result.image_bytes), filename=image_result.filename)

                # Create view WITHOUT buttons (preview mech - not unlocked)
                view = MechStoryView(self.cog, self.level, unlocked=False)
                await interaction.followup.send(embed=embed, file=file, view=view, ephemeral=True)

        except (RuntimeError, ValueError, KeyError) as e:
            logger.error(f"Error displaying mech {self.level}: {e}", exc_info=True)
            # After defer(), always use followup for error messages
            await interaction.followup.send(_("❌ Error loading mech."), ephemeral=True, delete_after=NOTICE_STAYS_FOR)


class EpilogueButton(Button):
    """Button to show the epilogue."""

    def __init__(self, cog_instance: 'DockerControlCog'):
        self.cog = cog_instance

        super().__init__(
            style=discord.ButtonStyle.danger,
            label=_("Epilogue"),
            custom_id="epilogue_button"
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Show corrupted epilogue."""
        try:
            # Check if donations are disabled
            if is_donations_disabled():
                await interaction.response.send_message(_("❌ Mech system is currently disabled."), ephemeral=True, delete_after=NOTICE_STAYS_FOR)
                return

            # Not self.custom_id ("epilogue_button"): without "mech_story_" in
            # front, the name never reached the story slider.
            if await _mech_button_braked(interaction, "mech_story_epilogue"):
                return

            epilogue_text = """**Epilogue: W#!sp*r of th3 [ERROR_CODE_11]**

C3n†ur!3§ l4†3r, th3 m3chs 4r3… [D4T4 C0RRUPT].
†h3 Husk§ l!3 ru§t!ng !n s!l3nt f!3lds.
C0r3w4lk3rs = mu§3um r3l!cs.
†!†4ns → du§t.
Gu4rd!4ns → myths.
…y3t, in th3 ru!ns, §t0r!es endure.
0ld s0ld!ers wh!§per — b3trayal, desp@@ir.
Ch!ldr3n l34rn hymn§ 0f Rad!ance.
P!lgr!ms pray → Ascendants long turn3d t0 a§h.
&& a fragi— h0pe l!ngers: s0m3h0w… af†3r wars, af†3r death… hum4n!ty m!ght rise.
But — in d4rk bunk3rs, where cracked r4d!os hum w/ §tat!c…
…an0ther story i§ t0ld.
…b3y0nd Exarchs.
…b3y0nd gods.
…b3y0nd sta—rs.
N0t savior. N0t destroyer.
Fin4lity i†self.
They call it [███DATA??%&CORRUPT███].
And those who dare… sp34k its ████ do s0 only once.
[### ERR_SEG_A] Tr4nsmissi0n… d3gr4ded. checksum fail… !@#!
…fr4gm3nt…r3covered: "…vig…e…nere…" <<<
(ignore? no value? [redacted])
[### ERR_SEG_B] packet loss… ??? mismatch length.
"KEY…=…4…" [system note: truncated]
⚠️ W4RN!NG: SIGNAL integrity = unstable
[SYSTEM_F4!L] [c0nnection lost] [███shut███]"""

            embed = discord.Embed(
                title="💀 Epilogue: W#!sp*r of th3 [ERROR_CODE_11]",
                description=epilogue_text,
                color=0x330033
            )
            embed.set_footer(text=_("⚠️ DATA CORRUPTION DETECTED - TRANSMISSION UNSTABLE"))

            await interaction.response.send_message(embed=embed, ephemeral=True)

        except (RuntimeError, ValueError, KeyError) as e:
            logger.error(f"Error showing epilogue: {e}", exc_info=True)
            await interaction.response.send_message(_("❌ Error loading epilogue."), ephemeral=True, delete_after=NOTICE_STAYS_FOR)


class MechStoryView(PrivateView):
    """View with Read Story and Play Song buttons - only for unlocked mechs."""

    def __init__(self, cog_instance: 'DockerControlCog', level: int, unlocked: bool = True):
        super().__init__(timeout=None)
        self.cog = cog_instance
        self.level = level
        self.unlocked = unlocked

        # Only add buttons for unlocked mechs
        if unlocked:
            self.add_item(ReadStoryButton(cog_instance, level))
            self.add_item(PlaySongButton(cog_instance, level))


class ReadStoryButton(Button):
    """Button to read the story chapter for a mech."""

    def __init__(self, cog_instance: 'DockerControlCog', level: int):
        self.cog = cog_instance
        self.level = level

        super().__init__(
            style=discord.ButtonStyle.success,
            label=_("Read Story"),
            custom_id=f"read_story_{level}"
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Show the story chapter."""
        try:
            # Check if donations are disabled
            if is_donations_disabled():
                await interaction.response.send_message(_("❌ Mech system is currently disabled."), ephemeral=True, delete_after=NOTICE_STAYS_FOR)
                return

            # Not self.custom_id (read_story_<level>) - see EpilogueButton.
            if await _mech_button_braked(interaction, f"mech_story_{self.level}"):
                return

            # Defer response to prevent timeout during story loading
            await interaction.response.defer(ephemeral=True)

            # Load story chapters
            from services.mech.mech_service import get_mech_service
            story_chapters = {}
            story_content = """[STORY CONTENT PLACEHOLDER]"""

            # Parse chapters (using existing method from MechHistoryButton)
            # For now, use the existing helper
            mech_button = MechHistoryButton(self.cog, 0)
            story_chapters = mech_button._load_epic_story_chapters()

            # Get chapter key for this level
            chapter_key = mech_button._get_chapter_key_for_level(self.level)

            if chapter_key and chapter_key in story_chapters:
                chapter_content = story_chapters[chapter_key]

                # Get chapter info
                chapter_info = {
                    "prologue1": ("Prologue I: The Dying Light", 0x2b2b2b),
                    "prologue2": ("Prologue II: Scars That Walk", 0x444444),
                    "chapter1": ("Chapter I: The Standard", 0x888888),
                    "chapter2": ("Chapter II: The Hunger", 0x0099cc),
                    "chapter3": ("Chapter III: The Pulse", 0x00ccff),
                    "chapter4": ("Chapter IV: The Abyss", 0xffcc00),
                    "chapter5": ("Chapter V: The Rift", 0xff6600),
                    "chapter6": ("Chapter VI: Radiance", 0xcc00ff),
                    "chapter7": ("Chapter VII: The Idols of Steel", 0x00ffff),
                    "chapter8": ("Chapter VIII: The Exarchs", 0xffff00),
                    "chapter9": ("Chapter IX: The Prayer of the Omega", 0xff00ff),
                    "epilogue": ("Epilogue: W#!sp*r of th3 [ERROR_CODE_11]", 0x330033)
                }

                title, color = chapter_info.get(chapter_key, ("Story Chapter", 0x666666))

                # Split if too long
                if len(chapter_content) > 4000:
                    chapter_content = chapter_content[:4000] + "..."

                embed = discord.Embed(
                    title=title,
                    description=chapter_content,
                    color=color
                )
                embed.set_footer(
                text=f"{_('The Song of Steel and Stars')} - {_('A Chronicle of the Mech Ascension')}")

                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.followup.send(_("📖 No story chapter available for this mech yet."), ephemeral=True, delete_after=NOTICE_STAYS_FOR)

        except (RuntimeError, ValueError, KeyError) as e:
            logger.error(f"Error showing story for level {self.level}: {e}", exc_info=True)
            # After defer(), always use followup for error messages
            await interaction.followup.send(_("❌ Error loading story."), ephemeral=True, delete_after=NOTICE_STAYS_FOR)


class PlaySongButton(Button):
    """Button to play the music for a mech level as Discord attachment."""

    def __init__(self, cog_instance: 'DockerControlCog', level: int):
        self.cog = cog_instance
        self.level = level

        super().__init__(
            style=discord.ButtonStyle.primary,
            label=None,
            emoji="🎵",
            custom_id=f"play_song_{level}"
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Send direct music link for instant streaming (no file upload required)."""
        try:
            # Check if donations are disabled
            if is_donations_disabled():
                await interaction.response.send_message(_("❌ Mech system is currently disabled."), ephemeral=True, delete_after=NOTICE_STAYS_FOR)
                return

            # Not self.custom_id (play_song_<level>) - see EpilogueButton.
            if await _mech_button_braked(interaction, f"mech_music_{self.level}"):
                return

            # Defer response to prevent timeout during music service calls
            await interaction.response.defer(ephemeral=True)

            # Import and use MechMusicService to get GitHub URL
            from services.web.mech_music_service import get_mech_music_service, MechMusicRequest

            service = get_mech_music_service()
            request_obj = MechMusicRequest(level=self.level)

            # Get YouTube URL through service (no file uploads!)
            result = service.get_mech_music_url(request_obj)

            if result.success:
                # Send YouTube URL directly for native Discord video embed
                # This triggers Discord's automatic YouTube preview with play button!
                song_link = f"🎵 **{result.title}** (Mech Level {self.level})\n\n{result.url}"

                # No delete_after: Discord draws the link as a player, and the
                # 15 s notice timer took it away mid-song (stage 4, section 03).
                # The one named exemption of test_a_one_off_private_notice_clears_itself.
                await interaction.followup.send(song_link, ephemeral=True)
            else:
                await interaction.followup.send(
                    _("❌ No music available for Mech Level {level}").format(level=self.level) + "\n"
                    f"Error: {result.error}",
                    ephemeral=True, delete_after=NOTICE_STAYS_FOR
                )

        except (RuntimeError, ValueError, KeyError) as e:
            logger.error(f"Error generating music URL for level {self.level}: {e}", exc_info=True)
            # After defer(), always use followup for error messages
            await interaction.followup.send(_("❌ Error loading music."), ephemeral=True, delete_after=NOTICE_STAYS_FOR)


# =============================================================================
# MECH DETAILS VIEW FOR PRIVATE MESSAGES
# =============================================================================

class MechDetailsView(PrivateView):
    """View for private mech details messages with Spenden and History buttons."""

    def __init__(self, cog_instance: 'DockerControlCog', channel_id: int):
        super().__init__(timeout=None)  # Persistent view - buttons never expire
        self.cog = cog_instance
        self.channel_id = channel_id

        # Add donate and history buttons
        self.add_item(MechPrivateDonateButton(cog_instance, channel_id))
        self.add_item(MechPrivateHistoryButton(cog_instance, channel_id))


class MechPrivateDonateButton(Button):
    """Donate button for private mech details messages."""

    def __init__(self, cog_instance: 'DockerControlCog', channel_id: int):
        super().__init__(
            style=discord.ButtonStyle.green,
            label=_("Power/Donate"),
            custom_id=f"mech_private_donate_{channel_id}"
        )
        self.cog = cog_instance
        self.channel_id = channel_id

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle donate button click - reuse existing donate functionality."""
        try:
            # Reuse the existing MechDonateButton logic
            donate_button = MechDonateButton(self.cog, self.channel_id)
            await donate_button.callback(interaction)

        except (RuntimeError, ValueError, KeyError) as e:
            logger.error(f"Error in private donate button: {e}", exc_info=True)
            try:
                # Smart error response - check if interaction was already deferred by child button
                if interaction.response.is_done():
                    await interaction.followup.send(
                        _("❌ Error processing donation request. Please try again later."),
                        ephemeral=True, delete_after=NOTICE_STAYS_FOR
                    )
                else:
                    await interaction.response.send_message(
                        _("❌ Error processing donation request. Please try again later."),
                        ephemeral=True, delete_after=NOTICE_STAYS_FOR
                    )
            except discord.errors.NotFound:
                logger.warning("Cannot send error message - interaction expired")
            except (discord.errors.DiscordException, RuntimeError):
                pass


class MechPrivateHistoryButton(Button):
    """History button for private mech details messages."""

    def __init__(self, cog_instance: 'DockerControlCog', channel_id: int):
        super().__init__(
            style=discord.ButtonStyle.secondary,
            label=_("Mech History"),
            custom_id=f"mech_private_history_{channel_id}"
        )
        self.cog = cog_instance
        self.channel_id = channel_id

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle history button click - reuse existing history functionality."""
        try:
            # Reuse the existing MechHistoryButton logic
            history_button = MechHistoryButton(self.cog, self.channel_id)
            await history_button.callback(interaction)

        except (RuntimeError, ValueError, KeyError) as e:
            logger.error(f"Error in private history button: {e}", exc_info=True)
            try:
                # Smart error response - check if interaction was already deferred by child button
                if interaction.response.is_done():
                    await interaction.followup.send(
                        _("❌ Error loading mech history. Please try again later."),
                        ephemeral=True, delete_after=NOTICE_STAYS_FOR
                    )
                else:
                    await interaction.response.send_message(
                        _("❌ Error loading mech history. Please try again later."),
                        ephemeral=True, delete_after=NOTICE_STAYS_FOR
                    )
            except discord.errors.NotFound:
                logger.warning("Cannot send error message - interaction expired")
            except (discord.errors.DiscordException, RuntimeError):
                pass
