# -*- coding: utf-8 -*-
"""A container whose file cannot be read must not look like one that was removed.

THE FINDING (review E33, services/config/server_config_service.py): the same
sentence as review E28, one directory across. ``_load_container_configs`` walks
``config/containers/*.json`` and builds the server list that the whole status
display is drawn from. A file that cannot be read is logged and **skipped**, so
the container simply is not in the list - and "not in the list" is exactly what
a container the operator switched off looks like.

What that costs: the container vanishes from ``/serverstatus``, from the
overview embed, from the control panel. No red dot, no "not found" marker -
gone. The operator sees six containers where there were seven and has to work
out which one is missing and why.

A root-owned file is not hypothetical here; it is the same cause as review E21
and the reason every ``docker exec`` on this install runs ``-u ddc``.

The per-file errors were already logged and they name the cause. What was
missing is the effect, and that is the part an operator can act on. Said once,
with the count, the names and the sentence that nothing was deleted.
"""

import json
import logging

import pytest


@pytest.fixture
def service(tmp_path, monkeypatch):
    import services.config.server_config_service as module
    from services.config.server_config_service import ServerConfigService

    containers = tmp_path / "containers"
    containers.mkdir()
    monkeypatch.setattr("utils.config_paths.get_config_dir", lambda: tmp_path)

    instance = ServerConfigService.__new__(ServerConfigService)
    instance._cache = None
    return instance, containers


def _write(directory, name, active=True):
    (directory / f"{name}.json").write_text(json.dumps({
        "docker_name": name, "active": active, "allowed_actions": ["status"],
    }))


def test_the_readable_containers_still_come_back(service, caplog):
    instance, containers = service
    _write(containers, "minecraft")
    (containers / "valheim.json").write_text("{ this is not json")

    with caplog.at_level(logging.DEBUG):
        servers = instance.get_all_servers()

    names = [s.get("docker_name") for s in servers]
    assert "minecraft" in names, "a readable container was lost with the broken one"


def test_the_loss_is_stated_with_its_consequence(service, caplog):
    instance, containers = service
    _write(containers, "minecraft")
    (containers / "valheim.json").write_text("{ this is not json")

    with caplog.at_level(logging.DEBUG):
        instance.get_all_servers()

    errors = " ".join(r.getMessage() for r in caplog.records
                      if r.levelno >= logging.ERROR)
    assert errors, "nothing was logged at ERROR at all"
    assert "valheim" in errors.lower(), f"the file is not named: {errors!r}"
    assert "status" in errors.lower() or "display" in errors.lower(), (
        f"the CONSEQUENCE is not named - the container is gone from the status "
        f"display, and that is the part worth saying: {errors!r}"
    )


def test_an_inactive_container_is_not_an_error(service, caplog):
    """Counter-check: switched off is a state, not a failure."""
    instance, containers = service
    _write(containers, "minecraft")
    _write(containers, "valheim", active=False)

    with caplog.at_level(logging.DEBUG):
        servers = instance.get_all_servers()

    assert [s.get("docker_name") for s in servers] == ["minecraft"]
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR], (
        "a container the operator switched off was reported as an error"
    )


def test_a_clean_directory_says_nothing_alarming(service, caplog):
    instance, containers = service
    _write(containers, "minecraft")
    _write(containers, "valheim")

    with caplog.at_level(logging.DEBUG):
        servers = instance.get_all_servers()

    assert len(servers) == 2
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
