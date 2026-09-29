# -*- coding: utf-8 -*-
"""The admin panel's container picker: the Admin button and its paged dropdown.

Moved out of cogs/control_ui.py on 2026-09-28 (that file stood at 2,608 lines on
the ceiling list, tests/spec/test_no_file_or_class_grows_past_its_ceiling.py).
The code is unchanged; it takes the paging helpers and the channel permission
from control_ui, which does not import this module back.
"""

from typing import TYPE_CHECKING, Optional

import discord
from discord.ui import Button

from services.config.config_service import load_config
from services.config.server_config_service import get_server_config_service
from utils.logging_utils import get_module_logger

from .control_helpers import _admin_may_control, _channel_has_permission, _is_registered_admin
from .control_ui import (SELECT_PAGE_NEXT, SELECT_PAGE_PREV, _get_cached_channel_permission,
                         _page_arrows, _page_of, _paged_placeholder, _turn_page)
from .ddc_ui import NOTICE_STAYS_FOR, PrivateView
from .group_control import (admin_control_view, admin_panel_embed, controllable_entries,
                            group_config_for, running_state_for)
from .translation_manager import _

if TYPE_CHECKING:
    from .docker_control import DockerControlCog

logger = get_module_logger('admin_ui')

class AdminButton(Button):
    """Button to show admin control dropdown from /ss messages."""

    def __init__(self, cog_instance: 'DockerControlCog', channel_id: int):
        self.cog = cog_instance
        self.channel_id = channel_id

        super().__init__(
            style=discord.ButtonStyle.secondary,  # Gray/transparent button for admin
            label=None,
            emoji="🛠️",  # Hammer and wrench emoji for admin
            custom_id=f"admin_button_{channel_id}",
            row=0
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Show admin container selection dropdown when clicked."""
        # Acknowledge immediately - the checks below do file I/O and can exceed Discord's
        # 3 s limit (404 Unknown interaction). Everything after this replies via followup.
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.errors.NotFound:
            logger.warning(f"Admin button interaction expired for channel {self.channel_id}")
            return
        except discord.errors.HTTPException as e:
            logger.error(f"Error deferring admin button interaction: {e}", exc_info=True)
            return

        try:
            # SERVICE FIRST: Use AdminService to check permissions
            from services.admin.admin_service import get_admin_service
            admin_service = get_admin_service()

            # Check if user is admin
            user_id = str(interaction.user.id)
            if not admin_service.is_user_admin(user_id):
                await interaction.followup.send(_("🛠️ You are not authorized to use admin controls."), ephemeral=True, delete_after=NOTICE_STAYS_FOR)
                return

            # Apply spam protection
            from services.infrastructure.spam_protection_service import get_spam_protection_service
            spam_service = get_spam_protection_service()
            # Through the service instead of an attribute on the button - same
            # reason as in InfoDropdownButton. The user_id from :1782 stays; it
            # is needed further up for the permission check.
            if spam_service.is_enabled():
                try:
                    if spam_service.is_on_cooldown(interaction.user.id, "admin"):
                        remaining = spam_service.get_remaining_cooldown(interaction.user.id, "admin")
                        await interaction.followup.send(
                            _("⏰ Please wait {remaining:.1f} more seconds before using this button again.").format(
                                remaining=remaining
                            ),
                            ephemeral=True, delete_after=NOTICE_STAYS_FOR
                        )
                        return
                    spam_service.add_user_cooldown(interaction.user.id, "admin")
                except (RuntimeError, AttributeError, KeyError) as e:
                    logger.error(f"Spam protection error for admin button: {e}", exc_info=True)

            # SERVICE FIRST: Use ServerConfigService to get active containers
            server_config_service = get_server_config_service()
            all_servers = server_config_service.get_all_servers()

            # Containers and groups, from the one place that builds this list
            # (cogs/group_control.py): the other button asks it too.
            active_containers = controllable_entries(all_servers)

            if not active_containers:
                await interaction.followup.send(_("📦 No active containers found."), ephemeral=True, delete_after=NOTICE_STAYS_FOR)
                return

            # DEBUG, like the dropdown's loops since review E37: at INFO every
            # press wrote 2 + 2N lines (stage 4 review before v3.1.0, section 03).
            logger.debug(f"AdminButton: {len(active_containers)} containers BEFORE sorting:")
            for c in active_containers:
                order_val = c.get('order', 999)
                logger.debug(f"  - {c['display']}: order={order_val} (type={type(order_val).__name__})")

            # Sort containers by the 'order' field (same as Admin Overview)
            # Handle both int and string values from Web UI
            def get_sort_key(container):
                order = container.get('order', 999)
                if isinstance(order, str):
                    try:
                        return int(order)
                    except ValueError:
                        return 999
                return int(order) if order is not None else 999

            active_containers.sort(key=get_sort_key)

            # Log the sorted order for debugging
            logger.debug(f"AdminButton: Containers AFTER sorting:")
            for c in active_containers:
                logger.debug(f"  - {c['display']}: order={c.get('order', 999)}")

            # Create view with dropdown
            view = AdminContainerSelectView(self.cog, active_containers, interaction.channel.id,
                                            user_id=interaction.user.id)

            embed = discord.Embed(
                title="🛠️ " + _("Admin Control Panel"),
                description=_("Select a container to view its control panel:"),
                color=discord.Color.red()
            )

            # Send as ephemeral response (interaction was deferred above)
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)

            logger.info(f"Admin panel shown for user {interaction.user.name} in channel {self.channel_id}")

        except (discord.errors.DiscordException, RuntimeError, ValueError, KeyError) as e:
            logger.error(f"Error showing admin panel: {e}", exc_info=True)
            try:
                await interaction.followup.send(_("❌ An error occurred. Please try again."), ephemeral=True, delete_after=NOTICE_STAYS_FOR)
            except (discord.errors.DiscordException, RuntimeError):
                pass

class AdminContainerSelectView(PrivateView):
    """View with dropdown for selecting a container for admin control."""

    def __init__(self, cog_instance: 'DockerControlCog', containers: list, channel_id: int,
                 user_id: Optional[int] = None):
        super().__init__(timeout=180)  # 3 minutes timeout
        self.cog = cog_instance
        self.channel_id = channel_id

        # Offer only what the presser may actually use (review F4). This panel
        # is ephemeral - "only you can see this" - so it can differ per user,
        # unlike the shared status message above it.
        #
        # Only where the CHANNEL grants nothing: in a control channel everyone
        # who may write there may do everything (B1), so there is nothing to
        # narrow. Without a user id the list is left alone and the gap is said
        # out loud, rather than a caller silently losing their containers.
        if user_id is None:
            logger.warning("[ADMIN_DROPDOWN] No user id given - offering every container; "
                           "the buttons behind it still check")
        else:
            try:
                if not _channel_has_permission(channel_id, 'control', load_config()):
                    before = len(containers)
                    containers = [c for c in containers
                                  if _admin_may_control(user_id, c.get('docker_name') or c.get('name'))]
                    if len(containers) != before:
                        logger.info(f"[ADMIN_DROPDOWN] {len(containers)} of {before} containers "
                                    f"offered to user {user_id}")
            except (AttributeError, KeyError, OSError, RuntimeError, ValueError) as e:
                # A list that cannot be narrowed is not widened silently: the
                # buttons behind every entry check again when they are pressed.
                logger.error(f"[ADMIN_DROPDOWN] Could not narrow the list for {user_id}: {e}",
                             exc_info=True)

        # Add dropdown
        self.add_item(AdminContainerDropdown(cog_instance, containers, channel_id))

class AdminContainerDropdown(discord.ui.Select):
    """Dropdown for selecting a container for admin control."""

    def __init__(self, cog_instance: 'DockerControlCog', containers: list, channel_id: int,
                 page: int = 0):
        self.cog = cog_instance
        self.channel_id = channel_id
        self.page = page

        # CRITICAL: Re-sort containers here to ensure correct order
        # Sort by 'order' field from Web UI configuration

        # DEBUG level, not INFO: this writes one line PER CONTAINER, twice (once
        # here and once after sorting), every time the panel is opened. On a
        # seven-container install that is fourteen INFO lines for one click,
        # and the header calls itself "Debug" (review E37).
        logger.debug(f"AdminDropdown received {len(containers)} containers:")
        for c in containers:
            order_val = c.get('order', 999)
            logger.debug(f"  - {c['display']}: order={order_val} (type={type(order_val).__name__})")

        # Sort containers by order field (handles both int and string from Web UI)
        def get_order_key(container):
            order = container.get('order', 999)
            # Convert to int if it's a string from Web UI
            if isinstance(order, str):
                try:
                    return int(order)
                except ValueError:
                    return 999
            return int(order) if order is not None else 999

        sorted_containers = sorted(containers, key=get_order_key)
        self.containers = sorted_containers

        # Debug log the sorted order - see above.
        logger.debug("AdminDropdown after sorting:")
        for c in sorted_containers:
            logger.debug(f"  - {c['display']}: order={c.get('order', 999)}")

        # Create options from sorted containers, one page at a time (review E37)
        placeholder = _("Select a container to control...")
        shown, has_prev, has_next = _page_of(sorted_containers, page)
        before, after = _page_arrows(sorted_containers, page, has_prev, has_next)
        options = list(before)
        for container in shown:
            # Remove " Server" suffix for cleaner dropdown display
            display_label = container['display']
            if display_label.endswith(' Server'):
                display_label = display_label[:-7]

            # CRITICAL FIX: Discord sorts options alphabetically UNLESS they have emoji or description!
            # We add a minimal description to force Discord to keep our order
            option = discord.SelectOption(
                label=display_label,
                value=container['docker_name'],
                emoji=container.get('emoji'),   # a group is marked as one
                description=" "  # Single space - invisible but forces Discord to keep our order
            )
            options.append(option)
        options.extend(after)

        super().__init__(
            placeholder=_paged_placeholder(placeholder, sorted_containers, page,
                                           has_prev or has_next),
            options=options,
            min_values=1,
            max_values=1,
            custom_id="admin_container_select"
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle container selection and show control panel."""
        try:
            # Before the defer: turning the page edits the message itself, and
            # a deferred interaction can no longer answer with edit_message.
            if self.values[0] in (SELECT_PAGE_PREV, SELECT_PAGE_NEXT):
                await _turn_page(
                    self, interaction, self.containers,
                    lambda page: AdminContainerDropdown(
                        self.cog, self.containers, self.channel_id, page=page))
                return

            # IMPORTANT: Defer immediately to avoid interaction timeout (3 second limit)
            await interaction.response.defer()

            # Anyone who sees the admin overview can open this menu, so ask here who
            # is pressing it - the CURRENT channel permission or the CURRENT admin
            # list, the same rule and the same words as every other path (SPEC.md
            # B1, B2). The buttons of the panel ask again when they are pressed, so
            # nothing could actually be done without the right; what was missing was
            # the refusal at the door, and a panel that looks usable but is not
            # (review B27).
            # Own alias: further down this callback imports load_config locally,
            # which would make the module-level name local for the whole function.
            from services.config.config_service import load_config as load_config_now
            from .translation_manager import _ as translate
            config_now = load_config_now()
            if not (_get_cached_channel_permission(self.channel_id, 'control', config_now)
                    or _is_registered_admin(interaction.user.id)):
                # translate, not _: a few lines down this callback unpacks
                # "embed, view, _ = ...", which makes the translation function local
                # to the whole callback - calling _() here would raise.
                await interaction.followup.send(
                    translate("This action is not allowed in this channel."), ephemeral=True, delete_after=NOTICE_STAYS_FOR)
                return

            selected_container = self.values[0]

            # Find the container configuration
            # SERVICE FIRST: Use ServerConfigService to get container configuration
            server_config_service = get_server_config_service()

            # Get container configuration by docker_name
            container_config = server_config_service.get_server_by_docker_name(selected_container)

            # If not found, try searching all servers
            if not container_config:
                all_servers = server_config_service.get_all_servers()
                for server in all_servers:
                    if server.get('docker_name') == selected_container:
                        container_config = server
                        break

            # A group has no container configuration; it has its own.
            container_config = container_config or group_config_for(selected_container)

            if not container_config:
                await interaction.edit_original_response(
                    content=_("❌ Container configuration not found for '{name}'").format(
                        name=selected_container),
                    embed=None,
                    view=None
                )
                return

            # Generate control message for this container
            from services.config.config_service import load_config

            # Load configuration
            config = load_config()
            if not config:
                logger.error("[ADMIN_BTN] Configuration could not be loaded - "
                             "the admin panel cannot be built")
                await interaction.edit_original_response(
                    content=_("❌ An error occurred. Please try again."),
                    embed=None,
                    view=None
                )
                return

            display_name = container_config.get('name', selected_container)

            # Temporarily mark the container config for admin control
            container_config['_is_admin_control'] = True

            # Generate expanded control embed and view using the cog's method
            if hasattr(self.cog, '_generate_status_embed_and_view'):
                # NOT `_`: this function now calls the translation function, and
                # binding `_` anywhere in it makes `_` local for the WHOLE scope -
                # every _() before this line would raise UnboundLocalError and
                # every one after it would call a tuple element (review E34,
                # caught by test_the_translation_function_is_not_shadowed).
                # A container is asked about; a group is answered from its
                # members (cogs/group_control.py).
                embed = await admin_panel_embed(self.cog, self.channel_id, selected_container,
                                                container_config, config, display_name)
                is_running, status_known = await running_state_for(
                    self.cog, selected_container, container_config)

                control_view = admin_control_view(self.cog, container_config, is_running)

                # Clean up temporary marker after everything is done
                container_config.pop('_is_admin_control', None)

                await interaction.edit_original_response(embed=embed, view=control_view)
            else:
                # Fallback if method not available
                logger.error("[ADMIN_BTN] The cog has no _generate_status_embed_and_view - "
                             "the control panel cannot be built")
                await interaction.edit_original_response(
                    content=_("❌ An error occurred. Please try again."),
                    embed=None,
                    view=None
                )
                return

            logger.info(f"Admin control panel shown for {selected_container} to user {interaction.user.name}")

        except (RuntimeError, ValueError, KeyError) as e:
            logger.error(f"Error handling admin container selection: {e}", exc_info=True)
            try:
                # Since we deferred at the start, response is always done, so edit original
                await interaction.edit_original_response(
                    content=_("❌ An error occurred. Please try again."),
                    embed=None,
                    view=None
                )
            except (discord.errors.DiscordException, RuntimeError):
                pass
