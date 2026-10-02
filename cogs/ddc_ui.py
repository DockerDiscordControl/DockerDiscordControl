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

import functools
from typing import Optional

import discord

from utils.logging_utils import get_module_logger

from .control_helpers import is_private_panel_message
from .translation_manager import _

logger = get_module_logger('ddc_ui')

# How long a private message stays before Discord removes it for us.
#
# WHY THESE ARE NAMES. An ephemeral message sits in the channel until its
# reader dismisses it, one click each, and DDC sends 173 one-off notices
# nobody ever needs twice - a cooldown, a refusal, a failure. The operator had
# to clear every one by hand. A number typed at 173 call sites cannot be
# changed later; a name can.
NOTICE_STAYS_FOR = 15     # a refusal or an error: long enough to read
PROGRESS_STAYS_FOR = 1    # "Refreshing..." - the real answer replaces it at once
# A private panel whose ✕ would stand alone on a row closes itself instead
# (operator, 2026-09-27: "the close button should never stand alone on a row").
AUTO_CLOSE_SECONDS = 60
# Discord lets DDC delete a private message only within fifteen minutes of the
# answer that made it, so a private panel closes well inside that: five minutes
# without use, ten at the most (operator, 2026-10-02)
PRIVATE_PANEL_SECONDS = 300
MAX_PRIVATE_SECONDS = 600
CLOSE_CUSTOM_ID = "ddc_close_panel"


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
            await interaction.followup.send(message, ephemeral=True, delete_after=NOTICE_STAYS_FOR)
        else:
            await interaction.response.send_message(message, ephemeral=True, delete_after=NOTICE_STAYS_FOR)
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


class CloseButton(discord.ui.Button):
    """Takes a private panel away, in the operator's own words.

    THE OPERATOR (2026-09-25): "I don't know whether everyone understands
    'Dismiss message'." That phrase is Discord's, it is small, grey, and until
    a view expires it is the only way out of an ephemeral message.

    IT REFUSES ON A PUBLIC MESSAGE. He asked for this explicitly: the status
    and control channel overviews must never carry it. Two things stop that -
    the button is only added where a panel is private, and pressing it asks
    the message's own ephemeral flag before deleting anything. The first is
    the rule; the second is what survives somebody forgetting it.
    """

    def __init__(self, row: Optional[int] = None):
        # A SYMBOL AS THE LABEL, ON THE SAME ROW AS THE ACTIONS.
        #
        # THE ROW: he asked for "only the X, behind the Info button" once he
        # saw it - the word made the panel two rows tall and read as a fourth
        # kind of thing beside three controls that say what they do with an
        # icon alone.
        #
        # THE SYMBOL, and not an emoji: Discord draws these with its own
        # emoji set, which colours \u25b6\ufe0f \u23f9\ufe0f \ud83d\udd04 \u2139\ufe0f blue and \u2716\ufe0f dark grey, so the X
        # came out washed out beside its blue neighbours and he asked whether
        # a blue one existed. It does not - \u274c is red, \u274e is green - and a
        # LABEL is drawn in the button's own white instead. U+2715 has no
        # emoji form at all, which is exactly why it stays text. It is a
        # symbol rather than a word, so it needs no catalogue key.
        super().__init__(style=discord.ButtonStyle.secondary, label="\u2715",
                         row=row, custom_id=CLOSE_CUSTOM_ID)

    async def callback(self, interaction: discord.Interaction) -> None:
        # ANSWER FIRST. Discord gives three seconds, and deleting a message is
        # not an answer: the first version of this button deleted and said
        # nothing, so the operator got "DDC did not respond in time" and the
        # panel stayed. invisible=True acknowledges without a "thinking" state.
        try:
            await interaction.response.defer(invisible=True)
        except (discord.InteractionResponded, discord.HTTPException) as error:
            logger.debug("Close button could not acknowledge the press: %s", error)

        message = getattr(interaction, "message", None)
        if message is None or not is_private_panel_message(message):
            logger.warning("Close button pressed on a message that is not private - ignored")
            return

        # NOT message.delete(). That is DELETE /channels/{id}/messages/{id},
        # and an ephemeral message is not in a channel - Discord answers 404.
        # The response of a component interaction IS the message the component
        # sits on, so this is the route that reaches it.
        try:
            await interaction.delete_original_response()
        except (discord.NotFound, discord.Forbidden, discord.HTTPException) as error:
            # Already gone, or past Discord's fifteen-minute interaction token.
            logger.debug("Could not close a panel: %s", error)


