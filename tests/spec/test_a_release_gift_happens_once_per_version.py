# -*- coding: utf-8 -*-
"""The release gift is given once per version, by the startup step.

WHAT THE OPERATOR ASKED FOR (2026-09-23): each DDC release gives an empty mech
three days of energy. The version DDC runs is in DDC_VERSION (set by the
Dockerfile, the same value /health and the page footer show), so the campaign
is named after it and the event log refuses a campaign it already carries -
a restart of the same version gives nothing, an update gives once.

Without a version - a container started without DDC_VERSION - there is no
release to celebrate and the step does nothing rather than inventing a name
that would hand out a gift on every restart.

COUNTER-CHECK (2026-09-23): red before - the step only ever ran the fixed
"startup_gift_v1" campaign, so an update gave nothing. The counter-checks
hold the version in the campaign id and the do-nothing case.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.bot.startup_steps import power as step_module


@pytest.fixture
def adapter(monkeypatch):
    """Records which campaigns were offered a gift."""
    offered = []

    class Adapter:
        def power_gift(self, campaign_id, gift_cents=None):
            offered.append((campaign_id, gift_cents))
            return SimpleNamespace(power_level=3.0, level=1)

        def release_gift(self, version):
            from services.mech.gifts import three_days_of_energy

            offered.append((f"release_{version}", three_days_of_energy(1)))
            return SimpleNamespace(power_level=3.0, level=1)

    monkeypatch.setattr("services.mech.mech_service_adapter.get_mech_service",
                        lambda: Adapter())
    return offered


def _run(monkeypatch, version):
    if version is None:
        monkeypatch.delenv("DDC_VERSION", raising=False)
    else:
        monkeypatch.setenv("DDC_VERSION", version)
    context = SimpleNamespace(logger=MagicMock())
    asyncio.run(step_module.grant_power_gift_step(context))


def test_the_campaign_carries_the_version(adapter, monkeypatch):
    _run(monkeypatch, "3.0.0")

    assert any("3.0.0" in campaign for campaign, _cents in adapter), (
        f"no campaign named after the release: {adapter}")


def test_the_gift_is_three_days_of_energy(adapter, monkeypatch):
    from services.mech import gifts

    _run(monkeypatch, "3.0.0")
    release = [cents for campaign, cents in adapter if "3.0.0" in campaign]

    assert release and release[0] == gifts.three_days_of_energy(1), (
        f"the release gift must be three days of the mech's consumption: {release}")


def test_without_a_version_nothing_is_offered(adapter, monkeypatch):
    """Counter-check: no version, no release - and no gift on every restart."""
    _run(monkeypatch, None)

    assert [c for c, _ in adapter if "release" in c] == []


def test_the_startup_gift_still_exists(adapter, monkeypatch):
    """Counter-check: a fresh install still gets its welcome gift."""
    _run(monkeypatch, "3.0.0")

    assert any(campaign == "startup_gift_v1" for campaign, _ in adapter)


def test_a_build_id_in_the_version_does_not_make_a_new_release(monkeypatch, adapter):
    """Build metadata is not a release.

    THE FINDING (independent review, 2026-09-23): the campaign is named after
    DDC_VERSION as it stands. If an image ever stamps a build id or a git sha
    into it, every rebuild of the SAME release becomes a new campaign: another
    three days of energy for a dry mech, and one more PowerGiftGranted in a log
    that read_events() walks end to end before every donation.

    SemVer puts build metadata after a "+", so that is where the release ends.
    """
    _run(monkeypatch, "3.0.0+build.271")

    campaigns = [campaign for campaign, _cents in adapter if campaign.startswith("release_")]

    assert campaigns == ["release_3.0.0"], campaigns


def test_the_version_itself_is_still_the_campaign(monkeypatch, adapter):
    """Counter-check: an ordinary version is not truncated."""
    _run(monkeypatch, "3.0.1")

    assert any(campaign == "release_3.0.1" for campaign, _ in adapter)
