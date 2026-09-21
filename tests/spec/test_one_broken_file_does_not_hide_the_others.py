# -*- coding: utf-8 -*-
"""One unreadable file in containers/ does not hide the container next to it.

THE FINDING (review D19, pass 2, section 18 F5): when a container's info is
not under `<name>.json`, all three methods fall back to scanning the whole
directory and reading every file to look for a matching `container_name`,
`docker_name` or `name`:

    for file in self.containers_dir.glob("*.json"):
        with open(file, 'r', encoding='utf-8') as f:
            data = json.load(f)

Neither the open nor the parse is guarded. One unreadable file - a half-written
legacy leftover, a hand-edited one, a file the bot cannot read - raises out of
the loop, and the method's own handler turns that into "not found" or a failed
save for a container whose own file is perfectly fine.

The scan reads files that belong to OTHER containers. A defect in one
container's file must not decide the fate of another's.
"""

import json

import pytest

from services.infrastructure.container_info_service import (
    ContainerInfo, ContainerInfoService)

WANTED = "valheim"


@pytest.fixture
def service(tmp_path, monkeypatch):
    """The wanted container is stored under a different file name, and a
    broken file sorts before it."""
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    containers = tmp_path / "containers"
    containers.mkdir(parents=True)
    (containers / "aaa_broken.json").write_text("{ this is not json", encoding="utf-8")
    (containers / "zzz_other_name.json").write_text(
        json.dumps({"docker_name": WANTED, "info": {"custom_text": "hello"}}),
        encoding="utf-8")
    return ContainerInfoService()


def _info(text):
    return ContainerInfo(enabled=True, show_ip=False, custom_ip="", custom_port="",
                         custom_text=text, protected_enabled=False,
                         protected_content="", protected_password="")


def test_the_container_is_still_found(service):
    result = service.get_container_info(WANTED)

    assert result.success
    assert result.data.custom_text == "hello", (
        "a broken file elsewhere in the directory hid a container that is there"
    )


def test_the_container_can_still_be_saved(service):
    result = service.save_container_info(WANTED, _info("changed"))

    assert result.success, f"the save failed over somebody else's file: {result.error}"

    stored = json.loads((service.containers_dir / "zzz_other_name.json")
                        .read_text(encoding="utf-8"))
    assert stored["info"]["custom_text"] == "changed"


def test_the_container_can_still_be_reset(service):
    assert service.delete_container_info(WANTED).success


def test_a_genuinely_absent_container_is_still_absent(service):
    """Counter-check: skipping the broken file must not invent a match."""
    result = service.get_container_info("not-configured-at-all")

    assert result.data.custom_text == ""


def test_the_broken_file_is_named_in_the_log(service, caplog):
    """The operator has a file that cannot be read - they should hear it."""
    import logging

    with caplog.at_level(logging.DEBUG):
        service.get_container_info(WANTED)

    assert any("aaa_broken" in record.getMessage() for record in caplog.records), (
        "a file in the container directory cannot be read and nothing says which"
    )
