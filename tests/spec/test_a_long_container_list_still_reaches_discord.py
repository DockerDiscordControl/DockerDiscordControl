# -*- coding: utf-8 -*-
"""A long container list still reaches Discord (embed description limit).

THE FINDING: none of the three overview embeds limits its description.
Discord refuses an embed whose description is longer than 4096 characters
with an HTTPException, so on an installation with many containers the
overview is not posted or updated AT ALL - the operator sees no overview and
only a line in the log. The list is built from the configured containers, so
it grows with the installation and the failure appears once and then stays.

What it does instead: as many containers as fit are shown, and the last line
says how many are not shown.

Measured 2026-09-22 with 200 containers whose names the layout shows in
full: admin overview 6,662 characters (refused), the server overview 4,082
and the collapsed one 3,687 - both a few characters below the limit, so they
break on the next container or a longer name. COUNTER-CHECK: all three cases
are red without the cut; removing the reserve for the "more" line makes the
helper's own limit test red.
"""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from cogs.docker_control import DockerControlCog
from services.discord.embed_helper_service import DESCRIPTION_LIMIT, fit_lines
from services.docker_status.models import ContainerStatusResult

MANY = 400
# Names as long as the layout shows them (20 characters in the server overview)
NAME = "game-server-{:03d}-eu"


def test_the_helper_keeps_the_limit_and_says_what_is_missing():
    lines = [f"line {i:04d} " + "x" * 60 for i in range(MANY)]
    text = fit_lines(lines, separator="\n", more=lambda n: f"… and {n} more")

    assert len(text) <= DESCRIPTION_LIMIT
    shown = [line for line in text.split("\n") if line.startswith("line ")]
    assert shown == lines[:len(shown)]
    assert text.endswith(f"… and {MANY - len(shown)} more")


def test_a_short_list_is_untouched():
    assert fit_lines(["a", "b"], separator="\n", more=lambda n: "…") == "a\nb"


def test_the_prefix_and_suffix_count():
    text = fit_lines(["y" * 100] * MANY, separator="\n", prefix="```\n", suffix="\n```",
                     more=lambda n: f"+{n}")
    assert len(text) <= DESCRIPTION_LIMIT
    assert text.startswith("```\n") and text.endswith("\n```")
    assert "+" in text


def _servers(count):
    return [{"docker_name": NAME.format(i), "name": NAME.format(i),
             "display_name": NAME.format(i), "allowed_actions": ["restart"]}
            for i in range(count)]


def _entries(servers):
    return {s["docker_name"]: {"data": ContainerStatusResult.success_result(
        docker_name=s["docker_name"], display_name=s["display_name"], is_running=True,
        cpu="1%", ram="1024 MB", uptime="1h", details_allowed=True),
        "timestamp": datetime.now(timezone.utc)} for s in servers}


@pytest.fixture
def cog():
    servers = _servers(MANY)
    entries = _entries(servers)
    cog = object.__new__(DockerControlCog)
    cog.status_cache_service = SimpleNamespace(get=entries.get)
    cog._status_update_semaphore = asyncio.Semaphore(1)
    cog._last_status_cache_refresh = 0.0
    cog._status_fetch_failed = set()
    cog.pending_actions = {}
    cog.mech_expanded_states = {}
    return SimpleNamespace(cog=cog, servers=servers)


@pytest.mark.parametrize("builder", ["_create_admin_overview_embed", "_create_overview_embed_collapsed",
                                     "_create_overview_embed_expanded"])
def test_every_overview_fits_with_many_containers(cog, builder):
    info_service = MagicMock()
    info_service.get_container_info.return_value = SimpleNamespace(success=False, data=None)
    mech_cache = MagicMock()
    mech_cache.get_cached_status.return_value = SimpleNamespace(success=False, error_message="n/a")
    with patch("cogs.overview_embeds.load_config", return_value={}), \
         patch("services.infrastructure.container_info_service.get_container_info_service",
               return_value=info_service), \
         patch("services.donation.donation_utils.is_donations_disabled", return_value=False), \
         patch("services.mech.mech_status_cache_service.get_mech_status_cache_service",
               return_value=mech_cache):
        result = asyncio.run(getattr(cog.cog, builder)(cog.servers, {}))
    embed = result[0]
    assert len(embed.description) <= DESCRIPTION_LIMIT, (
        f"{builder} builds {len(embed.description)} characters - Discord refuses the embed "
        f"and the overview never appears")
    # Names are truncated for the narrow layout, so only the prefix is looked for
    assert NAME.format(0)[:12] in embed.description, "the first containers are still shown"
    assert "more" in embed.description, "the line saying how many are missing"
