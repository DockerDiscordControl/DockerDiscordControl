# -*- coding: utf-8 -*-
"""Every channel row of the panel form is read, whatever gaps the numbering has.

No ``@covers`` marker: a finding, not a guarantee.

THE FINDING (stage 4 review, stage B, section 11 F4, re-checked 2026-09-20):
``_parse_channel_type`` walks the form rows by number. On an empty slot it
looked ahead only NINE slots for the next filled one and stopped otherwise.
A form whose numbering has a bigger gap - rows deleted in the panel - ends
early, and the channels behind the gap never reach the parser. Saving then
removes exactly those: ``channel_config_service.save_all_channels`` deletes
every ``<channel_id>.json`` that is not in the parsed set
(channel_config_service.py:315). The operator saves one unrelated change and
loses the permissions of the channels behind the gap, with no error
anywhere.
"""

import pytest

from services.config.config_form_parser_service import ConfigFormParserService

FIRST = "123456789012345678"
BEHIND_THE_GAP = "987654321098765432"


def _form(second_row):
    """Two status channels: row 1 and row <second_row>, everything between empty."""
    form = {"status_channel_id_1": FIRST, "status_channel_name_1": "first"}
    form[f"status_channel_id_{second_row}"] = BEHIND_THE_GAP
    form[f"status_channel_name_{second_row}"] = "behind the gap"
    return form


@pytest.mark.parametrize("second_row", [5, 20, 45], ids=["gap-3", "gap-18", "gap-43"])
def test_a_channel_behind_a_gap_is_read(second_row):
    channels = ConfigFormParserService.parse_channel_permissions_from_form(_form(second_row))

    assert FIRST in channels, "premise: the first row is read"
    assert BEHIND_THE_GAP in channels, (
        f"the channel in row {second_row} was not read - saving would delete its "
        f"permissions (channel_config_service.save_all_channels)"
    )
