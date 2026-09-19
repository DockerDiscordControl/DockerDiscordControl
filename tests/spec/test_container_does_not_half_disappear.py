# -*- coding: utf-8 -*-
"""A container must not exist on one path and be missing on the other.

NO ``@covers`` marker: that would be a new guarantee, and guarantees are the
operator's decision.

THE FINDING (stage 2, item 2 - silent removal). The same files under
``config/containers/*.json`` are evaluated by TWO readers, with opposite
defaults for a missing ``active`` key::

    services/config/server_config_service.py:90   container_data.get('active', True)
    services/config/config_loader_service.py:274  container_config.get('active', False)

That they are the same files is proven: ``server_config_service.py:46-47``
builds ``Path(__file__).parents[2] / 'config' / 'containers'``, the loader
gets ``containers_dir`` from ``ConfigService:200`` - both end up at
``<project>/config/containers``.

THE CONSEQUENCE: a container file without ``active`` is there for one reader
and gone for the other. ``config_loader_service.py:204`` fills
``config['servers']`` with it, and ``cogs/docker_control.py:1046`` looks up
the server configuration exactly there. ``get_all_servers()``, on the other
hand, feeds about a dozen call sites in ``docker_control.py``,
``status_info_integration.py`` and the info dialogs. The loss is announced by
a single ``logger.debug`` line ("Skipping inactive container") - in normal
operation DDC logs at INFO, so the line appears nowhere.

WHERE THE KEY CAN BE MISSING - measured, not assumed:
``config_migration_service.py:230`` writes ``save_json_func(container_file,
server)``, i.e. the legacy entry from ``docker_config.json`` VERBATIM. The
word ``active`` does not occur in that file even once; nor in
``services/infrastructure/container_info_service.py``, which also writes
container files. And the project data itself knows the shape without the key:
``tests/unit/audit_2026_09/test_r2_g2_config_fold.py:205`` uses
``{"servers": [{"docker_name": "web"}], ...}`` as a monolithic v1.1.x
configuration.

WHAT THIS TEST DOES NOT DECIDE: which of the two defaults is right. There are
good reasons for both, and the choice is an operator decision, not mine. The
only thing checked is that the two paths AGREE - because a container that is
half there is an error under any reading.

The convention "missing means active" is, however, the better documented side:
``server_config_service.py:89`` and ``cogs/admin_overview.py:463`` spell it out
as a comment, and two tests pin it down
(``tests/unit/audit_2026_09/test_pkg_b_admin_overview.py:74`` with a container
named ``no_active_field``, ``test_config_full.py:1027-1033``). There is no such
test for ``config_loader_service.py:274``: the apparent counter-evidence
``test_config_service.py:378`` writes EXCLUSIVELY files with an explicit
``active`` (:361-373) and says nothing about the missing key.

A MISTAKE OF MY OWN, recorded here because it repeated itself twice: I first
claimed that the loader side was untested (searching for the FUNCTION NAME,
while the tests go through ``get_config()``), then the opposite (reading the
DOCSTRING instead of the input). Only the fixture lines settled it. Both times
the same pattern: believing something about a test without looking at what it
is fed with.

COUNTER-CHECK (performed 2026-09-17) - two measurements, because two different
things had to be proven:

*1. The finding test was red BEFORE the fix*, with exactly the predicted
split::

    only via get_all_servers():   ['without_key']
    only via config['servers']:   []

The log confirms the cause instead of claiming it: "Real modular config
loaded: 1 servers" - the loader saw only ONE of the two files, although both
lay in the same directory. The positive control was green at the time, so the
difference did not come from two different directories. After the fix: 2
green.

*2. The positive control was green from the start* - so until proven
otherwise a test that cannot fail. But it is the one that makes the finding
test meaningful at all: if the two readers one day pointed to different
directories, the finding test would find a difference that means nothing.
Mutation: ``if False and container_config.get(...)``, so the loader returns
nothing at all::

    with mutation -> 2 failed, 0 passed

The control turned red at ITS own line (:218,
``assert WITH_KEY in via_loader`` -> ``assert 'with_key' in
set()``), with "Loaded 0 active containers for Discord" in the log. The second
red is the explainable knock-on effect: a blind loader necessarily also tips
the set comparison. Mutation reverted, afterwards 2 green again.

*Four ways in which this red would have been worthless* were fixed BEFORE the
run and none of them occurred: control stays green (would be hollow); it fails
on the wiring assertion (the mutation touches no paths); it fails on the
ServerConfigService side (the mutation does not reach there); collection or
import error (measures nothing).

AFFECTED GROUPS, all measured green: services/configuration 152,
audit_2026_09 564, cogs 267, services/web 358, services/scheduler 196,
test_container_info_service.py 14, extended 731, app_modules 73, spec 79.
"""

import json

import pytest

from services.config.config_loader_service import LEGACY_FOLD_MARKER, ConfigLoaderService
from services.config.config_service import get_config_service
from services.config.server_config_service import ServerConfigService

WITH_KEY = "with_key"
WITHOUT_KEY = "without_key"


