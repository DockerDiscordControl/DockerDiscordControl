# -*- coding: utf-8 -*-
# @covers Z1
"""Z1 - a donation in the ledger is never silently missing from the mech.

``ProgressService.add_donation`` appends the DonationAdded event to the event
log FIRST and writes the snapshot (power, evolution, totals) afterwards. The
event log is the record of real money; the snapshot is derived from it.

THE FINDING (stage 4 review pass 1, section 24 F1, re-checked 2026-09-19): if
the snapshot write fails after the event was appended (disk full, permission,
a hiccup on the SMB-mounted data dir), the donation is in the ledger but its
effect is not in the snapshot - and nothing ever replays it:
``load_snapshot`` does not look at the log. A retry with the same idempotency
key finds the event, calls it "already booked" and returns the old state.
And the next MemberCountUpdated persists the stale snapshot with a HIGHER
``last_event_seq``, so the gap can no longer be seen from sequence numbers.

THE RULE NOW: a snapshot lags when the log holds a power event with a seq
higher than its ``last_event_seq``. Every method that moves ``last_event_seq``
forward (add_donation, add_system_donation, update_member_count, power_gift)
first rebuilds a lagging snapshot from the log - so no write can bury the gap
under a higher seq. No new snapshot field: the schema must stay identical to
v2.3.1, which refuses unknown keys (R1-8, tests/unit/audit_2026_09/
test_r2_g5_mech.py) - a first version of this fix added one and broke exactly
those three tests.
"""

import importlib
import json
from types import SimpleNamespace

import pytest

from services.mech.progress import reset_progress_runtime
from services.mech.progress_paths import clear_progress_paths_cache

BASE_COST = 100000  # $1,000 per level - small donations never level up here


@pytest.fixture
def ps(tmp_path, monkeypatch):
    """Reloaded progress_service with isolated paths (as in test_pkg_e_progress.py)."""
    monkeypatch.setenv("DDC_PROGRESS_DATA_DIR", str(tmp_path / "progress"))
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path / "ddc_config"))
    reset_progress_runtime()
    clear_progress_paths_cache()
    module = importlib.reload(importlib.import_module("services.mech.progress_service"))
    module._progress_service = None
    config = {
        "timezone": "UTC",
        "difficulty_bins": [0, 50],
        "level_base_costs": {str(level): BASE_COST for level in range(1, 12)},
        "bin_to_dynamic_cost": {str(b): 0 for b in range(1, 22)},
        "mech_power_decay_per_day": {"default": 100},
    }
    module.runtime.configure_defaults(config)
    module.runtime.paths.config_file.write_text(json.dumps(config), encoding="utf-8")
    module.CFG = module.runtime.load_config(refresh=True)
    module.TZ = module.runtime.timezone(refresh=True)
    module._decay_config_cache["data"] = None
    module._decay_config_cache["last_load"] = 0
    config_module = importlib.import_module("services.config.config_service")
    monkeypatch.setattr(
        config_module, "get_config_service",
        lambda: SimpleNamespace(get_evolution_mode_service=lambda request:
                                config_module.GetEvolutionModeResult(
                                    success=True, use_dynamic=True, difficulty_multiplier=1.0)),
        raising=False)
    yield module
    module._progress_service = None
    reset_progress_runtime()
    clear_progress_paths_cache()


def _fail_next_snapshot_write(ps, monkeypatch):
    real = ps.persist_snapshot
    state = {"armed": True}

    def flaky(snap):
        if state["armed"]:
            state["armed"] = False
            raise OSError("disk full")
        return real(snap)

    monkeypatch.setattr(ps, "persist_snapshot", flaky)


def _total_on_disk(ps, mech):
    return ps.load_snapshot(mech).cumulative_donations_cents


def _booked(ps, key):
    """Premise check: the failed call really put the donation into the ledger.

    The injected failure hits the NEXT snapshot write. If anything else writes a
    snapshot first (a rebuild, say), the donation is never appended - and a low
    total would then be right, not a lost donation.
    """
    assert any(e.type == "DonationAdded" and e.payload.get("idempotency_key") == key
               for e in ps.read_events()), f"premise broken: donation {key} is not in the ledger"


def test_a_retry_with_the_same_key_applies_the_lost_donation(ps, monkeypatch):
    svc = ps.ProgressService("m1")
    svc.add_donation(10.0, "Alex", idempotency_key="k1")
    _fail_next_snapshot_write(ps, monkeypatch)
    with pytest.raises(OSError):
        svc.add_donation(5.0, "Sam", idempotency_key="k2")
    _booked(ps, "k2")

    svc.add_donation(5.0, "Sam", idempotency_key="k2")   # the retry

    assert _total_on_disk(ps, "m1") == 1500, (
        "The $5 donation is in the ledger, but the retry called it 'already booked' "
        "and the mech never got it."
    )


@pytest.mark.parametrize("writer, expected", [
    (lambda svc: svc.update_member_count(30), 1700),
    (lambda svc: svc.add_system_donation(1.0, "motor", idempotency_key="sys"), 1800),
], ids=["member-count", "system-donation"])
def test_a_later_write_does_not_bury_it(ps, monkeypatch, writer, expected):
    """A write in between would persist the stale snapshot with a HIGHER seq."""
    svc = ps.ProgressService("m2")
    svc.add_donation(10.0, "Alex", idempotency_key="k1")
    _fail_next_snapshot_write(ps, monkeypatch)
    with pytest.raises(OSError):
        svc.add_donation(5.0, "Sam", idempotency_key="k2")
    _booked(ps, "k2")
    writer(svc)

    svc.add_donation(2.0, "Kim", idempotency_key="k3")

    assert _total_on_disk(ps, "m2") == expected, "the $5 donation stayed missing from the mech"


def test_a_healthy_ledger_is_never_rebuilt(ps, monkeypatch):
    """The heal must stay a heal: ordinary donations do not replay the whole log.

    Without this, a lag check that fires on healthy snapshots would rebuild on
    EVERY write - still the right total, so the tests above would stay green,
    but a full replay of the ledger each time.
    """
    svc = ps.ProgressService("m4")
    rebuilds = []
    real_rebuild = ps.ProgressService.rebuild_from_events
    monkeypatch.setattr(ps.ProgressService, "rebuild_from_events",
                        lambda self: rebuilds.append(1) or real_rebuild(self))

    svc.add_donation(10.0, "Alex", idempotency_key="k1")
    svc.update_member_count(30)
    svc.add_donation(2.0, "Kim", idempotency_key="k2")
    svc.add_donation(2.0, "Kim", idempotency_key="k2")   # an ordinary idempotent retry

    assert rebuilds == [], f"{len(rebuilds)} rebuild(s) of a ledger that lacked nothing"
    assert _total_on_disk(ps, "m4") == 1200
