# -*- coding: utf-8 -*-
"""A group can be renamed, and everything that points at it follows.

THE GAP (2026-09-24): there was no rename. Saving a group under a new name
creates a SECOND group - the dialog even warns about replacing one - and the
old one stays behind, still named by every task, rule and admin assignment
that used it. For a thing the operator names himself, in his own words, that
is a hole.

WHAT MAKES IT MORE THAN A STRING SWAP. A group's name is its identity in three
other files:

    config/tasks.json        a scheduled task holds the plain name and a flag
    config/auto_actions.json a rule holds "group:<name>" in its trigger and
                             in its action
    config/admins.json       an assignment holds "group:<name>"

A rename that moved only groups.json would leave all three pointing at a group
that no longer exists - and each of them fails QUIETLY: the task reports "the
group does not exist any more" once a night, the rule resolves to nobody, the
admin simply loses a menu entry. That is the same "act on fewer and say done"
this whole feature was built against.

So the rename carries them, and says how many it touched. It is not a
transaction - four files cannot be written as one - so the ORDER is the
safeguard: the references move first, and groups.json last. Interrupted in the
middle, a reference points at a name that does not exist YET, which the
existing "does not exist any more" handling already reports; the other order
would leave a renamed group nobody points at, silently.

WHAT IT REFUSES: an empty name, one that is too long, one with a slash (the
delete route takes the name as a path segment), and a name another group
already has - the same rules save_group applies, because a rename is a save of
the name.

HOW THIS TEST CAN FAIL: a rename that leaves a reference behind, one that
overwrites another group, or one that reports more than it moved.

COUNTER-CHECK (2026-09-24): red before - there was no rename_group at all.
"""

import json
from pathlib import Path

