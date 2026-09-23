# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Clearing away a donation panel that a restart left behind.

/donate posts its panel non-ephemerally and gives it about fifteen minutes:
DonationView times out at 890 s and deletes its own message. The view and its
timer live in memory, the message does not - so a restart inside that window
(a rebuild takes the bot offline for 60-90 seconds) leaves the panel standing
with a "Broadcast Donation" button that looks live and does nothing. Pressing
it writes nothing to the log, because from the bot's side nothing happened.

Operator decision (2026-09-23): clear it away here rather than make the panel
persistent, so the panel stays what it is - something that appears, is used
and disappears - instead of standing in the channel until somebody removes it.
"""

from __future__ import annotations

import discord

from ..startup_context import StartupContext, as_step


@as_step
async def remove_stale_donation_panels_step(context: StartupContext) -> None:
    logger = context.logger
    cog = context.bot.get_cog("DockerControlCog")
    if not cog or not getattr(cog, "channel_server_message_ids", None):
        # No cog means the extensions did not load, which is already reported
        # where it happened; a second failure here would only bury it.
        return

    removed = 0
    for channel_id, tracked in list(cog.channel_server_message_ids.items()):
        message_id = tracked.get("donation")
        if not message_id:
            continue
        channel = context.bot.get_channel(channel_id)
        if channel is None:
            # The bot cannot see the channel right now - it may be back later,
            # so the id stays. Dropping it would strand the panel for good.
            logger.info("Donation panel %s stays: channel %s is not reachable",
                        message_id, channel_id)
            continue
        try:
            await channel.get_partial_message(message_id).delete()
            logger.info("Removed the donation panel %s left in channel %s by a restart",
                        message_id, channel_id)
            tracked.pop("donation", None)
            removed += 1
        except discord.NotFound:
            # The everyday case: the view deleted it itself before the restart.
            tracked.pop("donation", None)
        except (discord.Forbidden, discord.HTTPException) as e:
            # A refusal is not a delete: keep the id so the next start tries again.
            logger.warning("Donation panel %s in channel %s could not be removed: %s",
                           message_id, channel_id, e)

    try:
        cog._persist_tracked_message_ids()
    except (AttributeError, OSError, RuntimeError) as e:
        # Worth a line, not worth stopping the startup: the ids are only used
        # to clean up, and the next successful save fixes the file.
        logger.warning("Could not write back the message ids after the cleanup: %s", e)
    if removed:
        logger.info("Cleared %d donation panel(s) left behind by the restart", removed)
