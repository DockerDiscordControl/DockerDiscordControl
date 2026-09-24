# -*- coding: utf-8 -*-
"""A group has its own permissions, not a view of its containers'.

THE OPERATOR'S CORRECTION (2026-09-24), after I built it the other way round
and showed it to him. He said it in German; in English it was:

    a group holds at least one container and as many as you like, and the
    group is decoupled from the single-container control. There can be a
    container that is not switched on for DDC at all, or that may only be
    stopped on its own - and the group it belongs to can have any other
    permissions.

So a group is not a shortcut for ticking boxes on its members, and not a
derived view of them either. It is a control of its own: it carries Active and
the four actions the way a container does, in its own file, and a member's own
settings neither limit it nor are changed by it.

WHAT WAS MEASURED BEFORE WRITING THIS (2026-09-24, the operator's server):
groups.json held `{"name": "Gameserver", "containers": ["alpha", "beta"]}` and
nothing else - there was nowhere to put a permission. The Discord group restart
in cogs/stack_restart.py dropped every member that was not active in DDC, and
offered restart and only restart, to every group. Both are the subordination
the operator is rejecting; this file is the first of four steps and covers the
storage.

THE DEFAULT IS NOT "NOTHING". A group written before today records no
permissions, and it could be restarted from Discord yesterday - every group
could, whatever its members said. Reading such a group as having no rights
would take a working button away from an operator who changed nothing, so it
reads as the four standard actions and Active. A group SAVED from now on says
what it has.

HOW THIS TEST CAN FAIL: dropping the fields on save, losing them on the
round-trip through the file, letting an invented action through, or reading an
old group as powerless.

COUNTER-CHECK (2026-09-24): red before - ContainerGroup had two fields, and
save_group took two arguments.
"""

import json

import pytest

ACTIONS = ("status", "start", "stop", "restart")


@pytest.fixture
def groups(tmp_path, monkeypatch):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    from services.config import group_service

    group_service.reset_group_service()
    return group_service.get_group_service()


def _file(tmp_path):
    return json.loads((tmp_path / "groups.json").read_text(encoding="utf-8"))


def test_a_group_is_saved_with_its_own_permissions(groups, tmp_path):
    """THE POINT: the permissions belong to the group, so they are stored with
    the group and not looked up on its members."""
    groups.save_group("Gameserver", ["Valheim"],
                      active=True, allowed_actions=["status", "restart"])

    entry = _file(tmp_path)["groups"][0]

    assert entry["active"] is True
    assert entry["allowed_actions"] == ["status", "restart"]


def test_they_come_back_the_way_they_went_in(groups):
    groups.save_group("Gameserver", ["Valheim"],
                      active=False, allowed_actions=["stop"])

    group = groups.find("Gameserver")

    assert group.active is False
    assert group.allowed_actions == ["stop"]


def test_a_member_keeps_its_own_settings(groups, tmp_path):
    """The other half of "losgelöst": saving a group writes groups.json and
    nothing else. A container's own file is not touched, so a container that
    may only be stopped on its own stays that way."""
    containers = tmp_path / "containers"
    containers.mkdir()
    own = containers / "Valheim.json"
    own.write_text(json.dumps({"container_name": "Valheim", "active": False,
                               "allowed_actions": ["stop"]}), encoding="utf-8")
    before = own.read_text(encoding="utf-8")

    groups.save_group("Gameserver", ["Valheim"],
                      active=True, allowed_actions=list(ACTIONS))

    assert own.read_text(encoding="utf-8") == before, (
        "saving a group rewrote a container's own configuration")


def test_an_invented_action_is_refused(groups):
    """The four are what a container offers and what Discord can press. An
    unknown one would be stored, shown as a tick, and do nothing."""
    result = groups.save_group("Gameserver", ["Valheim"],
                               allowed_actions=["status", "self_destruct"])

    assert result.success is False
    assert "self_destruct" in (result.error or ""), result.error


def test_a_group_written_before_today_keeps_what_it_could_do(groups, tmp_path):
    """It could be restarted from Discord yesterday, whatever its members said.
    Reading it as powerless would take that away from an operator who changed
    nothing."""
    (tmp_path / "groups.json").write_text(
        json.dumps({"groups": [{"name": "Gameserver", "containers": ["alpha", "beta"]}]}),
        encoding="utf-8")

    group = groups.find("Gameserver")

    assert group.active is True
    assert list(group.allowed_actions) == list(ACTIONS)


def test_the_name_and_the_containers_still_work(groups):
    """Counter-check: the two fields that were there before are untouched."""
    groups.save_group("Gameserver", ["Valheim", "alpha"])

    group = groups.find("Gameserver")

    assert group.name == "Gameserver"
    assert group.containers == ["Valheim", "alpha"]


def test_saving_without_saying_gives_the_four(groups):
    """A group made by something that does not know about permissions yet - a
    test, an import - is a group that works, for the same reason as above."""
    groups.save_group("Gameserver", ["Valheim"])

    group = groups.find("Gameserver")

    assert group.active is True
    assert list(group.allowed_actions) == list(ACTIONS)


def test_a_group_with_no_action_at_all_is_allowed(groups):
    """Not the same as saying nothing: this operator ticked every box off, and
    that has to survive the round trip or the boxes are decoration."""
    groups.save_group("Gameserver", ["Valheim"], allowed_actions=[])

    assert groups.find("Gameserver").allowed_actions == []


@pytest.fixture
def client(groups, tmp_path, monkeypatch):
    """The group blueprint on a minimal app, against the same config directory."""
    from flask import Flask

    from app import auth as auth_module
    from app.blueprints.group_routes import group_bp

    monkeypatch.setattr(auth_module.auth, "verify_password_callback",
                        lambda user, password: "admin" if user and password else None)
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="groups", WTF_CSRF_ENABLED=False)
    app.register_blueprint(group_bp)
    return app.test_client()


AUTH = {"Authorization": "Basic YWRtaW46YWRtaW4="}   # admin:admin


def test_the_api_round_trips_them(client):
    """The panel is the only place these are set, so the route has to carry
    them both ways."""
    saved = client.post("/api/groups",
                        json={"name": "Gameserver", "containers": ["Valheim"],
                              "active": False, "allowed_actions": ["stop"]},
                        headers=AUTH)

    assert saved.status_code == 200, saved.get_data(as_text=True)
    shown = client.get("/api/groups", headers=AUTH).get_json()["groups"][0]

    assert shown["active"] is False
    assert shown["allowed_actions"] == ["stop"]


def test_the_api_keeps_the_permissions_when_only_the_members_change(client):
    """The group dialog saves a name and containers and knows nothing about
    permissions. It must not reset them on its way past."""
    client.post("/api/groups", json={"name": "Gameserver", "containers": ["Valheim"],
                                     "allowed_actions": ["stop"]}, headers=AUTH)
    client.post("/api/groups", json={"name": "Gameserver",
                                     "containers": ["Valheim", "alpha"]}, headers=AUTH)
    shown = client.get("/api/groups", headers=AUTH).get_json()["groups"][0]

    assert shown["allowed_actions"] == ["stop"], "the dialog wiped the group's permissions"
    assert shown["containers"] == ["Valheim", "alpha"]
