# -*- coding: utf-8 -*-
"""A real version made of ones and zeros ("1.0", "1.1") is shown.

THE FINDING (stage 4 review before v3.1.0, section 19b pass 3 F2 + pass 4
F5): the A2S version filter hid every version made only of 0s and 1s, to
drop the engine placeholders some servers answer with ("1.0.0.0" from
Valheim, "0.0.0.1" from Icarus - measured 2026-09-28). With them it hid
real versions: a game at "1.0" or "1.1" showed no version at all.

THE OPERATOR (2026-09-29): show those; hide only the 0.0.0.0-like
placeholders.

THE CONTRACT (services/infrastructure/game_query_service.a2s_version): a
placeholder is all zeros ("0", "0.0.0.0"), or four or more parts of 0s and
1s ("1.0.0.0", "0.0.0.1"). Everything else is a version.

HOW THIS TEST CAN FAIL: "1.0" or "1.1" is hidden again; or the measured
placeholders come back as versions.

COUNTER-CHECK (2026-09-29): the shown cases red before the change, the
hidden ones green before and after.
"""

import pytest

from services.infrastructure.game_query_service import a2s_version


@pytest.mark.parametrize("version", ["1.0", "1.1", "1.0.1", "0.1", "10.0"])
def test_a_real_version_is_shown(version):
    assert a2s_version(version, "") == version, f"{version!r} was hidden as a placeholder"


@pytest.mark.parametrize("version", ["1.0.0.0", "0.0.0.1", "0.0.0.0", "0", "0.0", "1.1.1.1"])
def test_a_placeholder_stays_hidden(version):
    assert a2s_version(version, "") is None, f"the placeholder {version!r} was shown"
