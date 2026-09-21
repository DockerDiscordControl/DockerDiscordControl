# -*- coding: utf-8 -*-
"""A donation has an upper limit, and it is refused rather than trimmed.

THE FINDING (review D2, pass 2, section 24 F4): `add_donation` rejects
`units_cents <= 0` and nothing else. `add_system_donation` caps at
MAX_SYSTEM_DONATION ($1,000) and `apply_donation_units` clamps power at
MAX_POWER and the cumulative total at MAX_CUMULATIVE - but an ordinary
donation had no upper bound of its own, so a mistyped or malicious amount
went into the ledger and was only silently clamped afterwards, deep inside
the power maths, where nobody is told.

THE LIMIT IS THE OPERATOR'S DECISION (2026-09-21): $10,000.00 per donation.
Refused, not trimmed - a clamped amount is the "silently tidied up" shape
this programme keeps removing, and the donor would be charged for something
the ledger did not record.
"""

import importlib
import json
from types import SimpleNamespace

import pytest

from services.donation.unified.models import DonationRequest
from services.donation.unified.validation import (
    DonationValidationError, validate_request)
from services.mech.progress import reset_progress_runtime
from services.mech.progress_paths import clear_progress_paths_cache

LIMIT = 10_000.00


@pytest.fixture
def progress(tmp_path, monkeypatch):
    monkeypatch.setenv("DDC_PROGRESS_DATA_DIR", str(tmp_path / "progress"))
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path / "config"))
    reset_progress_runtime()
    clear_progress_paths_cache()

    module = importlib.reload(importlib.import_module("services.mech.progress_service"))
    module.reset_progress_services()
    config = {"timezone": "UTC", "difficulty_bins": [0, 50],
              "level_base_costs": {str(level): 100000 for level in range(1, 12)},
              "bin_to_dynamic_cost": {str(b): 0 for b in range(1, 22)},
              "mech_power_decay_per_day": {"default": 0}}
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


def _request(amount):
    return DonationRequest(amount=amount, donor_name="max", source="web")


def test_the_ledger_refuses_more_than_the_limit(progress):
    with pytest.raises(ValueError) as refusal:
        progress.add_donation(LIMIT + 0.01, donor="max")

    assert "10,000" in str(refusal.value) or "10000" in str(refusal.value), (
        f"the refusal does not say what the limit is: {refusal.value}"
    )


def test_the_form_refuses_it_before_the_ledger_is_touched():
    """The donor should be told by the panel, not by an exception from the
    depths of the ledger."""
    with pytest.raises(DonationValidationError) as refusal:
        validate_request(_request(LIMIT + 0.01))

    assert "10,000" in str(refusal.value) or "10000" in str(refusal.value), refusal.value


def test_the_limit_itself_is_allowed(progress):
    """Counter-check: the boundary belongs to the donor, not to the refusal."""
    state = progress.add_donation(LIMIT, donor="max")

    assert state.total_donated == pytest.approx(LIMIT)
    validate_request(_request(LIMIT))


def test_an_ordinary_donation_is_untouched(progress):
    """Counter-check: refusing everything would pass the tests above."""
    state = progress.add_donation(20.0, donor="max")

    assert state.total_donated == pytest.approx(20.0)


def test_nothing_is_booked_when_it_is_refused(progress):
    """Refused, not trimmed: the ledger must be exactly as it was."""
    progress.add_donation(20.0, donor="max", idempotency_key="one")

    with pytest.raises(ValueError):
        progress.add_donation(LIMIT + 0.01, donor="max", idempotency_key="two")

    assert progress.get_state().total_donated == pytest.approx(20.0)


def test_the_two_limits_stay_in_step(progress):
    """The form and the ledger each carry the number. Two places that say the
    same thing are two places that can drift apart - and the day they do, the
    panel accepts an amount the ledger then refuses, after the donor paid."""
    import services.mech.progress_service as ledger
    from services.donation.unified import validation

    assert ledger.MAX_DONATION == int(round(validation.MAX_DONATION_DOLLARS * 100))
    assert validation.MAX_DONATION_DOLLARS == LIMIT
