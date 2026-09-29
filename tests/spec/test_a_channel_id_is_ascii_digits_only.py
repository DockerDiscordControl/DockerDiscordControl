# -*- coding: utf-8 -*-
"""A channel id is 17-19 ASCII digits - everywhere it is checked.

THE FINDING (stage 4 review before v3.1.0, section 11 pass 3 F3): the form
and the channel store checked ids with str.isdigit(), which accepts circled
and superscript digits ("①" x 18); the delete path used a regex. Such an id
pasted into a channel row was saved as <id>.json - and once the operator
removed the row, the delete refused it, and every later save reported "the
channels could not be saved" while the file stayed. (Python's \\d also
matches other scripts' digits, e.g. Arabic-Indic ones.)

THE CONTRACT: one rule, [0-9]{17,19}, for the form, the store and the delete.

HOW THIS TEST CAN FAIL: a non-ASCII digit id is accepted anywhere again.

COUNTER-CHECK (2026-09-29): red before the change; an ordinary id is
accepted before and after.
"""

import pytest

from services.config.config_form_parser_service import ConfigFormParserService

ODD = ["①" * 18, "١" * 18]
GOOD = "123456789012345678"


@pytest.mark.parametrize("channel_id", ODD)
def test_the_form_names_it_unusable(channel_id):
    form = {"control_channel_id_1": channel_id, "control_channel_name_1": "x"}
    assert channel_id in ConfigFormParserService.find_unusable_channel_ids(form)
    assert channel_id not in ConfigFormParserService.parse_channel_permissions_from_form(form)


@pytest.mark.parametrize("channel_id", ODD)
def test_the_store_does_not_write_it(channel_id, tmp_path, monkeypatch):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    from services.config.channel_config_service import ChannelConfigService
    service = ChannelConfigService.__new__(ChannelConfigService)
    assert not service._is_valid_discord_id(channel_id)


def test_an_ordinary_id_is_fine():
    form = {"control_channel_id_1": GOOD, "control_channel_name_1": "x"}
    assert ConfigFormParserService.find_unusable_channel_ids(form) == []
