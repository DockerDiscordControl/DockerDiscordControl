# -*- coding: utf-8 -*-
# @covers Z2
"""Z2 - A test run never touches production data.

No test writes into the real ``config/``, regardless of which runner starts
it and regardless of whether ``DDC_CONFIG_DIR`` is set.

Why exactly this service: ``MechResetService`` is the only one in the project
that resolves its directory against the project root and ignores
``DDC_CONFIG_DIR``. ``tests/unit/services/mech/test_mech_data_services.py``
calls ``quick_mech_reset()`` for real - the reset overwrites
``mech_state.json``/``evolution_mode.json`` and deletes
``achieved_levels.json``. That nothing has broken so far was due solely to the
empty mount over ``/app/config`` in ``scripts/ddc_test.sh``. Anyone who starts
the suite differently (``scripts/run_tests_unraid.sh``, ``run_tests.sh``) does
not have this protection.

These tests deliberately perform NO reset operation. What is checked is the
path resolution - because that is exactly what decides where writes would go.
Triggering a real reset to see where it lands would be the bug itself.

COUNTER-CHECK (performed 2026-09-16): Before the fix in
``services/mech/mech_reset_service.py``, ``test_default_service_honours_ddc_config_dir``
and ``test_no_write_target_inside_repository`` failed - the service pointed at
``<repo>/config``. Green after the fix. The third test
(``test_explicit_relative_path_still_resolves_against_project``) was green
before and after and records that the fix does NOT change an explicitly passed
path.
"""

from pathlib import Path

import pytest

import services.mech.mech_reset_service as mrs_mod
from services.mech.mech_reset_service import MechResetService, get_mech_reset_service

# Project root: services/mech/mech_reset_service.py -> parents[2]
REPO_ROOT = Path(mrs_mod.__file__).resolve().parents[2]


@pytest.fixture
def isolated_singleton():
    """Save and restore the singleton.

    Without this, the test would leave behind an instance pointing at a temp
    directory for the rest of the run - exactly the kind of pollution the
    inventory named as a problem in this suite.
    """
    before = mrs_mod._mech_reset_service
    mrs_mod._mech_reset_service = None
    try:
        yield
    finally:
        mrs_mod._mech_reset_service = before


def _write_targets(service: MechResetService):
    """All files the service would touch."""
    return [
        service.mech_state_file,
        service.evolution_mode_file,
        service.achieved_levels_file,
    ]


def test_default_service_honours_ddc_config_dir(monkeypatch, tmp_path):
    """Constructed without an argument: DDC_CONFIG_DIR determines the directory."""
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))

    service = MechResetService()

    assert service.config_dir == tmp_path
    for target in _write_targets(service):
        assert target.parent == tmp_path, f"{target} is not under DDC_CONFIG_DIR"


def test_no_write_target_inside_repository(monkeypatch, tmp_path, isolated_singleton):
    """The path the tests actually take: through the singleton.

    ``quick_mech_reset()`` uses ``get_mech_reset_service()``. If that points at
    the repository, a test run destroys real data.
    """
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))

    service = get_mech_reset_service()

    for target in _write_targets(service):
        assert REPO_ROOT not in target.resolve().parents, (
            f"Write target {target} is inside the repository - a test run could "
            f"destroy real configuration"
        )


def test_explicit_relative_path_still_resolves_against_project():
    """An explicitly passed relative path stays unchanged.

    Records that the fix for Z2 only affects the default case.
    Mirrors ``test_mech_data_services.py:791`` - here because it marks the
    boundary of the guarantee.
    """
    service = MechResetService(config_dir="custom_cfg")

    assert service.config_dir.is_absolute()
    assert service.config_dir.name == "custom_cfg"
