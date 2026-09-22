# -*- coding: utf-8 -*-
"""The container's info text has a limit too - at the save, and at the embed.

THE FINDING, the other half of review D18: protected_content and
protected_password are cut to their documented limit when they are saved
(test_a_shortened_info_text_says_so.py), but custom_text - the info text
shown to everybody - is cut nowhere on the server. The web form's
maxlength=250 is a suggestion to the browser, and the save path passes the
field through untouched, so a longer text is stored in full.

That text is put into the info embed's DESCRIPTION. Discord refuses a
description longer than 4096 characters, so a long info text does not show
up shortened - the Info button answers with an error and the container's
info cannot be read at all.

Both ends are closed: the save shortens once and says so (the same
enforcement point as the other two fields), and the embed builder cuts what
it was given, because a file written by hand or by an older version can
still hold more.

COUNTER-CHECK (2026-09-22): red before - a 5,000-character info text was
stored in full and built a 5,0xx-character description.
"""

import asyncio
import json
import logging
from types import SimpleNamespace

import pytest

from services.infrastructure.container_info_service import (MAX_CUSTOM_TEXT, ContainerInfo,
                                                            ContainerInfoService)

LONG = "x" * 5000


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    containers = tmp_path / "containers"
    containers.mkdir(parents=True)
    (containers / "web.json").write_text(json.dumps({"docker_name": "web", "info": {}}), encoding="utf-8")
    return ContainerInfoService()


def _info(**overrides):
    fields = dict(enabled=True, show_ip=False, custom_ip="", custom_port="", custom_text="",
                  protected_enabled=False, protected_content="", protected_password="")
    fields.update(overrides)
    return ContainerInfo(**fields)


def test_the_save_shortens_the_info_text_and_says_so(service, caplog):
    with caplog.at_level(logging.DEBUG):
        service.save_container_info("web", _info(custom_text=LONG))

    stored = json.loads((service.containers_dir / "web.json").read_text(encoding="utf-8"))
    assert len(stored["info"]["custom_text"]) == MAX_CUSTOM_TEXT
    assert [r for r in caplog.records if r.levelno >= logging.WARNING], (
        "the operator's info text was shortened and nothing says so")


def test_an_ordinary_info_text_is_untouched(service, caplog):
    with caplog.at_level(logging.DEBUG):
        service.save_container_info("web", _info(custom_text="Password: hunter2"))

    stored = json.loads((service.containers_dir / "web.json").read_text(encoding="utf-8"))
    assert stored["info"]["custom_text"] == "Password: hunter2"
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def _embed_of(monkeypatch, stored_text):
    """The info embed as the Info button builds it, for a file holding
    ``stored_text`` - written by hand or by an older version."""
    from cogs.status_info_integration import StatusInfoButton

    info = {"enabled": True, "custom_text": stored_text, "show_ip": False,
            "protected_enabled": False, "protected_content": "", "protected_password": ""}
    monkeypatch.setattr("services.infrastructure.container_info_service.get_container_info_service",
                        lambda: SimpleNamespace(get_container_info=lambda name: SimpleNamespace(
                            success=True, data=SimpleNamespace(to_dict=lambda: dict(info)))))
    button = object.__new__(StatusInfoButton)
    button.container_name = "web"
    button.server_config = {"docker_name": "web", "name": "web"}
    button.info_config = dict(info)
    button.cog = SimpleNamespace()
    return asyncio.run(button._generate_info_embed())


def test_a_long_text_from_an_old_file_still_builds_an_embed(monkeypatch):
    embed = _embed_of(monkeypatch, LONG)
    assert len(embed.description) <= 4096, (
        f"{len(embed.description)} characters - Discord refuses the embed and the Info "
        f"button answers with an error instead of the container's info")
    assert embed.description.startswith("x")


def test_a_short_text_reaches_the_embed_whole(monkeypatch):
    embed = _embed_of(monkeypatch, "Password: hunter2")
    assert "Password: hunter2" in embed.description
