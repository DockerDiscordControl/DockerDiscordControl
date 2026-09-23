# -*- coding: utf-8 -*-
"""The groups section is on the page, and says what a group is worth.

The service and the routes are covered elsewhere; this is the part the
operator sees. What it has to get right:

* the section is INCLUDED in the configuration page and its script is loaded -
  a section nobody includes is a file, not a feature;
* a group that names containers DDC no longer has is marked in the list. The
  route reports them (test_the_panel_manages_container_groups.py); showing
  them is what makes the report worth anything;
* an empty group is marked too - it is the one group that does nothing;
* every text it shows exists in the catalogues, in English and German.

COUNTER-CHECK (2026-09-23): red before - there was no section, no script tag
and no translation key. The node cases are listed by count, so a rule that
quietly disappears from container_groups.js fails here.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SECTION = ROOT / "app" / "templates" / "_container_groups.html"

KEYS = ("web.groups.title", "web.groups.description", "web.groups.none_yet",
        "web.groups.name", "web.groups.containers", "web.groups.save",
        "web.groups.delete", "web.groups.saved", "web.groups.deleted",
        "web.groups.needs_name", "web.groups.missing", "web.groups.empty",
        "web.groups.load_failed", "web.groups.search_placeholder",
        "web.groups.select_all", "web.groups.select_none",
        "web.groups.chosen_count", "web.groups.no_match")


def test_the_section_is_on_the_configuration_page():
    page = (ROOT / "app" / "templates" / "config.html").read_text(encoding="utf-8")

    assert "_container_groups.html" in page, "the groups section is not included anywhere"


def test_the_script_is_loaded():
    scripts = (ROOT / "app" / "templates" / "_scripts.html").read_text(encoding="utf-8")

    assert "container_groups.js" in scripts, "the section's script is never loaded"


def test_the_section_asks_the_route_for_its_groups():
    js = (ROOT / "app" / "static" / "js" / "container_groups.js").read_text(encoding="utf-8")

    assert "'/api/groups'" in js
    assert "groupWarning(group" in js, "the list does not use the rule it was given"


@pytest.mark.parametrize("language", ["en", "de"])
def test_every_text_exists_in_the_catalogue(language):
    catalogue = json.loads((ROOT / "locales" / f"{language}.json").read_text(encoding="utf-8"))

    missing = [key for key in KEYS if not catalogue.get(key)]

    assert missing == [], f"{language}.json has no text for {missing}"


def test_the_german_texts_are_really_german():
    """Counter-check: copying English into de.json would pass the test above."""
    german = json.loads((ROOT / "locales" / "de.json").read_text(encoding="utf-8"))
    english = json.loads((ROOT / "locales" / "en.json").read_text(encoding="utf-8"))

    same = [key for key in KEYS if german[key] == english[key]]

    assert same == [], f"these are still the English texts: {same}"


def test_the_rules_hold_in_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed here - run tests/js/container_groups.test.js by hand")
    result = subprocess.run([node, str(ROOT / "tests" / "js" / "container_groups.test.js")],
                            capture_output=True, text=True, timeout=60)

    assert result.returncode == 0, result.stdout + result.stderr
    # 14 since 2026-09-23: six cases came with the picker (the search and the
    # count). The number is listed so a rule that quietly disappears from
    # container_groups.js fails here.
    assert result.stdout.count("ok   - ") == 14, result.stdout


def test_meta_json_holds_language_metadata_only():
    """meta.json is not a catalogue, and a bulk edit must not treat it as one.

    COUNTER-CHECK (2026-09-23): this is a repair, not a guess. Adding the
    group texts to every file matching locales/*.json put fifteen strings into
    meta.json, whose values must be objects - the language picker then raised
    "'str' object has no attribute 'get'" and the configuration page did not
    render at all. The group run found it; this test would have.
    """
    meta = json.loads((ROOT / "locales" / "meta.json").read_text(encoding="utf-8"))

    not_objects = [code for code, value in meta.items() if not isinstance(value, dict)]

    assert not_objects == [], f"meta.json holds non-metadata entries: {not_objects}"
    assert "en" in meta and meta["en"].get("name"), "meta.json lost its language list"


def test_saving_over_a_group_asks_first():
    """Saving REPLACES the containers of a group with that name.

    THE FINDING (independent review, 2026-09-23): adding an eighth container to
    a group of seven the obvious way - type the name, pick the container, save -
    left a group of ONE and reported "Group saved." in green. There was no
    confirmation on delete either.

    COUNTER-CHECK: the node cases cover the warning and the two cases that must
    NOT warn (a new name, and a group loaded into the form for editing).
    """
    js = (ROOT / "app" / "static" / "js" / "container_groups.js").read_text(encoding="utf-8")

    assert "replacementWarning(" in js, "saving over a group still replaces it silently"
    assert "confirm(question)" in js, "a group is deleted without asking"
    assert "loadIntoForm" in js, "a group cannot be opened for editing"


def test_the_containers_are_picked_with_checkboxes():
    """REVISITED 2026-09-23: the picker was a <select multiple>, where 26
    containers had to be Ctrl-clicked (Cmd on the operator's Mac) and one stray
    click cleared the whole selection without saying so. It is a checkbox list
    with a search box now, so a pick survives the next click.

    COUNTER-CHECK: the multi-select must be GONE, not merely hidden beside the
    new list - two pickers would disagree about what is chosen.
    """
    section = SECTION.read_text(encoding="utf-8")

    assert "<select multiple" not in section, "the old multi-select is still there"
    assert 'class="form-check-input group-container-box"' in section
    assert 'id="group-search"' in section
    assert 'id="group-chosen-count"' in section, "nothing says how many are picked"


def test_all_and_none_act_on_what_the_search_shows():
    """A button that ticked the containers the search hid would be a trap: the
    box says two names and the group gets twenty-six."""
    js = (ROOT / "app" / "static" / "js" / "container_groups.js").read_text(encoding="utf-8")

    assert "item && !item.hidden" in js, "All/None ignores the search"


@pytest.mark.parametrize("key", ["web.groups.edit", "web.groups.replace",
                                 "web.groups.confirm_delete"])
@pytest.mark.parametrize("language", ["en", "de"])
def test_the_new_texts_exist(language, key):
    catalogue = json.loads((ROOT / "locales" / f"{language}.json").read_text(encoding="utf-8"))

    assert catalogue.get(key), f"{language}.json has no text for {key}"
