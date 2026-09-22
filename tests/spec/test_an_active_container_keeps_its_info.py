# -*- coding: utf-8 -*-
"""
THE FINDING (review C51, section 28 F5): a container that the operator just
submitted as active can have its info fields cleared, because two lists of the
same containers are built by two different rules.

    all_container_names:    container_data.get('container_name') or json_file.stem
    active_container_names: server.get('docker_name') or server.get('container_name')

Anything in the first list that is not in the second is treated as switched off
and its info fields are overwritten with empty values. So a container file
whose `container_name` differs from its `docker_name` appears under one name in
the first list and another in the second - and the operator's custom IP, port
and text are wiped on the next save.

Files written by DDC set both keys to the same value, which is why this is not
an everyday event. `migrate_containers_to_files` does not: it stores the
original server dict from `docker_config.json` under a file named after the
docker name, so the two can disagree from the migration onwards.

One rule for both lists now, and the docker name decides - that is the identity
the form fields are keyed by.

The counter-check keeps the clearing itself: a container that really was
switched off still has its info cleared.

2026-09-22: the forms below now carry the hidden info fields a rendered row
carries. Since
tests/spec/test_a_container_the_page_never_showed_keeps_its_info.py, only
containers the PAGE showed are written at all - a container the operator never
saw is neither cleared nor saved - and a form without those fields means "this
container was not on the page".
"""

import json

import pytest

from services.web.configuration_save_service import ConfigurationSaveService


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    (tmp_path / "containers").mkdir()
    instance = ConfigurationSaveService()
    instance.config_service = type("C", (), {
        "bot_config_file": "bot_config.json",
        "docker_config_file": "docker_config.json",
        "channels_config_file": "channels_config.json",
        "web_config_file": "web_config.json",
    })()
    return instance, tmp_path / "containers"


def _write(containers_dir, file_stem, data):
    (containers_dir / f"{file_stem}.json").write_text(json.dumps(data), encoding="utf-8")


def _saved_info(service, monkeypatch, processed, form_data):
    """Run the file-save step and report which names had their info cleared."""
    instance, _dir = service
    seen = {}

    import app.utils.container_info_web_handler as handler
    monkeypatch.setattr(handler, "save_container_configs_from_web", lambda servers: {})
    monkeypatch.setattr(handler, "save_container_info_from_web",
                        lambda form, names: seen.update({"form": dict(form),
                                                         "names": list(names)}) or {})
    monkeypatch.setattr(instance.config_service, "save_config", lambda data: True,
                        raising=False)
    import services.config.config_service as config_module
    monkeypatch.setattr(config_module, "save_config", lambda data: True, raising=False)
    instance._save_configuration_files(processed, form_data, config_split_enabled=False)
    return seen


def _row(name):
    """The hidden info inputs a rendered row carries."""
    return {f"info_enabled_{name}": "1", f"info_custom_text_{name}": "kept"}


def test_an_active_container_is_not_treated_as_switched_off(service, monkeypatch):
    """THE FINDING: the operator submitted it; do not wipe its info."""
    _instance, containers_dir = service
    # A file as the migration leaves it: named after the docker name, carrying a
    # different container_name inside.
    _write(containers_dir, "web", {"docker_name": "web", "container_name": "Web-Server"})

    seen = _saved_info(service, monkeypatch,
                       {"servers": [{"docker_name": "web"}]}, _row("web"))

    assert "info_enabled_Web-Server" not in seen.get("form", {}), (
        "an active container's info was cleared under its other name")
    assert seen.get("form", {}).get("info_custom_text_web") == "kept", (
        "an active container's info was cleared")


def test_a_container_that_was_switched_off_is_still_cleared(service, monkeypatch):
    """COUNTER-CHECK: the clearing is the point of this code."""
    _instance, containers_dir = service
    _write(containers_dir, "old", {"docker_name": "old", "container_name": "old"})

    seen = _saved_info(service, monkeypatch, {"servers": []}, _row("old"))

    assert seen.get("form", {}).get("info_enabled_old") == "0"


def test_every_container_still_gets_its_info_saved(service, monkeypatch):
    """COUNTER-CHECK: all containers are still passed on, active or not."""
    _instance, containers_dir = service
    _write(containers_dir, "web", {"docker_name": "web", "container_name": "web"})
    _write(containers_dir, "db", {"docker_name": "db", "container_name": "db"})

    form = {**_row("web"), **_row("db")}
    seen = _saved_info(service, monkeypatch, {"servers": [{"docker_name": "web"}]}, form)

    assert sorted(seen.get("names", [])) == ["db", "web"]
