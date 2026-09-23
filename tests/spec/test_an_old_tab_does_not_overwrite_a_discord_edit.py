# -*- coding: utf-8 -*-
"""A panel tab from before a Discord edit does not overwrite it in silence.

THE FINDING (independent review of the web panel, 2026-09-23, with the
diagnosis corrected here): the reviewer read this as a lock problem. It is not.
save_container_info_from_web builds the whole info block FROM THE FORM:

    ContainerInfo(enabled=..., custom_text=form_data.get(f'info_custom_text_{name}'), ...)

and the form carries the values the page was rendered with. So a container's
info text edited in Discord is reverted by ANY later panel save from a page
that was open before - deterministically, not only when the timing is unlucky.
A lock would have narrowed nothing.

    10:00  the page is opened; the form carries info "Port 25565"
    10:05  the operator edits the info in Discord to "Port 25566, modded"
    10:10  the operator saves something unrelated in that old tab
           -> the info is "Port 25565" again, and nothing says so

Operator decision (2026-09-23): warn instead of overwrite. The form carries a
VERSION MARKER per container - a short hash of the info block it was rendered
with. On save, a container whose info has changed since then is NOT written,
and the message names it.

The marker covers the INFO BLOCK, not the file: a panel save also writes the
container's allowed actions, so a whole-file marker would disagree with itself
on every ordinary save.

HOW THIS TEST CAN FAIL: it renders a form, changes the info behind its back,
saves, and reads what is on disk. The Discord edit being gone is red.

COUNTER-CHECK (2026-09-23): red before - the info was back to what the form
carried. The other tests keep the panel usable: an unchanged container is
written as before, a form with no marker at all (an older page, a script) is
still accepted, and the operator is told which container was left alone.
"""

import pytest

from app.utils.container_info_web_handler import (info_version_marker,
                                                  load_container_info_for_web,
                                                  save_container_info_from_web)
from services.infrastructure.container_info_service import (ContainerInfo,
                                                            get_container_info_service)

NAME = "minecraft"


@pytest.fixture
def info(tmp_path, monkeypatch):
    """A container whose info lives in a directory of its own."""
    import json

    service = get_container_info_service()
    containers = tmp_path / "containers"
    containers.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(service, "containers_dir", containers, raising=False)
    # save_container_info writes INTO an existing container file, so there has
    # to be one - the panel never creates a container here.
    (containers / f"{NAME}.json").write_text(
        json.dumps({"docker_name": NAME, "name": NAME, "allowed_actions": ["status"]}),
        encoding="utf-8")

    def write(text):
        result = service.save_container_info(NAME, ContainerInfo(
            enabled=True, show_ip=False, custom_ip="", custom_port="",
            custom_text=text, protected_enabled=False, protected_content="",
            protected_password=""))
        assert result.success, result.error

    write("Port 25565")
    return write


def _form_from_the_page():
    """The hidden inputs the template renders, marker included."""
    loaded = load_container_info_for_web([NAME])[NAME]
    return {
        f"info_enabled_{NAME}": "1",
        f"info_show_ip_{NAME}": "0",
        f"info_custom_ip_{NAME}": "",
        f"info_custom_port_{NAME}": "",
        f"info_custom_text_{NAME}": loaded.get("custom_text", ""),
        f"info_protected_enabled_{NAME}": "0",
        f"info_protected_content_{NAME}": "",
        f"info_protected_password_{NAME}": "",
        f"info_version_{NAME}": info_version_marker(loaded),
    }


def _on_disk():
    return get_container_info_service().get_container_info(NAME).data.to_dict()


def test_the_discord_edit_survives_a_save_from_an_old_tab(info):
    """THE FINDING: it was silently reverted to what the page carried."""
    form = _form_from_the_page()
    info("Port 25566, modded")          # the Discord edit, after the render

    save_container_info_from_web(form, [NAME])

    assert _on_disk()["custom_text"] == "Port 25566, modded", (
        "the panel wrote the text its page was rendered with, over an edit "
        "made in Discord in the meantime")


def test_the_operator_is_told_which_container_was_left_alone(info):
    """Silently refusing would be the same fault the other way round."""
    form = _form_from_the_page()
    info("Port 25566, modded")

    results = save_container_info_from_web(form, [NAME])

    assert results[NAME] is not True, (
        f"the refusal was reported as an ordinary save: {results}")
    assert NAME in str(results)


def test_an_unchanged_container_is_written_as_before(info):
    """Counter-check: the everyday save must not start refusing."""
    form = _form_from_the_page()
    form[f"info_custom_text_{NAME}"] = "Port 25565, whitelist on"

    results = save_container_info_from_web(form, [NAME])

    assert results[NAME] is True, results
    assert _on_disk()["custom_text"] == "Port 25565, whitelist on"


def test_a_form_without_a_marker_is_still_accepted(info):
    """Counter-check: an older page, or a script, must keep working."""
    form = _form_from_the_page()
    del form[f"info_version_{NAME}"]
    form[f"info_custom_text_{NAME}"] = "written without a marker"

    results = save_container_info_from_web(form, [NAME])

    assert results[NAME] is True, results
    assert _on_disk()["custom_text"] == "written without a marker"


def test_the_marker_ignores_what_is_not_the_info(info):
    """It must not change when something else about the container does.

    A panel save writes the allowed actions as well; a marker taken over the
    whole file would disagree with itself on every ordinary save.
    """
    first = info_version_marker(load_container_info_for_web([NAME])[NAME])
    service = get_container_info_service()
    path = service.containers_dir / f"{NAME}.json"
    import json

    data = json.loads(path.read_text(encoding="utf-8"))
    data["allowed_actions"] = ["start", "stop"]
    path.write_text(json.dumps(data), encoding="utf-8")

    assert info_version_marker(load_container_info_for_web([NAME])[NAME]) == first


def test_the_form_actually_carries_the_marker():
    """The CALL SITE, not the function.

    A marker the template never renders is a mechanism that is green in the
    tests and inert in the panel - the exact trap of testing a function while
    the fault sits beside it. Two halves have to meet: the loader has to put
    the marker in the info it hands the page, and the page has to render it
    under the name the save reads.
    """
    from pathlib import Path

    template = Path(__file__).resolve().parents[2] / "app/templates/_server_selection.html"
    markup = template.read_text(encoding="utf-8")

    assert 'name="info_version_{{ container.name }}"' in markup, (
        "the form does not carry the version marker, so nothing in the panel "
        "can ever notice an edit made elsewhere")
    assert "info_config.get('_version'" in markup, (
        "the marker is rendered from something other than the loaded info")


def test_the_loader_hands_the_marker_to_the_page(info):
    """The other half: the page can only render what it is given."""
    loaded = load_container_info_for_web([NAME])[NAME]

    assert loaded.get("_version") == info_version_marker(loaded), (
        f"the loaded info carries no usable marker: {loaded.get('_version')!r}")
