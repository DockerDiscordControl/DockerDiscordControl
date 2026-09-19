# -*- coding: utf-8 -*-
"""The mech decay must be right even without an own ``decay.json``.

NO ``@covers`` marker: that would be a new guarantee, and guarantees are the
operator's decision. The work is decided: "ship it".

THE FINDING. ``config/mech/decay.json`` is not shipped with the image, and it
was never in the repository (``config/*`` in .gitignore) - it only existed on
the operator's server. Without it ``progress_service.decay_per_day`` takes 100
cents per day for EVERY level - including level 11 (OMEGA), which according to
the file AND the code comment in mech_evolutions.py ("IMMORTAL!") must not
decay. According to the file, levels 4-10 decay faster (120 to 200 cents).

THE FIX: the file is shipped as a read-only default
(``services/mech/defaults/decay.json``, copied byte for byte from the
operator's server, checksum compared). ``<config dir>/mech/decay.json``
remains an override and wins if it exists.

HOW IT IS CHECKED HERE: ``DDC_CONFIG_DIR`` points to an EMPTY directory -
exactly the situation of a fresh install. The cache of
``get_decay_config_data`` (10 s) is cleared before and after.
"""

import json

import pytest

from services.mech import mech_evolutions, progress_service


@pytest.fixture
def fresh_install(tmp_path, monkeypatch):
    target = tmp_path / "empty_config"
    target.mkdir()
    monkeypatch.setenv("DDC_CONFIG_DIR", str(target))
    progress_service._decay_config_cache.update({"data": None, "last_load": 0})
    try:
        yield target
    finally:
        progress_service._decay_config_cache.update({"data": None, "last_load": 0})


def test_omega_does_not_decay(fresh_install):
    """THE FINDING, in its sharpest form."""
    assert progress_service.decay_per_day(11) == 0, (
        "On a fresh install OMEGA (level 11) decays - without decay.json "
        "the default of 100 cents applies to every level."
    )


@pytest.mark.parametrize("level,cent", [(1, 100), (4, 120), (6, 150), (8, 180), (10, 200)])
def test_the_levels_decay_as_intended(fresh_install, level, cent):
    assert progress_service.decay_per_day(level) == cent


def test_the_level_info_reports_the_same_decay(fresh_install):
    """Second reader: get_evolution_level_info calculates in dollars."""
    assert mech_evolutions.get_evolution_level_info(10).decay_per_day == pytest.approx(2.0)


def test_an_own_file_wins(fresh_install):
    """Boundary: the operator's override stays effective."""
    (fresh_install / "mech").mkdir()
    (fresh_install / "mech" / "decay.json").write_text(
        json.dumps({"default": 100, "levels": {"11": 5}}), encoding="utf-8")

    assert progress_service.decay_per_day(11) == 5
