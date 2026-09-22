# -*- coding: utf-8 -*-
"""The cooldown refusal of the task delete button must be translated.

NO ``@covers`` marker: that would be a new guarantee, and those are the
operator's decision.

THE FINDING. ``TaskDeleteButton.callback`` (``control_ui.py:1261``) refuses with
an f-string WITHOUT ``_()``: "Please wait ... before deleting another task."
On a German (French, Japanese ...) server this one refusal appears in English.
Measured: it is the only untranslated cooldown refusal under cogs/.

THE FIX follows the house pattern from SPEC.md B10: the existing entry that
is actually translated in the catalogs,
"⏰ Please wait {remaining:.1f} more seconds before using this button again."
(de: "Bitte warten Sie noch ..."). A new entry "... deleting another task"
would need 39 translations that I cannot honestly invent - it would be an
English placeholder everywhere except en.json and would only have moved the
finding. The wording becomes more general as a result; that is the price.

HOW IT IS CHECKED HERE: ``_`` in the module is replaced by a marker. Only
a text that went through ``_()`` carries it. This checks the PATH, not a
particular language - the catalog itself is guarded by the parity contracts.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cogs.control_ui import TaskDeleteButton
from services.infrastructure.spam_protection_service import SpamProtectionService

SPAM_PATH = "services.infrastructure.spam_protection_service.get_spam_protection_service"
USER = 8844


def _marked(text):
    return f"«{text}»"


@pytest.mark.asyncio
async def test_the_refusal_goes_through_the_translation(tmp_path):
    service = SpamProtectionService(config_dir=str(tmp_path))
    service.add_user_cooldown(USER, "task_delete")
    interaction = MagicMock()
    interaction.user.id = USER
    interaction.response.send_message = AsyncMock()
    button = TaskDeleteButton(MagicMock(), "t1", "Task", 0)

    with patch(SPAM_PATH, return_value=service), patch("cogs.control_ui._", _marked):
        await button.callback(interaction)

    interaction.response.send_message.assert_awaited_once()
    message = interaction.response.send_message.await_args.args[0]
    # .format() fills the placeholder in the marked text too - so the start
    # and end of the marker together with the catalog wording are checked.
    assert message.startswith("«⏰ Please wait ") and message.endswith(
        " more seconds before using this button again.»"
    ), f"The refusal did not go through _() with the catalog entry: {message!r}"
    assert interaction.response.send_message.await_args.kwargs.get("ephemeral") is True
