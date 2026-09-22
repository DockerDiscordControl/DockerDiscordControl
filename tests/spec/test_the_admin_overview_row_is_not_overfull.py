# -*- coding: utf-8 -*-
"""Discord takes five components per action row - the Admin Overview is at five.

The stack button (Phase 4c) made it admin, restart all, stop all, stack,
donate: exactly the maximum Discord allows in one action row. A sixth raises
at view construction, in production, when a channel's overview is built. Here
it fails in a test instead, where it is cheap - and whoever adds the sixth
sees at once that it needs its own row.

In its own file on purpose: building the view needs a running event loop, and
an async test in test_buttons_on_old_messages_keep_working.py leaves the
loop closed for the synchronous registration test that follows it there.

COUNTER-CHECK (2026-09-22): a sixth button added to row 0 by hand turned this
red - py-cord itself raises "item would not fit at row 0 (6 > 5 width)" while
the view is built, which is exactly what this test moves out of production.
"""

from types import SimpleNamespace

import pytest

CHANNEL = 111


@pytest.mark.asyncio
async def test_no_action_row_holds_more_than_five_components():
    from cogs.admin_overview import AdminOverviewView

    view = AdminOverviewView(SimpleNamespace(), CHANNEL, True)

    rows = {}
    for item in view.children:
        rows.setdefault(getattr(item, "row", 0) or 0, []).append(item)
    assert rows, "the view has no components at all"
    for row, items in rows.items():
        assert len(items) <= 5, f"row {row} holds {len(items)} components"
