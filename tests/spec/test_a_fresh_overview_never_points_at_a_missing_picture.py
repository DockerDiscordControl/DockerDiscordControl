# -*- coding: utf-8 -*-
"""A freshly sent overview never points at a picture it does not carry.

THE FINDING (stage 4 review before v3.1.0, section 05, both passes,
verified 2026-09-29). The overview builder sets
attachment://mech_animation.webp on the embed even when the animation
could not be built - on purpose, so that an EDIT keeps the picture already
on the message. /ss deletes the old overview and sends a NEW one: when the
animation had failed it went out without a file but with that reference -
a broken image, or a payload Discord refuses, whose identical retry failed
the same way ("An error occurred while generating the overview").
_send_message_with_files already dropped the reference; /ss sent past it.

THE CONTRACT: every send in serverstatus without a file goes through
without_dangling_image(), which drops an attachment:// image.

HOW THIS TEST CAN FAIL: a file-less send of the embed as it is.

COUNTER-CHECK (2026-09-29): written before the fix and red then.
"""

import ast
from pathlib import Path

import discord

SLASH = Path(__file__).resolve().parents[2] / "cogs" / "slash_commands.py"


def test_the_helper_drops_only_an_attachment_reference():
    from cogs.slash_commands import without_dangling_image

    dangling = discord.Embed(title="x")
    dangling.set_image(url="attachment://mech_animation.webp")
    image = without_dangling_image(dangling).image
    assert not (image and image.url)

    real = discord.Embed(title="y")
    real.set_image(url="https://ddc.bot/x.png")
    assert without_dangling_image(real).image.url == "https://ddc.bot/x.png"


def test_every_file_less_send_in_serverstatus_goes_through_it():
    tree = ast.parse(SLASH.read_text(encoding="utf-8"))
    command = next(node for node in ast.walk(tree)
                   if isinstance(node, ast.AsyncFunctionDef) and node.name == "serverstatus")
    sends = [call for call in ast.walk(command)
             if isinstance(call, ast.Call) and ast.unparse(call.func).endswith("followup.send")
             and any(k.arg == "embed" for k in call.keywords)
             and not any(k.arg == "file" for k in call.keywords)]

    assert sends, "no file-less send found - the scan has gone blind"
    for call in sends:
        embed = next(k.value for k in call.keywords if k.arg == "embed")
        assert "without_dangling_image" in ast.unparse(embed), ast.unparse(call)
