# -*- coding: utf-8 -*-
"""Protected info that is too long is shortened once, visibly, at the save.

THE FINDING (review D18, pass 2, section 18 F4): `ContainerInfo.from_dict`
sliced `protected_content` to 250 and `protected_password` to 60 characters
with nothing raised and nothing logged - while the two write paths build
`ContainerInfo(...)` directly and never truncate at all. The Discord modal
happens to cap its field at 250; the web handler does not, and an HTML
maxlength is a suggestion to the browser, not a rule for the server.

So the operator could save 300 characters, see them saved, and find 250 the
next time the panel loaded them - the reader had quietly shortened what the
writer had quietly kept. Saving again then made the loss permanent.

One enforcement point: the save shortens, once, and says so in the log. The
reader returns what is stored, because a reader that edits its data is how
the two came to disagree in the first place.
"""

import json
import logging

import pytest

from services.infrastructure.container_info_service import (
    ContainerInfo, ContainerInfoService)

# The limits the code has always documented, stated here so this file fails
# for the finding rather than for a name the code does not carry yet.
MAX_PROTECTED_CONTENT = 250
MAX_PROTECTED_PASSWORD = 60

LONG_TEXT = "x" * 400
LONG_PASSWORD = "y" * 120


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    containers = tmp_path / "containers"
    containers.mkdir(parents=True)
    (containers / "web.json").write_text(
        json.dumps({"docker_name": "web", "info": {}}), encoding="utf-8")
    return ContainerInfoService()


def _info(**overrides):
    fields = dict(enabled=True, show_ip=False, custom_ip="", custom_port="",
                  custom_text="", protected_enabled=True,
                  protected_content="short", protected_password="pw")
    fields.update(overrides)
    return ContainerInfo(**fields)


def test_the_save_shortens_and_says_so(service, caplog):
    with caplog.at_level(logging.DEBUG):
        service.save_container_info("web", _info(protected_content=LONG_TEXT))

    stored = json.loads((service.containers_dir / "web.json").read_text(encoding="utf-8"))
    assert len(stored["info"]["protected_content"]) == MAX_PROTECTED_CONTENT
    assert [r for r in caplog.records if r.levelno >= logging.WARNING], (
        "the operator's text was shortened and nothing says so"
    )


def test_the_password_has_its_own_limit(service):
    service.save_container_info("web", _info(protected_password=LONG_PASSWORD))

    stored = json.loads((service.containers_dir / "web.json").read_text(encoding="utf-8"))
    assert len(stored["info"]["protected_password"]) == MAX_PROTECTED_PASSWORD


def test_what_was_saved_is_what_comes_back(service):
    """The round trip is the promise: read what the save reported, not
    something the reader shortened on its own."""
    service.save_container_info("web", _info(protected_content=LONG_TEXT))

    first = service.get_container_info("web").data.protected_content
    service.save_container_info("web", _info(protected_content=first))
    second = service.get_container_info("web").data.protected_content

    assert first == second, "the value changed between two reads of the same file"
    assert len(first) == MAX_PROTECTED_CONTENT


def test_an_ordinary_text_is_untouched(service, caplog):
    """Counter-check: shortening everything would pass the tests above."""
    with caplog.at_level(logging.DEBUG):
        service.save_container_info("web", _info(protected_content="a normal note"))

    stored = json.loads((service.containers_dir / "web.json").read_text(encoding="utf-8"))
    assert stored["info"]["protected_content"] == "a normal note"
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_a_reader_returns_what_is_stored(service):
    """Counter-check, the other side: a file that already holds a longer value
    - written by an older version or by hand - is reported as it is, not
    silently trimmed on the way out."""
    path = service.containers_dir / "web.json"
    path.write_text(json.dumps({"docker_name": "web",
                                "info": {"protected_content": LONG_TEXT}}), encoding="utf-8")

    assert len(service.get_container_info("web").data.protected_content) == len(LONG_TEXT)
