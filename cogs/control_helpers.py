# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #

import discord
from typing import List, Union
from services.config.config_service import load_config
from .translation_manager import _ # Import the translation function
from utils.time_utils import format_datetime_with_timezone, get_datetime_imports # Import time helper
from utils.logging_utils import get_module_logger
from utils.config_cache import get_cached_guild_id, get_cached_servers

# Central datetime imports
datetime, timedelta, timezone, time = get_datetime_imports()

# Import app_commands using central utility
from utils.app_commands_helper import get_app_commands
app_commands = get_app_commands()

# Logger with central utility
logger = get_module_logger('control_helpers')

def get_guild_id() -> Union[List[int], None]:
    """Loads the guild ID from the configuration."""
    guild_id = get_cached_guild_id()  # Performance optimization: use cache
    if guild_id:
        return [guild_id]
    # If no or an invalid guild_id is in the config,
    # None is returned, which means the command is global.
    logger.warning("No valid guild_id found in config. Commands will be registered globally.")
    return None

# Updated function for Discord Autocomplete
async def container_select(original_ctx, original_current):
    """ Returns a list of configured Docker containers for autocomplete.
    This function handles both discord.py and PyCord style autocomplete contexts.
    Always returns a simple list of strings to avoid serialization issues.
    """
    logger.info(f"[container_select] ENTER. original_ctx type: {type(original_ctx)}, original_current type: {type(original_current)}")

    search_text = ""
    # Based on logs: original_ctx is None, original_current is AutocompleteContext for schedule commands.
    if hasattr(original_current, 'value') and not isinstance(original_current, str):
        logger.info(f"  Treating original_current as AutocompleteContext. Accessing original_current.value.")
        try:
            search_text = original_current.value or ""
            logger.info(f"  Search text from original_current.value: '{search_text}'")
        except (RuntimeError) as e:
            logger.error(f"  Error accessing original_current.value: {e}. Defaulting search_text.", exc_info=True)
            search_text = ""
    elif hasattr(original_ctx, 'value') and not isinstance(original_ctx, str):
        # Fallback if original_ctx is an AutocompleteContext (e.g. PyCord standard)
        logger.info(f"  Treating original_ctx as AutocompleteContext. Accessing original_ctx.value.")
        try:
            search_text = original_ctx.value or ""
            logger.info(f"  Search text from original_ctx.value: '{search_text}'")
        except (RuntimeError, discord.Forbidden, discord.HTTPException, discord.NotFound) as e:
            logger.error(f"  Error accessing original_ctx.value: {e}. Defaulting search_text.", exc_info=True)
            search_text = ""
    elif isinstance(original_current, str):
        # Standard discord.py: original_current is the string value, original_ctx is Interaction
        logger.info(f"  Treating original_current as string value: '{original_current}'")
        search_text = original_current
    else:
        logger.warning(f"  Could not reliably determine search_text. Defaulting to empty. original_ctx type: {type(original_ctx)}, original_current type: {type(original_current)}")
        search_text = ""

    logger.info(f"[container_select] Determined search_text: '{search_text}'")

    servers = get_cached_servers()  # Performance optimization: use cache instead of load_config()
    if not servers:
        logger.warning("[container_select] No servers found in configuration (or servers list is empty). Returning empty list.")
        # return [] # If servers is empty, initial_container_names will be empty naturally

    initial_container_names = [server.get('docker_name') for server in servers if server.get('docker_name')]
    logger.info(f"[container_select] Initial unfiltered container names from config: {initial_container_names}")

    container_names_to_return = []
    if not search_text:
        logger.debug("[container_select] No search_text, will return all initial_container_names.")
        container_names_to_return = initial_container_names
    else:
        search_text_lower = search_text.lower()
        logger.debug(f"[container_select] Filtering with search_text_lower: '{search_text_lower}'")
        container_names_to_return = [name for name in initial_container_names if search_text_lower in name.lower()]
        logger.info(f"[container_select] Filtered container names: {container_names_to_return}")

    logger.info(f"[container_select] EXIT. Returning {len(container_names_to_return)} items: {container_names_to_return[:25]}")
    return container_names_to_return[:25]

def _channel_has_permission(channel_id: int, permission_key: str, config: dict = None) -> bool:
    """Checks if a channel has a specific permission."""
    if config is None:
        config = load_config()  # Performance optimization: use cache if no config provided

    channel_permissions = config.get('channel_permissions', {})
    channel_config = channel_permissions.get(str(channel_id))

    if channel_config:
        # If the channel has an explicit configuration
        return channel_config.get('commands', {}).get(permission_key, False)
    else:
        # If no specific configuration, use default
        default_permissions = config.get('default_channel_permissions', {})
        return default_permissions.get('commands', {}).get(permission_key, False)

def _is_registered_admin(user_id) -> bool:
    """True if ``user_id`` is in the CURRENT admin list (``admins.json``, /addadmin).

    SPEC.md B2: the admin list exists so that admins may act where the channel
    alone permits nothing - the status channels. The Z5 fix of 2026-09-16/17
    removed the "Admin Control" message title as a permission and put nothing
    in its place, so admins were refused in status channels (operator's report
    of 2026-09-19). The list is read at the moment of the press, never taken
    from a message. A failing lookup counts as "not an admin".
    """
    try:
        from services.admin.admin_service import get_admin_service
        return bool(get_admin_service().is_user_admin(user_id))
    except (ImportError, OSError, ValueError, RuntimeError) as e:
        logger.error(f"Admin list could not be read for user {user_id}: {e}", exc_info=True)
        return False

