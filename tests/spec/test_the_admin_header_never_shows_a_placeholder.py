# -*- coding: utf-8 -*-
"""The admin overview header must show numbers, never the words {online}.

THE FINDING (review E42, cogs/docker_control.py): the header line of the admin
overview is built TWICE. Once before the containers are counted, with the two
counts passed as the literal strings ``'{online}'`` and ``'{offline}'`` so they
survive the format as placeholders - and once afterwards, from scratch, with
the real numbers.

The second one overwrites the first completely, so the placeholder trick is
work whose result is thrown away: one extra catalogue lookup and one extra
format for every admin overview ever rendered. Harmless today.

What is NOT harmless is what it looks like. A reader sees a deliberate
two-pass format and concludes the first line matters - and if the second ever
stops running, on any path, the operator's admin panel reads

    Container: 7 • Online: {online} • Offline: {offline}

with the words, not the numbers. Nothing anywhere would catch that, because
the strings are perfectly valid and the embed renders.

So the first build is gone and this test holds the outcome: the header carries
numbers, and never a literal placeholder.
"""

import pytest


SERVERS = [
    {"docker_name": "alpha", "display_name": "Alpha"},
    {"docker_name": "beta", "display_name": "Beta"},
]


@pytest.fixture
def cog(monkeypatch):
    import cogs.docker_control as docker_control
    from cogs.docker_control import DockerControlCog

    monkeypatch.setattr(docker_control, "load_config", lambda: {"timezone": "UTC"})

    instance = DockerControlCog.__new__(DockerControlCog)
    instance.pending_actions = {}

    class _NoCache:
        def get(self, _name):
            return None

    instance.status_cache_service = _NoCache()
    return instance


@pytest.mark.asyncio
async def test_the_header_shows_numbers_not_placeholders(cog):
    from cogs.docker_control import DockerControlCog

    result = await DockerControlCog._create_admin_overview_embed(
        cog, SERVERS, {"timezone": "UTC"})
    embed = result[0] if isinstance(result, tuple) else result
    description = embed.description or ""

    assert "{online}" not in description and "{offline}" not in description, (
        f"the admin panel header shows the placeholder words instead of the "
        f"counts: {description.splitlines()[:2]}"
    )
    assert "{total}" not in description


@pytest.mark.asyncio
async def test_the_header_counts_the_containers(cog):
    """Counter-check: removing the placeholder must not remove the numbers."""
    from cogs.docker_control import DockerControlCog

    result = await DockerControlCog._create_admin_overview_embed(
        cog, SERVERS, {"timezone": "UTC"})
    embed = result[0] if isinstance(result, tuple) else result
    header = (embed.description or "").splitlines()[1]

    assert "2" in header, f"two containers were given and the header says: {header!r}"
