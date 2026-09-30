# -*- coding: utf-8 -*-
"""A container display name written in brackets keeps them.

THE FINDING (stage 4 review before v3.1.0, section 12 pass 4 F11): the
parser treated any name starting with "[" and ending with "]" as a
stringified Python list: "[PROD]" was saved as "PROD", "[1]" as "1",
"[EU] Valheim]" as "EU] Valheim". The panel posts plain strings; the list
case only ever came from an old form shape.

THE CONTRACT: a name is taken as written unless it really is a list of
names ("['Name']").

HOW THIS TEST CAN FAIL: brackets are stripped again, or the real list case
stops working.

COUNTER-CHECK (2026-09-30): the bracket names red before the change; the
list case green before and after.
"""

import pytest

from services.config.config_form_parser_service import ConfigFormParserService


@pytest.mark.parametrize("name", ["[PROD]", "[1]", "[EU] Valheim]"])
def test_a_bracketed_name_is_kept(name):
    assert ConfigFormParserService._parse_display_name(name, "web") == name


def test_a_stringified_list_still_gives_its_first_name():
    assert ConfigFormParserService._parse_display_name("['Valheim', 'x']", "web") == "Valheim"
