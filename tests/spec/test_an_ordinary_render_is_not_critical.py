# -*- coding: utf-8 -*-
"""Showing the overview is not a CRITICAL event.

No ``@covers`` marker: a finding, not a guarantee.

THE FINDING (stage 4 review, stage B, section 05 F4, re-checked 2026-09-20):
``_create_overview_embed_expanded`` wrote six ``logger.critical`` lines on
every expanded render - "BARS DEBUG - mech_progress_current=2 (type: <class
'int'>)" and the like. They are leftovers from hunting a bar that showed
100 %, and they are labelled DEBUG in their own text. CRITICAL is the level
an operator greps for and wires alerts to; ordinary numbers of an ordinary
render do not belong there, and drown out the line that really matters.
"""

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from cogs.docker_control import DockerControlCog


def _mech_result():
    """A cached mech status good enough to reach the progress bars."""
    bars = SimpleNamespace(Power_current=3, Power_max_for_level=10,
                           mech_progress_current=2, mech_progress_max=4)
    return SimpleNamespace(success=True, cache_age_seconds=1.0, error_message=None,
                           power=3.0, total_donated=12, level=2,
                           name="Scout", threshold=25.0, speed=7,
                           speed_description="brisk", speed_color=0x00FF41,
                           glvl=2, glvl_max=11, bars=bars)


async def _render(caplog):
    service = MagicMock()
    service.get_cached_status.return_value = _mech_result()
    cog = object.__new__(DockerControlCog)
    with caplog.at_level(logging.DEBUG):
        with patch("cogs.docker_control.load_config", return_value={}), patch("cogs.overview_embeds.load_config", return_value={}), \
             patch("services.donation.donation_utils.is_donations_disabled",
                   return_value=False), \
             patch("services.mech.mech_status_cache_service.get_mech_status_cache_service",
                   return_value=service):
            await cog._create_overview_embed_expanded([], {})
    return caplog.records


@pytest.mark.asyncio
async def test_the_render_reaches_the_progress_bars(caplog):
    """Premise: without this the test would pass on a render that never ran."""
    records = await _render(caplog)

    assert any("CACHE BARS" in record.getMessage() for record in records), (
        "the render did not get as far as the bars - the test would prove nothing"
    )


@pytest.mark.asyncio
async def test_nothing_is_logged_as_critical(caplog):
    records = await _render(caplog)

    critical = [record.getMessage() for record in records
                if record.levelno >= logging.CRITICAL]
    assert not critical, f"an ordinary render logged as CRITICAL: {critical}"