class DDCView(discord.ui.View):
    """A view whose failing buttons answer the user, and which clears up after itself."""

    # OPEN PRIVATE PANELS ARE WRITTEN DOWN (services/discord/private_panels.py), so
    # a restart of DDC - which loses every timeout - can still delete them while
    # their token lives (operator, 2026-10-02). py-cord tells a view where it went
    # in one of two ways: a followup sets view.message, an answer sets view.parent.

    @property
    def message(self):
        return discord.ui.View.message.fget(self)

    @message.setter
    def message(self, value) -> None:
        discord.ui.View.message.fset(self, value)
        if value is None or not self.timeout or not is_private_panel_message(value):
            return
        state = getattr(value, "_state", None)
        webhook = getattr(state, "_webhook", None)
        interaction = getattr(state, "_interaction", None)
        from services.discord.private_panels import remember
        if webhook is not None:
            remember(self.id, getattr(webhook, "id", None), getattr(webhook, "token", None), value.id)
        elif interaction is not None:
            remember(self.id, getattr(interaction, "application_id", None),
                     getattr(interaction, "token", None), "@original")

    @property
    def parent(self):
        return self.__dict__.get("_ddc_parent")

    @parent.setter
    def parent(self, value) -> None:
        self.__dict__["_ddc_parent"] = value
        if value is not None and self.timeout and isinstance(self, PrivateView):
            from services.discord.private_panels import remember
            remember(self.id, getattr(value, "application_id", None),
                     getattr(value, "token", None), "@original")

    def _dispatch_item(self, item, interaction):
        # THE MESSAGE THE PANEL WAS SENT WITH, kept before py-cord replaces it.
        # On every press py-cord sets view.message = interaction.message, a plain
        # Message, whose delete() is the channel route - 404 for an ephemeral
        # message - so every panel that had been used stayed after its timeout.
        # The WebhookMessage DDC stored deletes through the interaction's own
        # route (stage 4 review before v3.1.0, section 38).
        sent = getattr(self, "message", None)
        if (isinstance(sent, (discord.WebhookMessage, discord.InteractionMessage))
                and getattr(self, "_sent_message", None) is None):
            self._sent_message = sent
        return super()._dispatch_item(item, interaction)

    async def _scheduled_task(self, item, interaction):
        await super()._scheduled_task(item, interaction)
        await self._remember_a_deleter(interaction)

    async def _remember_a_deleter(self, interaction) -> None:
        """Keep a press whose original response IS this private panel, to delete it with.

        Each press starts the timeout again, but the message the panel was sent
        with carries a token that dies fifteen minutes after the FIRST answer: a
        panel used for a while timed out after it and stayed (operator's
        question, 2026-10-02). A press answered by a deferred update or an edit
        has the panel as its original response, and its token is fresh. A press
        answered with a new message or a modal does not - asked, not guessed:
        py-cord does not keep the response type.
        """
        panel = getattr(interaction, "message", None)
        if panel is None or not self.timeout or not is_private_panel_message(panel):
            return
        try:
            original = await interaction.original_response()
        except (discord.NotFound, discord.Forbidden, discord.HTTPException,
                discord.ClientException, AttributeError) as error:
            logger.debug("No deleter for a private panel from this press: %s", error)
            return
        if getattr(original, "id", None) == panel.id:
            self._deleter = interaction
            from services.discord.private_panels import remember
            remember(self.id, getattr(interaction, "application_id", None),
                     getattr(interaction, "token", None), "@original")

    async def on_timeout(self) -> None:
        """Take a finished private panel away instead of leaving a dead one.

        py-cord stops listening to a view once its timeout passes, but the
        message stays: a dropdown that has quietly stopped working, sitting
        there looking perfectly usable, and removable only by hand. The
        operator had to dismiss every one of them.

        ONLY A PRIVATE ONE. A timeout must never remove a message everybody
        can see. The public overview and the Mech views are persistent
        (timeout=None) so this cannot fire for them - but that is a property
        of thirteen separate constructor calls, and one of them only has to
        change. The message itself is asked instead, by the same flag the
        admin-panel detection reads.
        """
        message = getattr(self, "_sent_message", None) or getattr(self, "message", None)
        if message is None:
            # Sent as the answer itself (response.send_message): py-cord gives such a
            # view no message, only view.parent, and an unpressed panel was never
            # deleted (2026-10-02). The answer to that interaction IS the panel; only
            # a PrivateView's - nothing here says whether another answer was private.
            parent = getattr(self, "parent", None)
            if isinstance(self, PrivateView) and parent is not None:
                try:
                    await parent.delete_original_response()
                except (discord.NotFound, discord.Forbidden, discord.HTTPException) as error:
                    logger.debug("Could not remove a timed-out panel: %s", error)
                self._forget_panel()
            return
        if not is_private_panel_message(message):
            return
        # A MESSAGE THAT HAS MOVED ON. The container picker becomes the
        # container's admin panel by editing the same message; py-cord then
        # files the new view under that message id. This view's timer runs on
        # regardless, and deleted whatever the message showed by then.
        synced = getattr(getattr(getattr(message, "_state", None), "_view_store", None),
                         "_synced_message_views", None)
        if isinstance(synced, dict) and synced.get(message.id, self) is not self:
            return

        deleter = getattr(self, "_deleter", None)
        try:
            if deleter is not None:
                # The last press that answered on this panel: its token is fresh
                await deleter.delete_original_response()
            else:
                await message.delete()
        except (discord.NotFound, discord.Forbidden, discord.HTTPException) as error:
            # Already dismissed by hand, or past Discord's fifteen-minute
            # interaction token. Neither is worth an operator's attention.
            logger.debug("Could not remove a timed-out panel: %s", error)
        self._forget_panel()

    def _forget_panel(self) -> None:
        """Gone (or no longer deletable): a restart has nothing to do for it."""
        from services.discord.private_panels import forget
        forget(self.id)

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


