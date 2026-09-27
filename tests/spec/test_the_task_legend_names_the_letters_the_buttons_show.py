# -*- coding: utf-8 -*-
"""The task legend explains the letters the delete buttons actually show.

THE FINDING (full catalogue review, 2026-09-27): the delete-task buttons in
cogs/task_ui.py always show the Latin letters O/D/W/M/Y. The legend under
them, "O = Once, D = Daily, W = Weekly, M = Monthly, Y = Yearly", had been
translated letters and all in most languages - Spanish "U = Una vez",
Serbian "Ј = Једном", Finnish with "K" twice - so it explained letters that
never appear. Every catalogue now keeps O/D/W/M/Y and translates the words.

Also held here: "OMEGA MECH", the name of the last mech level, is a name and
reads the same in every language (seven catalogues had translated it).

COUNTER-CHECK (2026-09-27): red before - about thirty legends and seven
OMEGA names.
"""

import json
import re
from pathlib import Path

import pytest

LOCALES = Path(__file__).resolve().parents[2] / "locales"
LEGEND = "O = Once, D = Daily, W = Weekly, M = Monthly, Y = Yearly"


def _catalogues():
    return sorted(p for p in LOCALES.glob("*.json") if p.stem != "meta")


def test_the_buttons_still_show_these_letters():
    source = (LOCALES.parent / "cogs" / "task_ui.py").read_text(encoding="utf-8")
    for letter in "ODWMY":
        assert f"'{letter}'" in source or f'"{letter}"' in source, letter


@pytest.mark.parametrize("path", _catalogues(), ids=lambda p: p.stem)
def test_the_legend_keeps_the_letters(path):
    text = json.loads(path.read_text(encoding="utf-8"))[LEGEND]
    missing = [letter for letter in "ODWMY" if not re.search(rf"(?<![A-Za-z]){letter} ?=", text)]
    assert not missing, f"{path.stem}: {text!r} lacks {missing}"


@pytest.mark.parametrize("path", _catalogues(), ids=lambda p: p.stem)
def test_omega_mech_is_a_name(path):
    assert json.loads(path.read_text(encoding="utf-8"))["OMEGA MECH"] == "OMEGA MECH"
