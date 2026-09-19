# -*- coding: utf-8 -*-
"""The translated speed levels must be present on every installation.

NO ``@covers`` marker: that would be a new guarantee, and those are the
operator's decision. What was decided is the work: "ship it".

THE FINDING. ``config/mech/speed_translations.json`` existed only on the
operator's server. Without it, ``get_translated_speed_description`` returns the
English text for every language. This becomes visible wherever a language is
passed in: in the private detail view
(mech_status_details_service.py:117) and in mech_data_store.py:609.

WHAT IS DELIBERATELY NOT SHIPPED HERE, measured: ``evolution.json``. Its
level data is field-for-field identical to the hard-wired fallback (0
differences), the community levels are read only by ``calculate_dynamic_cost`` -
which has no caller - and the difficulty setting is the operator's personal
one. Shipping it would have had no effect.
The infinity message has the same fallback text in the code.

HOW IT IS CHECKED HERE: ``speed_levels`` reads at IMPORT time - reload against
an empty config directory, restore afterwards.
"""

import importlib
import json

import pytest

from services.mech import speed_levels


@pytest.fixture(autouse=True)
def _restore():
    yield
    importlib.reload(speed_levels)


@pytest.fixture
def fresh_install(tmp_path, monkeypatch):
    target = tmp_path / "empty_config"
    target.mkdir()
    monkeypatch.setenv("DDC_CONFIG_DIR", str(target))
    return target


def test_german_on_a_fresh_install(fresh_install):
    module = importlib.reload(speed_levels)
    assert module.get_translated_speed_description(5, "de") == "Todmüde schleppend", (  # language data
        "A fresh install has no translated speed levels."
    )


def test_english_stays_english(fresh_install):
    """Guard: the English text is the same in the file and in the fallback."""
    module = importlib.reload(speed_levels)
    assert module.get_translated_speed_description(5, "en") == "Excruciatingly lethargic"


def test_the_own_file_wins(fresh_install):
    (fresh_install / "mech").mkdir()
    (fresh_install / "mech" / "speed_translations.json").write_text(json.dumps(
        {"speed_descriptions": {"5": {"de": "Own"}}}), encoding="utf-8")

    module = importlib.reload(speed_levels)
    assert module.get_translated_speed_description(5, "de") == "Own"