import pytest


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A group, a task, a rule and an assignment, all naming it."""
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    containers = tmp_path / "containers"
    containers.mkdir()
    for name in ("Icarus", "Icarus2"):
        (containers / f"{name}.json").write_text(json.dumps(
            {"container_name": name, "docker_name": name, "active": True,
             "allowed_actions": ["status"]}), encoding="utf-8")

    (tmp_path / "tasks.json").write_text(json.dumps({"tasks": [
        {"task_id": "t1", "container_name": "Icaruse", "target_is_group": True,
         "action": "restart", "cycle": "daily"},
        {"task_id": "t2", "container_name": "Icarus", "target_is_group": False,
         "action": "restart", "cycle": "daily"},
        # A CONTAINER that happens to carry the group's name. Only the flag
        # tells the two apart, and without this entry the check below could not
        # fail: nothing else in the file shares the name.
        {"task_id": "t3", "container_name": "Icaruse", "target_is_group": False,
         "action": "restart", "cycle": "daily"},
    ]}), encoding="utf-8")

    (tmp_path / "auto_actions.json").write_text(json.dumps({"rules": [
        {"id": "r1", "name": "watch",
         "trigger": {"type": "container_state", "containers": ["group:Icaruse", "Icarus"]},
         "action": {"type": "RESTART", "containers": ["group:Icaruse"]}},
    ]}), encoding="utf-8")

    (tmp_path / "admins.json").write_text(json.dumps({
        "discord_admin_users": ["111"],
        "admin_containers": {"111": ["group:Icaruse", "Icarus"]},
    }), encoding="utf-8")

    from services.config import group_service

    group_service.reset_group_service()
    service = group_service.get_group_service()
    service.save_group("Icaruse", ["Icarus", "Icarus2"],
                       active=True, allowed_actions=["status", "restart"])
    service.save_group("Other", ["Icarus"])
    return service


def _read(tmp_path, name):
    return json.loads((tmp_path / name).read_text(encoding="utf-8"))


def test_the_group_keeps_everything_but_its_name(world):
    result = world.rename_group("Icaruse", "Gameserver")

    assert result.success is True, result.error
    assert world.find("Icaruse") is None
    renamed = world.find("Gameserver")

    assert renamed is not None
    assert renamed.containers == ["Icarus", "Icarus2"]
    assert renamed.allowed_actions == ["status", "restart"]
    assert renamed.active is True


def test_a_scheduled_task_follows(world, tmp_path):
    """It holds the plain name, and only when it targets a group."""
    world.rename_group("Icaruse", "Gameserver")
    tasks = {task["task_id"]: task for task in _read(tmp_path, "tasks.json")["tasks"]}

    assert tasks["t1"]["container_name"] == "Gameserver"
    assert tasks["t2"]["container_name"] == "Icarus"
    assert tasks["t3"]["container_name"] == "Icaruse", (
        "a container that happens to share the group's name was renamed too")


def test_a_rule_follows_on_both_sides(world, tmp_path):
    """A rule names a group in what it watches AND in what it acts on."""
    world.rename_group("Icaruse", "Gameserver")
    rule = _read(tmp_path, "auto_actions.json")["rules"][0]

    assert rule["trigger"]["containers"] == ["group:Gameserver", "Icarus"]
    assert rule["action"]["containers"] == ["group:Gameserver"]


def test_an_admin_assignment_follows(world, tmp_path):
    world.rename_group("Icaruse", "Gameserver")
    assignment = _read(tmp_path, "admins.json")["admin_containers"]["111"]

    assert assignment == ["group:Gameserver", "Icarus"]


def test_it_says_how_much_it_moved(world):
    """The operator gets one sentence, not four files to check."""
    result = world.rename_group("Icaruse", "Gameserver")

    assert result.moved == {"tasks": 1, "rules": 2, "admins": 1}, result.moved


def test_a_name_another_group_has_is_refused(world):
    result = world.rename_group("Icaruse", "Other")

    assert result.success is False
    assert "Other" in (result.error or "")
    assert world.find("Icaruse") is not None, "the group was lost to a refused rename"


def test_the_name_rules_are_the_same_as_for_a_save(world):
    """A rename is a save of the name; it may not let through what save_group
    refuses."""
    for bad in ("", "   ", "a" * 81, "Media/TV"):
        result = world.rename_group("Icaruse", bad)

        assert result.success is False, bad
    assert world.find("Icaruse") is not None


def test_renaming_to_the_same_name_is_not_an_error(world):
    """Pressing save on an unchanged name must not read as a collision with
    itself."""
    result = world.rename_group("Icaruse", "Icaruse")

    assert result.success is True, result.error
    assert world.find("Icaruse") is not None


def test_a_group_that_is_gone_is_said_so(world):
    result = world.rename_group("Nothing", "Something")

    assert result.success is False
    assert "Nothing" in (result.error or "")


def test_the_references_move_before_the_group(world, tmp_path, monkeypatch):
    """THE ORDER IS THE SAFEGUARD. Four files are not one write: interrupted,
    a reference must point at a name that does not exist YET - which every
    caller already reports - rather than a renamed group nobody points at."""
    from services.config import group_service

    written = []
    real_write = group_service.GroupService._write

    def _explode(self, entries):
        written.append("groups")
        raise OSError("interrupted")

    monkeypatch.setattr(group_service.GroupService, "_write", _explode)
    result = world.rename_group("Icaruse", "Gameserver")

    assert result.success is False
    assert written == ["groups"], written
    # The references went first and are already on the new name.
    tasks = _read(tmp_path, "tasks.json")["tasks"]

    assert any(task["container_name"] == "Gameserver" for task in tasks)
    monkeypatch.setattr(group_service.GroupService, "_write", real_write)


# --- the way in: the panel ---------------------------------------------------

AUTH = {"Authorization": "Basic YWRtaW46YWRtaW4="}   # admin:admin


@pytest.fixture
def client(world, monkeypatch):
    from flask import Flask

    from app import auth as auth_module
    from app.blueprints.group_routes import group_bp

    monkeypatch.setattr(auth_module.auth, "verify_password_callback",
                        lambda user, password: "admin" if user and password else None)
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="rename", WTF_CSRF_ENABLED=False)
    app.register_blueprint(group_bp)
    return app.test_client()


def test_the_panel_can_rename(client):
    answer = client.post("/api/groups/Icaruse/rename", headers=AUTH,
                         json={"name": "Gameserver"})

    assert answer.status_code == 200, answer.get_data(as_text=True)
    body = answer.get_json()

    assert body["success"] is True
    assert body["moved"] == {"tasks": 1, "rules": 2, "admins": 1}, body


def test_a_refused_rename_says_why(client):
    answer = client.post("/api/groups/Icaruse/rename", headers=AUTH,
                         json={"name": "Other"})
    body = answer.get_json()

    assert answer.status_code == 400
    assert "Other" in body["error"]


def test_a_group_that_is_not_there_answers_404(client):
    answer = client.post("/api/groups/Nothing/rename", headers=AUTH,
                         json={"name": "Something"})

    assert answer.status_code == 404, answer.get_data(as_text=True)


def test_the_dialog_offers_it():
    """The editor loads a group to change its members; the name is the one
    thing it could not change."""
    import re

    root = Path(__file__).resolve().parents[2]
    editor = (root / "app" / "static" / "js" / "container_groups.js").read_text(encoding="utf-8")
    editor = re.sub(r"//[^\n]*", "", editor)

    assert "/rename" in editor, "nothing in the dialog renames a group"
    assert "ddc:groups-changed" in editor, (
        "a rename that does not announce itself leaves the table on the old name")
