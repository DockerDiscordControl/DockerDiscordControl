# -*- coding: utf-8 -*-
"""A missing animation is said in the footer - and never sent as a broken image.

Two halves of the same failure. When the animation service cannot deliver,
the overview builder writes "🎬 Animation service temporarily unavailable"
into the embed's footer - and the last line before the return sets the footer
to "https://ddc.bot", unconditionally, so the notice was erased on every
single render. The operator saw an overview with a missing image and no
explanation.

And the embed still pointed at attachment://mech_animation.webp with no file
to go with it. On an EDIT that reference is right (the attachment is already
on the message); on a fresh send - the first /ss in a channel - it is a
broken image. The shared sender drops an attachment reference when it sends
no attachment.

COUNTER-CHECK (2026-09-22): red before - the footer read only the website,
and the sent embed kept the attachment URL.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from cogs.docker_control import DockerControlCog


def test_the_website_footer_does_not_erase_the_notice():
    from cogs.docker_control import DockerControlCog  # noqa: F401 - documents where the builder lives

    embed = discord.Embed(description="containers")
    embed.set_footer(text="🎬 Animation service temporarily unavailable")

    from cogs.overview_embeds import with_website_footer

    with_website_footer(embed)

    assert "Animation" in embed.footer.text, embed.footer.text
    assert "ddc.bot" in embed.footer.text


def test_an_embed_without_a_notice_gets_the_plain_website_footer():
    """Counter-check: the ordinary overview looks exactly as before."""
    from cogs.overview_embeds import with_website_footer

    embed = discord.Embed(description="containers")
    with_website_footer(embed)

    assert embed.footer.text == "https://ddc.bot"


@pytest.mark.asyncio
async def test_a_message_sent_without_a_file_does_not_reference_one():
    cog = object.__new__(DockerControlCog)
    embed = discord.Embed(description="containers")
    embed.set_image(url="attachment://mech_animation.webp")
    target = SimpleNamespace(send=AsyncMock(return_value="sent"))

    await cog._send_message_with_files(target, embed, None, view="view")

    sent = target.send.await_args.kwargs["embed"]
    assert not sent.image or not (sent.image.url or "").startswith("attachment://"), (
        f"a broken image was sent: {sent.image.url}")


@pytest.mark.asyncio
async def test_a_message_with_a_file_keeps_its_image():
    """Counter-check: the animation must still be shown when there is one."""
    cog = object.__new__(DockerControlCog)
    embed = discord.Embed(description="containers")
    embed.set_image(url="attachment://mech_animation.webp")
    file = MagicMock(filename="mech_animation.webp")
    target = SimpleNamespace(send=AsyncMock(return_value="sent"))

    await cog._send_message_with_files(target, embed, file, view="view")

    sent = target.send.await_args.kwargs["embed"]
    assert sent.image.url == "attachment://mech_animation.webp"
