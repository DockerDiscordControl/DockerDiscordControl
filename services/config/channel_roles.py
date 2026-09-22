# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Which configured channels play which role - decided in one place."""

import logging
from typing import Any, Dict, List

logger = logging.getLogger("ddc.channel_roles")


def control_channel_ids(config: Dict[str, Any]) -> List[int]:
    """The channels with the control permission, in both config formats.

    Used by the update notice and by the container watchdog's default notice
    channel (tests/spec/test_control_channels_are_found_in_one_place.py).
    """
    channels: List[int] = []
    # New format: channel_permissions
    for channel_id, perms in (config.get('channel_permissions') or {}).items():
        if (perms or {}).get('commands', {}).get('control', False):
            try:
                channels.append(int(channel_id))
            except ValueError:
                logger.debug(f"Invalid channel ID: {channel_id}")
    # Old format fallback: channels array
    if not channels:
        for channel_config in config.get('channels', []) or []:
            if 'control' in channel_config.get('permissions', []):
                try:
                    channels.append(int(channel_config['channel_id']))
                except (ValueError, KeyError):
                    pass
    return channels
