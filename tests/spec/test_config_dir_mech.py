# -*- coding: utf-8 -*-
"""The mech files must be looked up in ``DDC_CONFIG_DIR``.

NO ``@covers`` marker: that would be a new guarantee, and those are the
operator's decision.

THE FINDING. Six mech places derive their files themselves and ignore the
variable::

    EvolutionConfigService       mech/evolution.json      parents[2] / "config"
    get_evolution_level_info     mech/decay.json          parents[2] / "config"
    MechStoryService             mech/stories/            parents[2] / "config"
    speed_levels (at import)     mech/speed_translations  parents[2] / "config"
    MechStateManager             mech_state.json          RELATIVE "config/..."
    progress_paths (fallback)    progress/                RELATIVE "config/progress"

MechStateManager already creates its file in the constructor (Z2), and the
relative path depends on the working directory. For progress_paths,
``DDC_PROGRESS_DATA_DIR`` and ``progress.data_dir`` from the configuration keep
precedence - only the last fallback changes, to the value that
docs/CONFIGURATION.md already names ("/app/config/progress").

A SEPARATE FINDING, NOT HANDLED HERE: evolution.json, decay.json, the stories
and speed_translations.json are NOT shipped with the image and were never in
the repository (config/* is in .gitignore). They exist on the operator's server
(as of 2025-11). What a fresh install shows without them is a product question
and has been put to the operator.

HOW IT IS CHECKED HERE: the test creates the files in the configured directory.
``speed_levels`` reads at IMPORT - so the test reloads the module and restores
it afterwards. progress_paths is checked via ``_resolve_base_dir``, bypassing
the cache - the cache stays untouched.
"""

import importlib
import json

import pytest

from services.mech import mech_evolutions, progress_paths, speed_levels
from services.mech.mech_state_manager import MechStateManager
from services.mech.mech_story_service import MechStoryService


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    target = tmp_path / "own_config"
    (target / "mech").mkdir(parents=True)
    monkeypatch.setenv("DDC_CONFIG_DIR", str(target))
    return target


def test_evolution_json_is_in_the_directory(config_dir):
    assert mech_evolutions.EvolutionConfigService().config_path == config_dir / "mech" / "evolution.json"


def test_the_decay_comes_from_the_directory(config_dir):
    (config_dir / "mech" / "decay.json").write_text(
        json.dumps({"levels": {"3": 250}, "default": 100}), encoding="utf-8")

    info = mech_evolutions.get_evolution_level_info(3)

    assert info is not None
    assert info.decay_per_day == pytest.approx(2.5), (
        "decay.json from DDC_CONFIG_DIR was not read (250 cents -> 2.50)."
    )


def test_the_stories_are_in_the_directory(config_dir):
    assert MechStoryService().story_dir == config_dir / "mech" / "stories"


def test_the_speed_translations_come_from_the_directory(config_dir):
    content = {"probe": {"de": "Probe"}}
    (config_dir / "mech" / "speed_translations.json").write_text(json.dumps(content), encoding="utf-8")
    reloaded = importlib.reload(speed_levels)
    assert reloaded.SPEED_TRANSLATIONS == content, (
        "speed_translations.json from DDC_CONFIG_DIR was not read."
    )


@pytest.fixture(autouse=True)
def _restore_speed_levels():
    """Reload after every test - autouse is set up first and torn down last,
    i.e. AFTER monkeypatch has reset the environment."""
    yield
    importlib.reload(speed_levels)


def test_the_mech_state_is_in_the_directory(config_dir):
    """Z2 part: the constructor creates the file."""
    manager = MechStateManager()

    assert manager.state_file == str(config_dir / "mech_state.json")
    assert (config_dir / "mech_state.json").exists()


def test_progress_falls_back_to_the_directory(config_dir, monkeypatch):
    monkeypatch.delenv("DDC_PROGRESS_DATA_DIR", raising=False)
    monkeypatch.setattr(progress_paths, "_config_base_dir", lambda: None)

    assert progress_paths._resolve_base_dir() == config_dir / "progress"


def test_the_own_progress_variable_keeps_precedence(config_dir, tmp_path, monkeypatch):
    """Scope."""
    own = tmp_path / "progress_only"
    monkeypatch.setenv("DDC_PROGRESS_DATA_DIR", str(own))

    assert progress_paths._resolve_base_dir() == own