def _admin_may_control(user_id, docker_name: str) -> bool:
    """B2, narrowed to the containers this admin was assigned (review F2).

    The same rule as ``_is_registered_admin`` for an admin with no assignment -
    they keep every container, which is the upgrade default and must stay that
    way. An assigned admin passes only for their own containers.

    This is the B2 branch ALONE. The channel branch (B1) is asked before it and
    is not narrowed by anything: whoever may write in a control channel still
    does everything there. Assignments only bite where the channel permits
    nothing, which is the status channels they were asked for.

    A lookup that fails counts as "not allowed", like its neighbour above.
    """
    try:
        from services.admin.admin_service import get_admin_service
        return bool(get_admin_service().may_control(user_id, docker_name))
    except (ImportError, OSError, ValueError, RuntimeError) as e:
        logger.error(f"Admin assignment could not be read for user {user_id}: {e}",
                     exc_info=True)
        return False


def _admin_may_control_task(user_id, task_id: str) -> bool:
    """The same rule for a scheduled task, via the container it acts on.

    A task button knows its task, not its container, so the container has to be
    looked up - but only for an admin who HAS an assignment. For everybody else
    the answer cannot depend on it, and doing the lookup anyway would let a
    missing task refuse an unscoped admin who is allowed today.

    A task that cannot be found while the admin IS assigned counts as "not
    allowed": there is no way to tell whether it is one of theirs.
    """
    try:
        from services.admin.admin_service import get_admin_service
        service = get_admin_service()
        containers = service.get_admin_containers(user_id)
        if containers is None:
            return bool(service.is_user_admin(user_id))
        if not containers:
            return False

        from services.scheduling.scheduler import find_task_by_id
        task = find_task_by_id(task_id)
        container_name = getattr(task, 'container_name', None)
        if not container_name:
            logger.warning(f"Task {task_id} has no container - refusing the assigned "
                           f"admin {user_id}, there is no way to tell whose it is")
            return False
        return str(container_name) in containers
    except (ImportError, OSError, ValueError, RuntimeError, AttributeError) as e:
        logger.error(f"Admin assignment could not be read for user {user_id}: {e}",
                     exc_info=True)
        return False


def _get_pending_embed(display_name: str) -> discord.Embed:
    """Generates a standardized embed for the pending status in the box design."""
    # --- Start: Adjusted box formatting for Pending --- #
    config = load_config()  # Performance optimization: use cache instead of load_config()
    language = config.get('language', 'de') # Needed for translation context
    status_text = _("Pending...") # Use translated text
    current_emoji = "⏳"
    BOX_WIDTH = 28

    header_text = f"── {display_name} "
    max_name_len = BOX_WIDTH - 4 # Account for ┌──  ──┐
    if len(header_text) > max_name_len:
         header_text = header_text[:max_name_len-1] + "… " # Truncate name

    padding_width = max(1, BOX_WIDTH - 1 - len(header_text))
    header_line = f"┌{header_text}{'─' * padding_width}"
    footer_line = f"└{'─' * (BOX_WIDTH - 1)}"

    description = f"```\n{header_line}\n"
    description += f"│ {current_emoji} {status_text}\n"
    description += f"{footer_line}\n"
    description += f"```"

    embed = discord.Embed(
        description="", # Initialize description as empty
        color=discord.Color.gold() # Yellow
    )

    # Add footer similar to the normal status message
    now_footer = datetime.now(timezone.utc)
    last_update_text = _("Pending since")
    # Get timezone from config (format_datetime_with_timezone will handle fallbacks)
    current_time = format_datetime_with_timezone(now_footer, config.get('timezone'), time_only=True)

    # Insert timestamp above the code block
    timestamp_line = f"{last_update_text}: {current_time}"
    embed.description = f"{timestamp_line}\n{description}"

    # Adjusted footer: Only the URL
    embed.set_footer(text=f"https://ddc.bot")
    # --- End: Adjusted box formatting for Pending --- #
    return embed


def validate_custom_address(address: str) -> bool:
    """Validate custom IP/hostname format for security.

    Stood twice, character for character, in control_ui.py and
    status_info_integration.py. A security check that exists twice gets
    corrected once - and the same shape caused a real Z5 break today: the task
    delete button existed twice and only one copy checked the channel
    permission. See docs/quality/STAGE0_INVENTORY.md section 7.
    """
    import re

    # Limit length to prevent abuse
    if not isinstance(address, str) or len(address) > 255:
        return False

    # Split the port off FIRST, so the host is judged by the same rule whether
    # or not one is attached. It used to be the other way round: the IP pattern
    # below had no port group, so an address WITH a port never matched it and
    # fell through to the hostname pattern - which does not look at numbers at
    # all. 999.999.999.999 was refused and 999.999.999.999:80 was accepted
    # (review D28).
    host = address
    if ':' in address:
        host, _, port = address.rpartition(':')
        if not validate_custom_port(port):
            return False

    # Allow IPs
    ip_pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
    if re.match(ip_pattern, host):
        # Validate IP octets
        return all(int(octet) <= 255 for octet in host.split('.'))

    # Allow hostnames
    hostname_pattern = r'^[a-zA-Z0-9.-]+$'
    if re.match(hostname_pattern, host):
        # Additional validation: no double dots, no leading/trailing dots
        if '..' in host or host.startswith('.') or host.endswith('.'):
            return False
        return True

    return False


def validate_custom_port(port: str) -> bool:
    """Whether a port is a port - the value, not the number of digits.

    The pattern this replaces read ``[0-9]{1,5}``, which counts digits, so
    99999 and 0 came through. Both callers of validate_custom_address append
    the separate ``custom_port`` field to the address they show with nothing
    but ``str.isdigit()`` in front of it, which is the same hole one line
    further down - so the rule lives here, once, and both use it (review D28).
    """
    if not isinstance(port, str) or not port.isdigit():
        return False
    return 1 <= int(port) <= 65535
