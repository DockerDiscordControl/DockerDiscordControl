# -*- coding: utf-8 -*-
"""The container list is the point of the overview. The mech is decoration on it.

THE FINDING (review E20, cogs/docker_control.py): both overview builders -
``_create_overview_embed_expanded`` and ``_create_overview_embed_collapsed`` -
assemble the container status lines first, set them as ``embed.description``,
and only then add the mech section. The mech section is wrapped in a handler
listing ``(discord.errors.DiscordException, RuntimeError, OSError, KeyError)``.

The mech services raise ``MechStateError -> MechServiceError ->
DDCBaseException``, and the cache service can raise ``AttributeError`` or
``ImportError`` on a bad import. None of those are in that tuple, so the
exception left the builder entirely - and the finished container list went with
it. The operator loses the thing they actually need (is my Minecraft server
up?) because of the thing they do not (an animated robot).

**The file already says this happened.** The comment at the top of that mech
block records two bugs that lived there until v2.4.1, the first of them:

    It imported MECH_LEVELS from services.mech.mech_service, which has never
    exported that name. The ImportError escaped the handler below (it only
    catches DiscordException/RuntimeError/OSError/KeyError), so expanding the
    mech section in Discord crashed outright.

That was repaired by fixing the import. The shape that let one bad import take
the whole overview down was left as it was.

The handler is broad now, and the counter-check keeps the point: the mech
FAILING must not become the mech silently showing nothing wrong.
"""

import pytest

from services.exceptions import MechStateError


SERVERS = [
    {"docker_name": "minecraft", "display_name": "Minecraft"},
    {"docker_name": "valheim", "display_name": "Valheim"},
]


@pytest.fixture
def cog_with_a_broken_mech(monkeypatch):
    import cogs.docker_control as docker_control
    from cogs.docker_control import DockerControlCog

    monkeypatch.setattr(docker_control, "load_config", lambda: {"timezone": "Europe/Berlin"})
    # The overview embeds moved to cogs/overview_embeds.py (Phase 3): patch both.
    import cogs.overview_embeds as overview_embeds
    monkeypatch.setattr(overview_embeds, "load_config", lambda: {"timezone": "Europe/Berlin"})

    import services.donation.donation_utils as donation_utils
    monkeypatch.setattr(donation_utils, "is_donations_disabled", lambda: False)

    import services.mech.mech_status_cache_service as cache_service_module

    def broken():
        raise MechStateError("the snapshot lags behind the event log")

    monkeypatch.setattr(cache_service_module, "get_mech_status_cache_service", broken)

    cog = DockerControlCog.__new__(DockerControlCog)
    cog.pending_actions = {}

    class _EmptyCache:
        def get(self, _name):
            return None

    cog.status_cache_service = _EmptyCache()
    return cog


@pytest.mark.parametrize("builder", ["_create_overview_embed_collapsed"])
@pytest.mark.asyncio
async def test_the_container_list_survives_a_broken_mech(builder, cog_with_a_broken_mech):
    from cogs.docker_control import DockerControlCog

    result = await getattr(DockerControlCog, builder)(
        cog_with_a_broken_mech, SERVERS, {"timezone": "Europe/Berlin"})

    embed = result[0] if isinstance(result, tuple) else result
    assert embed is not None, (
        f"{builder} raised because the mech section failed - the operator lost "
        f"the container list, which is the only part they need"
    )
    assert "Minecraft" in (embed.description or ""), (
        f"an embed came back but without the containers: {embed.description!r}"
    )
    assert "Valheim" in (embed.description or "")


@pytest.mark.parametrize("builder", ["_create_overview_embed_collapsed"])
@pytest.mark.asyncio
async def test_a_broken_mech_is_still_reported(builder, cog_with_a_broken_mech, caplog):
    """Counter-check: surviving the failure must not mean hiding it."""
    import logging

    from cogs.docker_control import DockerControlCog

    with caplog.at_level(logging.DEBUG):
        await getattr(DockerControlCog, builder)(
            cog_with_a_broken_mech, SERVERS, {"timezone": "Europe/Berlin"})

    assert any(r.levelno >= logging.ERROR for r in caplog.records), (
        "the mech section failed and nothing was logged at all"
    )
