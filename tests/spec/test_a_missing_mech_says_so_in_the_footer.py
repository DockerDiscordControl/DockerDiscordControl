# -*- coding: utf-8 -*-
"""An overview whose mech section failed says so in its footer.

THE FINDING (stage 4 review before v3.1.0, section 05 pass 4 F12): when the
mech status could not be read, the collapsed overview dropped the whole mech
section - no "Donation Engine" field, no image - and, unlike the animation
failure one level further in, wrote no hint in the footer. The mech just
vanished, and the reason was only in the log: the situation
with_website_footer's docstring records the operator complaining about.

THE CONTRACT: the footer names it, before the website line.

HOW THIS TEST CAN FAIL: the mech vanishes silently again.

COUNTER-CHECK (2026-09-29): red before the change.
"""

import pytest

from tests.spec.test_a_broken_mech_does_not_hide_the_servers import (SERVERS,  # noqa: F401
                                                                     cog_with_a_broken_mech)


@pytest.mark.asyncio
async def test_the_footer_names_the_missing_mech(cog_with_a_broken_mech):  # noqa: F811
    from cogs.docker_control import DockerControlCog

    embed, _file = await DockerControlCog._create_overview_embed_collapsed(
        cog_with_a_broken_mech, SERVERS, {"timezone": "Europe/Berlin"})

    footer = embed.footer.text if embed.footer else ""
    assert footer != "https://ddc.bot" and "unavailable" in footer.lower(), (
        f"the mech section vanished without a word: {footer!r}")
    assert footer.split()[-1] == "https://ddc.bot"
