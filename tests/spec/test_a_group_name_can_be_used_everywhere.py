# -*- coding: utf-8 -*-
"""A group name that DDC accepts is one it can also delete and match.

THREE FINDINGS from the independent review (2026-09-23), all in the same
place - what save_group() lets through:

* a name with "/" is stored and can never be deleted again. DELETE
  /api/groups/<name> is a path segment; Flask's default converter does not
  match "/", and %2F is decoded before routing. Verified against Flask: a name
  with a space answers 200, "Media%2FTV" answers 404 - and the 404 body is
  HTML, so the panel shows the bare word "Error". "Media/TV" would be an
  undeletable group;
* two names that differ only in their unicode form ("Café" typed as NFC and as
  NFD) are two groups that look identical in every menu, and find() on the
  wrong form answers "there is no group called Café";
* a container is tested stripped but stored unstripped, so " plex" via the API
  lands in `missing` for ever; and a container named twice in one group is
  acted on twice.

COUNTER-CHECK (2026-09-23): red before - all four names below were accepted
and stored as given.
"""

import json

import pytest


@pytest.fixture
def groups(tmp_path, monkeypatch):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    containers = tmp_path / "containers"
    containers.mkdir()
    for name in ("Valheim", "plex"):
        (containers / f"{name}.json").write_text(
            json.dumps({"container_name": name, "allowed_actions": ["status"]}),
            encoding="utf-8")

    from services.config import group_service

    group_service.reset_group_service()
    return group_service.get_group_service()


@pytest.mark.parametrize("name", ["Media/TV", "back\\slash", "with\nnewline", "tab\there"])
def test_a_name_that_would_break_a_path_or_a_menu_is_refused(groups, name):
    result = groups.save_group(name, ["Valheim"])

    assert result.success is False, f"{name!r} was accepted and could not be deleted again"
    assert groups.get_groups() == []


def test_an_ordinary_name_with_spaces_and_umlauts_is_fine(groups):
    """Counter-check: the refusal must stay narrow."""
    assert groups.save_group("Spiele Server (groß)", ["Valheim"]).success is True
    assert groups.find("Spiele Server (groß)") is not None


def test_two_unicode_spellings_are_one_group(groups):
    """NFC and NFD look identical in every menu; they must not be two groups."""
    nfc = "Café"            # é as one character
    nfd = "Café"           # e + combining accent

    assert groups.save_group(nfc, ["Valheim"]).success is True
    second = groups.save_group(nfd, ["plex"])

    assert second.success is True, "the same name in another spelling was refused"
    assert len(groups.get_groups()) == 1, "two groups nobody can tell apart"
    assert groups.find(nfd) is not None and groups.find(nfc) is not None


def test_a_container_is_stored_as_it_will_be_looked_up(groups):
    groups.save_group("Gameserver", [" Valheim ", "plex", "plex"])

    members = groups.members_of("Gameserver")

    assert members.containers == ["Valheim", "plex"], (
        f"stored as {members.containers} - a padded name never matches, "
        f"a doubled one is acted on twice")
    assert members.missing == []
