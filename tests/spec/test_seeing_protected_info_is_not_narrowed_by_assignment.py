# -*- coding: utf-8 -*-
"""An admin tied to other containers still SEES password-less protected info.

THE QUESTION (stage 4 review before v3.1.0, section 02 pass 4 F5): an admin
assigned to container A reads the password-less protected info of container
B through the info dropdown. SPEC B2 says "seeing is not narrowed, only the
controls follow the assignment"; a code comment treated reading protected
content as something the assignment should limit. The two disagreed.

THE OPERATOR (2026-09-29): B2 applies - seeing is not narrowed. Password-less
protected info is shown to every registered admin; only the controls follow
the assignment. (A password still protects what has one, and editing the
protected info is a control and follows the assignment.)

This is a pin on a decision, not a repair: the code already did this. It is
here so that nobody "fixes" it into the narrow reading.

COUNTER-CHECK (2026-09-29): with the dropdown asking _admin_may_control
instead of _is_registered_admin, the first case went red.
"""

import pytest

import cogs.control_ui as cui
from tests.spec.test_protected_info_uses_the_real_permission import SECRET, _dropdown, _shown


@pytest.mark.asyncio
async def test_an_admin_of_other_containers_sees_the_protected_info(monkeypatch):
    dropdown, interaction = _dropdown(monkeypatch, control=False)
    monkeypatch.setattr(cui, "_is_registered_admin", lambda user_id: True)
    monkeypatch.setattr(cui, "_admin_may_control", lambda user_id, name: False)

    await dropdown.callback(interaction)

    assert SECRET in _shown(interaction), "B2: seeing is not narrowed by the assignment"


@pytest.mark.asyncio
async def test_somebody_who_is_no_admin_does_not(monkeypatch):
    dropdown, interaction = _dropdown(monkeypatch, control=False)
    monkeypatch.setattr(cui, "_is_registered_admin", lambda user_id: False)
    monkeypatch.setattr(cui, "_admin_may_control", lambda user_id, name: False)

    await dropdown.callback(interaction)

    assert SECRET not in _shown(interaction)
