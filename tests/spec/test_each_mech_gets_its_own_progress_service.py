# -*- coding: utf-8 -*-
"""A progress service belongs to the mech it was asked for.

THE FINDING (review D12, pass 2, section 24 F5): `get_progress_service`
caches ONE module-level instance and builds it only `if _progress_service is
None`, so the `mech_id` argument is honoured on the very first call in the
process and silently ignored ever after. A later caller asking for another
mech gets the first one's service - and with it the first one's ledger.

Today there is one mech, so nothing is wrong in the running application. What
was wrong is that the signature promised something it did not do, and that
`MechServiceAdapter` stores `self.mech_id` next to a progress service that
may carry a different one. The existing unit test wrote the defect down as
the contract: "Singleton: second call returns the FIRST instance, ignoring
new mech_id".
"""

import importlib
import json
from types import SimpleNamespace

import pytest

from services.mech.progress import reset_progress_runtime
from services.mech.progress_paths import clear_progress_paths_cache


@pytest.fixture
def progress(tmp_path, monkeypatch):
    monkeypatch.setenv("DDC_PROGRESS_DATA_DIR", str(tmp_path / "progress"))
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path / "config"))
    reset_progress_runtime()
    clear_progress_paths_cache()

    module = importlib.reload(importlib.import_module("services.mech.progress_service"))
    module.reset_progress_services()
    config = {"timezone": "UTC", "difficulty_bins": [0, 50],
              "level_base_costs": {str(level): 1000 for level in range(1, 12)},
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
        yield module
    finally:
        module.reset_progress_services()
        reset_progress_runtime()
        clear_progress_paths_cache()


def test_another_mech_gets_another_service(progress):
    first = progress.get_progress_service("alpha")
    second = progress.get_progress_service("beta")

    assert second.mech_id == "beta", (
        f"asked for 'beta' and got the service of {second.mech_id!r}"
    )
    assert first is not second


def test_their_ledgers_do_not_mix(progress):
    """The consequence that would matter: one mech's donation must not land
    in the other's total."""
    progress.get_progress_service("alpha").add_donation(10.0, donor="a")
    progress.get_progress_service("beta").add_donation(5.0, donor="b")

    assert progress.get_progress_service("alpha").get_state().total_donated == pytest.approx(10.0)
    assert progress.get_progress_service("beta").get_state().total_donated == pytest.approx(5.0)


def test_the_same_mech_keeps_the_same_service(progress):
    """Counter-check: it is still a cache, not a factory."""
    assert progress.get_progress_service("alpha") is progress.get_progress_service("alpha")


def test_the_default_is_still_main(progress):
    """Counter-check: the application asks without an argument."""
    assert progress.get_progress_service().mech_id == "main"