def _alone_on_its_row(view) -> bool:
    """Whether the close button is the only component on its rendered row."""
    for row in view.to_components():
        ids = [component.get("custom_id") for component in row.get("components", [])]
        if CLOSE_CUSTOM_ID in ids:
            return len(ids) == 1
    return False


class PrivateView(DDCView):
    """A view only one person can see, which therefore carries its own way out.

    THE OPERATOR (2026-09-25): "everywhere there are buttons, the closing X
    has to be there." Twelve views were delivered only as ephemeral messages
    and offered none - the mech details, the gallery and its stories, the
    container info panels, the task views, the password prompt.

    WHY A TYPE AND NOT TWELVE CALLS. Six of them live in cogs/control_ui.py,
    which is on the size ceiling and may not grow
    (tests/spec/test_no_file_or_class_grows_past_its_ceiling.py). That ceiling
    exists to push mechanism out of an oversized file, so this is it doing its
    job: "a panel only you can see" became a KIND of view, and the way out
    comes with the kind. Each of the eleven says so by its base class.

    WHY IT IS APPENDED AFTER ``__init__`` AND NOT INSIDE IT: a subclass adds
    its items AFTER calling ``super().__init__()``, and he asked for the X to
    sit behind the others. Wrapping the subclass's ``__init__`` puts it last
    and does so AT CONSTRUCTION, which matters because ``bot.add_view()``
    reads the children to route presses on messages that outlived a restart.

    A VIEW THAT REBUILDS ITS ITEMS cannot use this: LiveLogView clears and
    rebuilds on every refresh, so it adds the button itself and stays a plain
    DDCView.
    """

    # A panel that needs longer than the minute to be read and filled in keeps
    # the timeout it asked for; its ✕ still does not stand alone. Only the
    # confirmation of a new task, with its two dropdowns (operator, 2026-09-29).
    KEEPS_ITS_TIMEOUT = False

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        built = cls.__init__

        @functools.wraps(built)
        def __init__(self, *args, **rest):
            built(self, *args, **rest)
            # Idempotent: a subclass of a subclass wraps twice, and a view
            # that adds its own close button keeps the one it chose.
            if not any(isinstance(item, CloseButton) for item in self.children):
                self.add_item(CloseButton())
                # NEVER ALONE ON A ROW (operator, 2026-09-27). A select takes a
                # whole row, and a sixth button starts a new one; there the ✕
                # goes, and the panel closes itself after a minute instead.
                # Read from the layout Discord will get, not guessed.
                if _alone_on_its_row(self):
                    self.remove_item(self.children[-1])
                    if not self.KEEPS_ITS_TIMEOUT:
                        self.timeout = AUTO_CLOSE_SECONDS

        cls.__init__ = __init__
