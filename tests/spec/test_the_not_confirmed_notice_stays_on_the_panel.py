# -*- coding: utf-8 -*-
"""The "Not confirmed yet" notice stays on the panel - it is not redrawn away.

THE FINDING (stage 4 review before v3.1.0, section 02 pass 4 F1, verified
2026-09-29). When the wait after an action gave up, ActionButton showed the
gold "Not confirmed yet" notice (the operator's wish of 2026-09-24: an
error message if the container does not come up) - and then spawned
update_all_views unconditionally, which edited the same message back to
the ordinary status or admin embed a moment later. The notice was on screen
for a fraction of a second.

THE CONTRACT: when the action was not confirmed, the redrawn panel carries
the notice (with its buttons back); otherwise the status embed.

HOW THIS TEST CAN FAIL: the redraw takes the status embed regardless again.

The redraw needs a live interaction, so the choice is one function,
panel_embed_after(), tested here - and the source is read to hold that
both redraws of the panel go through it (the fault was the call site).

COUNTER-CHECK (2026-09-29): written before the fix and red then.
"""

import ast
from pathlib import Path

import discord

CONTROL_UI = Path(__file__).resolve().parents[2] / "cogs" / "control_ui.py"


def test_not_confirmed_keeps_the_notice():
    from cogs.action_effect import panel_embed_after

    status = discord.Embed(title="status")
    chosen = panel_embed_after(False, status, "Valheim", "start")

    assert chosen is not status and "Valheim" in (chosen.title or "") + (chosen.description or "")


def test_confirmed_shows_the_status():
    from cogs.action_effect import panel_embed_after

    status = discord.Embed(title="status")

    assert panel_embed_after(True, status, "Valheim", "start") is status
    assert panel_embed_after(None, status, "Valheim", "start") is status


def test_both_redraws_go_through_it():
    tree = ast.parse(CONTROL_UI.read_text(encoding="utf-8"))
    redraw = next(node for node in ast.walk(tree)
                  if isinstance(node, ast.AsyncFunctionDef) and node.name == "update_all_views")
    edits = [call for call in ast.walk(redraw)
             if isinstance(call, ast.Call) and getattr(call.func, "attr", "") == "edit_original_response"]

    assert len(edits) == 2, f"expected the admin and the normal redraw, found {len(edits)}"
    for call in edits:
        embed = next(k.value for k in call.keywords if k.arg == "embed")
        assert "panel_embed_after" in ast.unparse(embed), ast.unparse(embed)
