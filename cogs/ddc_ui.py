# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Shared bases for every Discord view and modal DDC shows.

They exist for one reason: **an interaction that fails must say so.**

Measured in the shipped py-cord:

===========================  ================================================
``ui/view.py:428``           ``View._scheduled_task`` wraps the item callback
                             in ``except Exception`` and calls ``on_error``
``ui/view.py:393``           the default ``View.on_error`` prints the
                             traceback to ``sys.stderr`` and answers the
                             interaction **not at all**
``ui/modal.py:242``          ``Modal.on_error`` does the same
===========================  ================================================

DDC defined neither, so pressing Start, Stop, Restart, a mech button, Live
Logs or a task button and hitting an error left the interaction spinning until
Discord gave up with "This interaction failed" - and nothing reached DDC's log,
because a bare ``print()`` to stderr is not the logger (review E24).

Review E14 fixed exactly this for slash commands, which travel a different
event. This is the larger half: DDC has eight slash commands and thirty views
and modals. ``/serverstatus`` posts a panel, and everything after that is a
button.

``tests/spec/test_a_button_that_fails_says_so.py`` walks the source tree and
fails if any class still inherits ``discord.ui.View`` or ``discord.ui.Modal``
directly, so one added tomorrow is covered today.
"""

from __future__ import annotations

import discord

from utils.logging_utils import get_module_logger

from .translation_manager import _

logger = get_module_logger('ddc_ui')


async def _answer(interaction: discord.Interaction) -> None:
    """Tell the user their click failed, whatever state the interaction is in.

    Generic on purpose. An arbitrary exception carries whatever it happens to
    carry - a path, a URL with a query string, the contents of a config value -
    and this message goes into a Discord channel. The user needs to know the
    click failed; the reason belongs in the log. Same rule as review E14.
    """
    message = _("❌ An error occurred. Please try again.")
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except (discord.HTTPException, discord.ClientException) as e:
        # Already answered, expired, or Discord refused. Nothing left to do and
        # nothing wrong - the failure itself is logged by the caller.
        logger.debug("Could not deliver the failure notice: %s: %s",
                     type(e).__name__, e)


def _name_of(item) -> str:
    """Something an operator can match against what they clicked."""
    return (getattr(item, "custom_id", None)
            or getattr(item, "label", None)
            or type(item).__name__)


class DDCView(discord.ui.View):
    """A view whose failing buttons answer the user and reach the DDC log."""

    async def on_error(self, error: Exception, item, interaction: discord.Interaction) -> None:
        logger.error("Button '%s' in %s failed (%s: %s)",
                     _name_of(item), type(self).__name__,
                     type(error).__name__, error, exc_info=error)
        await _answer(interaction)


class DDCModal(discord.ui.Modal):
    """A modal whose failing submit answers the user and reaches the DDC log."""

    async def on_error(self, error: Exception, interaction: discord.Interaction) -> None:
        logger.error("Modal %s failed (%s: %s)",
                     type(self).__name__, type(error).__name__, error,
                     exc_info=error)
        await _answer(interaction)
