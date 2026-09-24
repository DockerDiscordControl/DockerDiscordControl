# -*- coding: utf-8 -*-
"""Resolving a group does not re-read every container file each time.

THE FINDING (independent review, 2026-09-23): a group resolves its members
against the containers DDC has, and that list comes from
ServerConfigService.get_all_servers(), which reloads every file under
config/containers/ on every call - by design, "always reload". Nothing cached
it, so:

* the watchdog's rule match resolves the group PER EVENT PER RULE
  (automation_service.process_container_events is a double loop);
* the admin overview asks whether a group exists on EVERY redraw, in every
  control channel, once a minute;
* the panel's group list and the Discord menu resolve once per group (N+1).

On this installation the config lives on an SMB-mounted array, and the bot
does this on its event loop. The first test measures it; the number it asserts
is what makes a regression visible.

COUNTER-CHECK (2026-09-23): red before - 20 events over 5 rules produced 100
reads of the container configuration instead of 1.
"""

import json

import pytest


@pytest.fixture
def counted(tmp_path, monkeypatch):
    """A group service whose reads of the container list are counted."""
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    containers = tmp_path / "containers"
    containers.mkdir()
    for name in ("Valheim", "alpha", "AdGuard-Home"):
        (containers / f"{name}.json").write_text(
            json.dumps({"container_name": name, "allowed_actions": ["status"]}),
            encoding="utf-8")

    from services.config import group_service, server_config_service

    group_service.reset_group_service()
    service = group_service.get_group_service()
    service.save_group("Gameserver", ["Valheim", "alpha"])

    reads = []
    real = server_config_service.ServerConfigService.get_all_servers

    def counting(self, *args, **kwargs):
        reads.append(1)
        return real(self, *args, **kwargs)

    monkeypatch.setattr(server_config_service.ServerConfigService, "get_all_servers", counting)
    return service, reads


def test_twenty_resolutions_do_not_cost_twenty_reads(counted):
    service, reads = counted

    for _ in range(20):
        service.members_of("Gameserver")

    assert len(reads) <= 2, (
        f"resolving a group 20 times read the container configuration {len(reads)} times; "
        f"the watchdog does this per event per rule, on the bot's loop")


def test_a_new_container_is_seen_without_a_restart(counted):
    """Counter-check: a cache that never expires is worse than the cost."""
    import time

    service, _reads = counted
    service.save_group("Gameserver", ["Valheim", "Newcomer"])
    assert service.members_of("Gameserver").missing == ["Newcomer"]

    from utils.config_paths import get_config_dir

    (get_config_dir() / "containers" / "Newcomer.json").write_text(
        json.dumps({"container_name": "Newcomer", "allowed_actions": ["status"]}),
        encoding="utf-8")
    time.sleep(1.1)

    assert service.members_of("Gameserver").missing == [], (
        "a container added while DDC runs stays invisible to the groups")


def test_the_groups_file_is_still_read_when_it_changes(counted):
    """Counter-check: a group saved by the OTHER process must be seen."""
    service, _reads = counted
    assert [g.name for g in service.get_groups()] == ["Gameserver"]

    from utils.config_paths import get_config_dir

    (get_config_dir() / "groups.json").write_text(json.dumps({"groups": [
        {"name": "Gameserver", "containers": ["Valheim"]},
        {"name": "Infrastruktur", "containers": ["AdGuard-Home"]}]}), encoding="utf-8")

    assert [g.name for g in service.get_groups()] == ["Gameserver", "Infrastruktur"], (
        "a group written by the bot is invisible to the panel, or the other way round")


@pytest.mark.asyncio
async def test_drawing_the_admin_overview_is_not_a_config_scan(counted, monkeypatch):
    """The overview is redrawn once a minute, in every control channel.

    It asks whether there is a group or a stack to offer, and that question
    used to walk the whole container configuration each time - on top of the
    walk the overview itself does.

    COUNTER-CHECK: with the cache removed this reads the configuration once per
    redraw; ten redraws then cost ten scans instead of one.
    """
    from types import SimpleNamespace

    import cogs.admin_overview as ao

    _service, reads = counted
    monkeypatch.setattr(ao, "get_status_cache_service",
                        lambda: SimpleNamespace(get=lambda name: None))
    reads.clear()

    for _ in range(10):
        ao.AdminOverviewView(SimpleNamespace(), 42, has_running_containers=True)

    assert len(reads) <= 2, (
        f"ten redraws of the admin overview scanned the container configuration "
        f"{len(reads)} times")