@pytest.fixture
def both_readers(tmp_path, monkeypatch):
    """Point both container readers at THE SAME throwaway directory.

    ConfigService: redirect the paths and rebuild ``_loader_service`` - without
    the rebuild the loader keeps reading at the paths it was built with in the
    constructor. Then clear the caches, otherwise a result from an earlier test
    colours this run green. Taken from
    ``tests/unit/services/configuration/test_config_service.py:41``.

    ServerConfigService: via ``DDC_CONFIG_DIR``. Until 2026-09-19 it ignored
    the variable, and so its ``__file__`` was redirected to a fake file here;
    since then it reads utils.config_paths.get_config_dir()
    (test_config_dir_containers_and_channels.py). So the REAL body still runs,
    not a replica.
    """
    config_dir = tmp_path / "config"
    containers_dir = config_dir / "containers"
    containers_dir.mkdir(parents=True)
    (config_dir / "channels").mkdir()
    (config_dir / "config.json").write_text(json.dumps({"language": "de"}), encoding="utf-8")
    # Fold marker: prevents the one-time conversion from rewriting files in
    # the middle of the test.
    (config_dir / LEGACY_FOLD_MARKER).write_text("{}", encoding="utf-8")

    # Positive control: this file MUST show up on both paths. If it does not,
    # the fixture is broken, not the code.
    (containers_dir / f"{WITH_KEY}.json").write_text(json.dumps({
        "container_name": WITH_KEY, "active": True, "order": 1,
    }), encoding="utf-8")
    # The disputed case: no 'active' key.
    (containers_dir / f"{WITHOUT_KEY}.json").write_text(json.dumps({
        "container_name": WITHOUT_KEY, "order": 2,
    }), encoding="utf-8")

    service = get_config_service()
    saved_state = dict(service.__dict__)

    service.config_dir = config_dir
    service.channels_dir = config_dir / "channels"
    service.containers_dir = containers_dir
    service.main_config_file = config_dir / "config.json"
    service.auth_config_file = config_dir / "auth.json"
    service.heartbeat_config_file = config_dir / "heartbeat.json"
    service.web_ui_config_file = config_dir / "web_ui.json"
    service.docker_settings_file = config_dir / "docker_settings.json"
    service.bot_config_file = config_dir / "bot_config.json"
    service.docker_config_file = config_dir / "docker_config.json"
    service.web_config_file = config_dir / "web_config.json"
    service.channels_config_file = config_dir / "channels_config.json"
    service._loader_service = ConfigLoaderService(
        service.config_dir, service.channels_dir, service.containers_dir,
        service.main_config_file, service.auth_config_file, service.heartbeat_config_file,
        service.web_ui_config_file, service.docker_settings_file, service.bot_config_file,
        service.docker_config_file, service.web_config_file, service.channels_config_file,
        service._load_json_file, service._validation_service,
    )
    service._cache_service.invalidate_cache()
    service._cache_service.clear_token_cache()

    # Point ServerConfigService at the same directory.
    monkeypatch.setenv("DDC_CONFIG_DIR", str(config_dir))

    try:
        yield type("Readers", (), {
            "config_dir": config_dir,
            "containers_dir": containers_dir,
            "service": service,
        })
    finally:
        service._cache_service.invalidate_cache()
        service.__dict__.clear()
        service.__dict__.update(saved_state)


def _via_the_loader(service) -> set:
    """Names from config['servers'] - the path with default False."""
    configuration = service.get_config(force_reload=True)
    return {s.get("container_name") or s.get("docker_name")
            for s in configuration.get("servers", [])}


def _via_the_server_service() -> set:
    """Names from get_all_servers() - the path with default True."""
    return {s.get("docker_name") for s in ServerConfigService().get_all_servers()}


def test_both_readers_see_the_same_directory(both_readers):
    """Positive control against a blunt tool.

    If one of the two readers points elsewhere, the test below says nothing:
    it would then find a difference that only comes from two different
    directories. Exactly this way a test in this programme once ran against
    the real configuration instead of against the throwaway directory.
    """
    assert both_readers.service._loader_service.containers_dir == both_readers.containers_dir

    via_loader = _via_the_loader(both_readers.service)
    via_service = _via_the_server_service()

    assert WITH_KEY in via_loader, (
        f"The loader does not see the positive control: {sorted(via_loader)}. "
        "Then it does not point to the throwaway directory."
    )
    assert WITH_KEY in via_service, (
        f"The ServerConfigService does not see the positive control: "
        f"{sorted(via_service)}. Probably the redirection of __file__ does not take effect."
    )


def test_container_without_active_does_not_disappear_on_one_path(both_readers):
    """THE FINDING: the same file, two answers.

    What is NOT checked is WHICH default applies - that is the operator's
    decision. What is checked is that both paths give the same answer. A
    container that is half there is an error under any reading.
    """
    via_loader = _via_the_loader(both_readers.service)
    via_service = _via_the_server_service()

    only_in_service = via_service - via_loader
    only_in_loader = via_loader - via_service

    assert not (only_in_service or only_in_loader), (
        "The same files under config/containers/ yield two different "
        "container lists.\n"
        f"  only via get_all_servers():   {sorted(only_in_service)}\n"
        f"  only via config['servers']:   {sorted(only_in_loader)}\n"
        "Cause: server_config_service.py:90 assumes True for a missing 'active', "
        "config_loader_service.py:274 assumes False. So the container is "
        "there for some callers and gone for others - reported only by a "
        "logger.debug line that appears nowhere in normal operation (INFO)."
    )
