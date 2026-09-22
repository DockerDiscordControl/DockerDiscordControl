# -*- coding: utf-8 -*-
"""A save does not wipe the info of a container the page never showed.

THE FINDING: when the configuration is saved, every container file whose name
is not among the ACTIVE containers gets its info fields cleared - and "active"
means "ticked in the table that was rendered". The table shows the containers
Docker currently lists, truncated to DDC_MAX_CONTAINERS_DISPLAY (100 by
default, settable to 1). A container that exists as a file but was not on the
page - the display limit, a container not in Docker's list at that moment -
was therefore treated exactly like one the operator had switched off: its
custom text, IP, port, and (because the clearing loop does not even name them,
so they fall back to empty) its protected content and password were saved away.

A rendered row always carries every info field as a hidden input, so the page
is the one place that knows what the operator meant. Containers it never
showed are left alone.

COUNTER-CHECK (2026-09-22): red before - the untouched container's text and
protected content came back empty.
"""

import json

import pytest

from services.web.configuration_save_service import info_fields_to_write


def _rendered(name, text="the text", protected="secret"):
    """The hidden inputs a rendered row carries (app/templates/_server_selection.html)."""
    return {
        f"info_enabled_{name}": "1",
        f"info_show_ip_{name}": "0",
        f"info_custom_ip_{name}": "10.0.0.5",
        f"info_custom_port_{name}": "7777",
        f"info_custom_text_{name}": text,
        f"info_protected_enabled_{name}": "1",
        f"info_protected_content_{name}": protected,
        f"info_protected_password_{name}": "pw",
    }


def test_a_container_that_was_not_on_the_page_is_not_written_at_all():
    form = _rendered("shown")
    names, form_out = info_fields_to_write(dict(form), ["shown", "offscreen"], ["shown"])

    assert names == ["shown"], "a container the page never showed was written"
    assert f"info_custom_text_offscreen" not in form_out


def test_a_container_the_operator_switched_off_is_cleared():
    form = _rendered("dropped")
    names, form_out = info_fields_to_write(dict(form), ["dropped"], [])

    assert names == ["dropped"]
    assert form_out["info_enabled_dropped"] == "0"
    assert form_out["info_custom_text_dropped"] == ""


def test_an_active_container_keeps_what_the_row_carries():
    """Counter-check: the clearing must not reach a ticked container."""
    form = _rendered("kept")
    names, form_out = info_fields_to_write(dict(form), ["kept"], ["kept"])

    assert names == ["kept"]
    assert form_out["info_custom_text_kept"] == "the text"
    assert form_out["info_protected_content_kept"] == "secret"


def test_the_protected_fields_are_cleared_too_when_it_is_cleared():
    """If a container IS cleared, it is cleared honestly - not half of it, with
    the rest falling back to empty because nobody named it."""
    form = _rendered("dropped")
    _names, form_out = info_fields_to_write(dict(form), ["dropped"], [])

    assert form_out["info_protected_enabled_dropped"] == "0"
    assert form_out["info_protected_content_dropped"] == ""
    assert form_out["info_protected_password_dropped"] == ""


def test_the_file_of_an_unseen_container_is_untouched_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    containers = tmp_path / "containers"
    containers.mkdir()
    (containers / "offscreen.json").write_text(json.dumps({
        "docker_name": "offscreen",
        "info": {"enabled": True, "custom_text": "do not lose me",
                 "protected_enabled": True, "protected_content": "nor me",
                 "protected_password": "pw"}}), encoding="utf-8")

    from app.utils.container_info_web_handler import save_container_info_from_web
    from services.infrastructure.container_info_service import ContainerInfoService

    names, form_out = info_fields_to_write(_rendered("shown"), ["shown", "offscreen"], ["shown"])
    save_container_info_from_web(form_out, names)

    stored = json.loads((containers / "offscreen.json").read_text(encoding="utf-8"))["info"]
    assert stored["custom_text"] == "do not lose me"
    assert stored["protected_content"] == "nor me"
