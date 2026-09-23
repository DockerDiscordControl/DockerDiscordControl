# -*- coding: utf-8 -*-
"""Container groups: what the operator defines, and what DDC makes of it.

WHY THIS EXISTS (operator, 2026-09-23): DDC could only group containers by
their Docker compose project. Measured on the running server: 0 of 37
containers carry `com.docker.compose.project`, because Unraid does not create
containers with compose - so the whole feature did nothing there. Groups are
now defined in the panel, by hand, with names the operator chooses
("Gameserver", "Infrastruktur"), and they are meant to work everywhere:
the admin button, scheduled tasks, auto-actions.

This is the foundation: the file, the service, and the two rules that matter
for everything built on top -

* a group resolves to the containers DDC actually has. A name that is no
  longer configured is REPORTED, not silently dropped: a group of seven that
  quietly became six would restart six containers and say "done".
* the file is written the way every shared file in DDC is written - one
  read-modify-write under the cross-process lock, atomically - because the bot
  and the web panel are two processes.

COUNTER-CHECK (2026-09-23): red before - there was no group service at all.
Each test below states what it would let through if it were the only one.
"""

import json

import pytest


@pytest.fixture
def groups(tmp_path, monkeypatch):
    """The group service on a throwaway config directory with three containers."""
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    containers = tmp_path / "containers"
    containers.mkdir()
    for name in ("Valheim", "Icarus 1", "AdGuard-Home"):
        (containers / f"{name}.json").write_text(
            json.dumps({"container_name": name, "allowed_actions": ["status", "restart"]}),
            encoding="utf-8")

    from services.config import group_service

    group_service.reset_group_service()
    return group_service.get_group_service()


def test_a_group_is_kept(groups):
    groups.save_group("Gameserver", ["Valheim", "Icarus 1"])

    assert [g.name for g in groups.get_groups()] == ["Gameserver"]
    assert groups.members_of("Gameserver").containers == ["Valheim", "Icarus 1"]


def test_a_container_that_is_gone_is_reported_not_dropped(groups):
    groups.save_group("Gameserver", ["Valheim", "Enshrouded"])

    members = groups.members_of("Gameserver")

    assert members.containers == ["Valheim"]
    assert members.missing == ["Enshrouded"], (
        "a group that quietly shrinks would act on fewer containers and still "
        "report success")


def test_a_group_survives_a_second_service(groups, tmp_path):
    """Counter-check: it is written to disk, not kept in memory."""
    groups.save_group("Gameserver", ["Valheim"])

    from services.config import group_service

    group_service.reset_group_service()

    assert [g.name for g in group_service.get_group_service().get_groups()] == ["Gameserver"]
    assert (tmp_path / "groups.json").is_file()


def test_the_same_name_twice_is_refused(groups):
    """Counter-check: two groups with one name make every later choice ambiguous."""
    groups.save_group("Gameserver", ["Valheim"])

    result = groups.save_group("gameserver", ["Icarus 1"])

    assert result.success is False
    assert "gameserver" in result.error.lower()
    assert len(groups.get_groups()) == 1


def test_a_group_without_a_name_is_refused(groups):
    assert groups.save_group("   ", ["Valheim"]).success is False
    assert groups.get_groups() == []


def test_renaming_and_deleting(groups):
    groups.save_group("Gameserver", ["Valheim"])

    assert groups.save_group("Gameserver", ["Valheim", "Icarus 1"]).success is True
    assert groups.members_of("Gameserver").containers == ["Valheim", "Icarus 1"]
    assert groups.delete_group("Gameserver").success is True
    assert groups.get_groups() == []


def test_an_unknown_group_is_not_an_empty_one(groups):
    """Counter-check: "no such group" must not look like "a group of nothing"."""
    members = groups.members_of("does not exist")

    assert members.exists is False
    assert members.containers == []


def test_two_processes_do_not_lose_a_group(tmp_path, monkeypatch):
    """The bot and the panel are two processes; one must not overwrite the other.

    Same shape as the other two-process specs: the slower writer holds the file
    lock while the faster one arrives, so without the lock the second write
    would replace a file that never saw the first group.

    COUNTER-CHECK: with cross_process_lock replaced by nullcontext, the file
    holds one group instead of two.
    """
    import os
    import subprocess
    import sys
    import textwrap
    import time
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    (tmp_path / "containers").mkdir()
    (tmp_path / "containers" / "Valheim.json").write_text(
        json.dumps({"container_name": "Valheim"}), encoding="utf-8")

    writer = textwrap.dedent('''
        import sys, time
        sys.path.insert(0, {root!r})
        from services.config import group_service

        real_write = group_service.GroupService._write
        def slow_write(self, entries):
            time.sleep({delay})
            return real_write(self, entries)
        group_service.GroupService._write = slow_write

        group_service.get_group_service().save_group({name!r}, ["Valheim"])
    ''')

    def _start(name, delay):
        script = writer.format(root=str(root), name=name, delay=delay)
        return subprocess.Popen([sys.executable, "-c", script],
                                env=dict(os.environ, DDC_CONFIG_DIR=str(tmp_path)),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    slow = _start("Gameserver", 0.8)
    time.sleep(0.25)
    quick = _start("Infrastruktur", 0.0)
    for process in (slow, quick):
        assert process.wait(timeout=90) == 0, process.stderr.read()

    written = json.loads((tmp_path / "groups.json").read_text(encoding="utf-8"))["groups"]

    assert sorted(g["name"] for g in written) == ["Gameserver", "Infrastruktur"], (
        f"a group was overwritten: {written}")
