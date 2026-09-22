# -*- coding: utf-8 -*-
"""The admin overview's container menu asks who is pressing it.

No ``@covers`` marker: a finding, not a guarantee.

THE FINDING (stage 4 review, stage B, section 03 F1, re-checked 2026-09-20):
``AdminContainerDropdown.callback`` opens a container control panel without
looking at anybody's rights - it hands ``ControlView`` a hardcoded
``channel_has_control_permission=True`` with the comment "Admin always has
control". Anyone who can see the admin overview message can pick a container
from that menu.

What the report feared is NOT the case: every button of that panel asks
again when it is pressed - the CURRENT channel permission or the CURRENT
admin list (SPEC.md Z5, B2) - so a bystander in a status channel gets
"This action is not allowed in this channel." and nothing happens. The
``_is_admin_control`` marker written onto the config dict decides display
only; nothing reads it as a right.

What remains is that this one path lets someone open a panel they may not
use, while every sibling path (the task buttons, the info button) refuses at
the door. The rule is the operator's: in a control channel everyone may act,
in a status channel only a registered admin (SPEC.md B1, B2) - so the menu
refuses the same way, with the same words.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cogs.control_ui import AdminContainerDropdown

CONTAINER = {"docker_name": "vrising", "name": "V-Rising", "allowed_actions": ["start"]}
REFUSAL = "This action is not allowed in this channel."


def _dropdown(user_id=4711):
    cog = MagicMock()
    # The real constructor: Select.values only answers on a properly built component.
    dropdown = AdminContainerDropdown(
        cog, [{"display": "V-Rising", "docker_name": "vrising", "order": 1}], channel_id=99)
    interaction = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.followup.send = AsyncMock()
    interaction.edit_original_response = AsyncMock()
    interaction.user = SimpleNamespace(id=user_id, name="someone")
    interaction.channel = SimpleNamespace(id=99)
    dropdown._interaction = interaction
    dropdown._selected_values = ["vrising"]
    return dropdown, interaction, cog


def _answers(interaction):
    calls = (interaction.followup.send.await_args_list
             + interaction.response.send_message.await_args_list
             + interaction.edit_original_response.await_args_list)
    texts = []
    for call in calls:
        if call.args:
            texts.append(str(call.args[0]))
        if "content" in call.kwargs and call.kwargs["content"]:
            texts.append(str(call.kwargs["content"]))
    return texts


async def _press(has_channel_permission, is_admin):
    dropdown, interaction, cog = _dropdown()
    servers = MagicMock()
    servers.get_server_by_docker_name.return_value = dict(CONTAINER)
    cog._generate_status_embed_and_view = AsyncMock(
        return_value=(MagicMock(), MagicMock(), None))
    cog.get_status = AsyncMock(return_value=SimpleNamespace(success=True, is_running=True))
    cog.expanded_states = {}
    with patch("cogs.control_ui.get_server_config_service", return_value=servers), \
         patch("cogs.control_ui.load_config", return_value={"servers": [CONTAINER]}), \
         patch("cogs.control_ui._channel_has_permission",
               return_value=has_channel_permission), \
         patch("cogs.control_ui._get_cached_channel_permission",
               return_value=has_channel_permission), \
         patch("cogs.control_ui._is_registered_admin", return_value=is_admin):
        await dropdown.callback(interaction)
    return interaction, cog


@pytest.mark.asyncio
async def test_a_registered_admin_gets_the_panel():
    """Premise: the people the menu is for must still get through."""
    interaction, cog = await _press(has_channel_permission=False, is_admin=True)

    cog._generate_status_embed_and_view.assert_awaited()
    assert REFUSAL not in " ".join(_answers(interaction))


@pytest.mark.asyncio
async def test_a_control_channel_gets_the_panel():
    """Whoever may write in a control channel may do everything there (B1)."""
    interaction, cog = await _press(has_channel_permission=True, is_admin=False)

    cog._generate_status_embed_and_view.assert_awaited()


@pytest.mark.asyncio
async def test_a_bystander_in_a_status_channel_is_refused():
    interaction, cog = await _press(has_channel_permission=False, is_admin=False)

    assert REFUSAL in " ".join(_answers(interaction)), (
        f"no refusal, the answers were: {_answers(interaction)}"
    )
    cog._generate_status_embed_and_view.assert_not_awaited()
