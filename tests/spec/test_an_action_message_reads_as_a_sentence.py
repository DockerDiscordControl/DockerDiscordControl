# -*- coding: utf-8 -*-
"""An action message names the action on its own line, never inside a sentence.

THE FINDING (English review, 2026-09-27): three messages put the button label
into a sentence as "{action_process_text}" = "(Restart)":

    Server **Valheim** could not be processed (Restart).
    **Valheim** was (Restart) - only this panel could not be updated.
    **Valheim** was sent the (Restart) and Docker accepted it, ...

The label is translated as a label ("Neu starten", "Redémarrer"), so no
language could ever make a sentence of it. The action now heads the message -
"**Valheim** · Restart" - and the sentence below it needs no action word.

HOW THIS TEST CAN FAIL: it renders all three for a restart and checks that no
"(Restart)" is left, that the name and the action head the text, and that the
sentence is there.

COUNTER-CHECK (2026-09-27): red before on all three.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock


def _button():
    from cogs.control_ui import ActionButton

    button = ActionButton.__new__(ActionButton)
    button.display_name = "Valheim"
    button.action = "restart"
    return button


def _check(text, sentence):
    assert "(Restart)" not in text, f"the label is still in a sentence: {text!r}"
    assert text.startswith("**Valheim** · Restart\n"), text
    assert sentence in text, text


def test_a_failed_action():
    _check(_button()._failed_embed().description, "could not be carried out")


def test_a_panel_that_could_not_be_refreshed():
    interaction = MagicMock()
    interaction.edit_original_response = AsyncMock()
    asyncio.run(_button()._say_the_panel_is_stale(interaction, action_done=True))
    embed = interaction.edit_original_response.await_args.kwargs["embed"]
    _check(embed.description, "only this panel could not be updated")


def test_an_action_not_confirmed_yet():
    from cogs.action_effect import not_confirmed_embed

    _check(not_confirmed_embed("Valheim", "restart").description, "Docker accepted the command")
