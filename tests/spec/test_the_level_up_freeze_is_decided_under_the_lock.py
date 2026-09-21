# -*- coding: utf-8 -*-
"""The member count is frozen by the donation that actually levels up.

THE FINDING (review C73, section 23 F8): ``add_donation_async`` read
``self.progress_service.get_state()``, worked out from that snapshot whether
this donation would cross the threshold, froze the member count if so, and
only then called ``add_donation``. Two donations arriving close together both
read the same pre-donation state and each concluded "no level-up" - yet the
second one, booked after the first, is the one that crosses. The level-up
then priced the next level from whatever count happened to be on record
instead of the one the caller supplied.

The freeze belongs where the level-up is decided: inside
``progress_service``'s own lock. The caller now says which count to use IF
this donation turns out to be the one, and the progress service applies it
exactly then.
"""

import pytest

from services.mech.mech_service_adapter import MechServiceAdapter


class _ProgressDouble:
    """Stands in for the progress service, and records what it was told."""

    def __init__(self, level=3, evo_current=10.0, evo_max=20.0):
        self.level = level
        self.evo_current = evo_current
        self.evo_max = evo_max
        self.member_count_updates = []
        self.donations = []

    def get_state(self):
        return self

    # ProgressState fields the adapter's _convert_state reads.
    power_current = 5.0
    power_max = 20.0
    power_percent = 25
    evo_percent = 50
    total_donated = 100.0
    can_level_up = False
    is_offline = False
    difficulty_bin = 1
    difficulty_tier = "small"
    member_count = 50

    def update_member_count(self, count):
        self.member_count_updates.append(count)

    def add_donation(self, amount, donor=None, channel_id=None, *,
                     idempotency_key=None, member_count_at_level_up=None):
        self.donations.append({"amount": amount,
                               "member_count_at_level_up": member_count_at_level_up})
        return self


@pytest.fixture
def adapter(monkeypatch):
    adapter = MechServiceAdapter()
    double = _ProgressDouble()
    monkeypatch.setattr(adapter, "progress_service", double)
    adapter.double = double
    return adapter


@pytest.mark.asyncio
async def test_the_count_travels_with_the_donation(adapter):
    """THE FINDING: the caller's count must reach the call that books it."""
    await adapter.add_donation_async(5.0, donor="max", member_count=42)

    assert adapter.double.donations[-1]["member_count_at_level_up"] == 42, (
        "the count was decided from a snapshot taken before the booking, so a "
        "donation that turns out to level up may never see it"
    )


@pytest.mark.asyncio
async def test_a_small_donation_carries_it_too(adapter):
    """The one that matters: this donation does NOT look like a level-up from
    the state read beforehand, and is exactly the one that can become one."""
    adapter.double.evo_current = 0.0
    adapter.double.evo_max = 100.0

    await adapter.add_donation_async(1.0, donor="max", member_count=42)

    assert adapter.double.donations[-1]["member_count_at_level_up"] == 42


@pytest.mark.asyncio
async def test_the_guild_count_is_used_when_there_is_no_channel_count(adapter):
    """Counter-check: the existing fallback order stays."""
    class _Guild:
        member_count = 77

    await adapter.add_donation_async(5.0, donor="max", guild=_Guild())

    assert adapter.double.donations[-1]["member_count_at_level_up"] == 77


@pytest.mark.asyncio
async def test_without_any_count_nothing_is_invented(adapter):
    """Counter-check: no count means the progress service keeps its own."""
    await adapter.add_donation_async(5.0, donor="max")

    assert adapter.double.donations[-1]["member_count_at_level_up"] is None


# --------------------------------------------------------------------------- #
# The promise against the real progress service, not a double.
# --------------------------------------------------------------------------- #

import importlib
import json
from types import SimpleNamespace

from services.mech.progress import reset_progress_runtime
from services.mech.progress_paths import clear_progress_paths_cache

FROZEN_COUNT = 777


@pytest.fixture
def progress(tmp_path, monkeypatch):
    """An isolated progress runtime with a cheap level-up."""
    monkeypatch.setenv("DDC_PROGRESS_DATA_DIR", str(tmp_path / "progress"))
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path / "config"))
    reset_progress_runtime()
    clear_progress_paths_cache()

    module = importlib.reload(importlib.import_module("services.mech.progress_service"))
    module.reset_progress_services()

    config = {"timezone": "UTC", "difficulty_bins": [0, 50],
              "level_base_costs": {str(level): 100 for level in range(1, 12)},
              "bin_to_dynamic_cost": {str(b): 0 for b in range(1, 22)},
              "mech_power_decay_per_day": {"default": 100}}
    module.runtime.configure_defaults(config)
    module.runtime.paths.config_file.write_text(json.dumps(config), encoding="utf-8")
    module.CFG = module.runtime.load_config(refresh=True)
    module.TZ = module.runtime.timezone(refresh=True)

    config_module = importlib.import_module("services.config.config_service")
    monkeypatch.setattr(config_module, "get_config_service",
                        lambda: SimpleNamespace(
                            get_evolution_mode_service=lambda request:
                            config_module.GetEvolutionModeResult(
                                success=True, use_dynamic=True,
                                difficulty_multiplier=1.0)),
                        raising=False)
    module._decay_config_cache["data"] = None
    module._decay_config_cache["last_load"] = 0

    try:
        yield module.get_progress_service()
    finally:
        module.reset_progress_services()
        reset_progress_runtime()
        clear_progress_paths_cache()


def test_the_supplied_count_prices_the_new_level(progress):
    """The whole point: the donation that crosses the threshold is the one
    whose count is used, whoever turns out to be crossing it."""
    before = progress.get_state()
    crossing_amount = before.evo_max - before.evo_current + 1.0

    after = progress.add_donation(crossing_amount, donor="max",
                                  member_count_at_level_up=FROZEN_COUNT)

    assert after.level == before.level + 1, "the donation was meant to level up"
    assert after.member_count == FROZEN_COUNT, (
        "the level-up priced the next level from some other count"
    )


def test_a_donation_that_does_not_level_up_changes_no_count(progress):
    """Counter-check: the count is frozen AT the level-up, not on every
    donation - that is the whole of 'Option B'."""
    before = progress.get_state()
    small_amount = max(0.01, (before.evo_max - before.evo_current) / 2.0)

    after = progress.add_donation(small_amount, donor="max",
                                  member_count_at_level_up=FROZEN_COUNT)

    assert after.level == before.level
    assert after.member_count != FROZEN_COUNT
