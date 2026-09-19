# -*- coding: utf-8 -*-
"""The admin list must live in the directory from ``DDC_CONFIG_DIR``.

NO ``@covers`` marker: that would be a new guarantee, and those are the
operator's decision.

THE FINDING. ``AdminService`` derives ``admins.json`` itself in three places
(``Path(__file__).parents[2] / 'config'``, admin_service.py:45/156/195) and
ignores the variable. Unlike the containers there is no second reader here -
the service agrees with itself. The consequence is a different one:

1. Anyone who points ``DDC_CONFIG_DIR`` at their volume (as
   docs/CONFIGURATION.md describes) has the admin list OUTSIDE of it. When the
   container is recreated it is gone - and with it every admin permission.
2. Z2: In the test run (conftest sets the variable) ``save_admin_data`` writes
   into the REAL config/.

HOW IT IS CHECKED HERE: writing, reading and the permission check run against
a fresh directory. For reading, the TEST creates the file - otherwise a green
read test would only prove that writing and reading use the same wrong
location.
"""

import json

import pytest

from services.admin.admin_service import AdminService


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    target = tmp_path / "custom_config"
    target.mkdir()
    monkeypatch.setenv("DDC_CONFIG_DIR", str(target))
    return target


def _create(config_dir, users):
    (config_dir / "admins.json").write_text(
        json.dumps({"discord_admin_users": users, "admin_notes": {}}), encoding="utf-8")


def test_saving_goes_into_the_directory(config_dir):
    """THE FINDING, first consequence: the list ends up outside the volume."""
    assert AdminService().save_admin_data(["111"], {"111": "Probe"}) is True

    file = config_dir / "admins.json"
    assert file.exists(), "admins.json was not written to DDC_CONFIG_DIR."
    assert json.loads(file.read_text(encoding="utf-8"))["discord_admin_users"] == ["111"]


def test_the_admin_data_comes_from_the_directory(config_dir):
    _create(config_dir, ["222"])

    assert AdminService().get_admin_data()["discord_admin_users"] == ["222"]


def test_the_permission_check_reads_the_directory(config_dir):
    """The path that decides permissions (_load_admin_users)."""
    _create(config_dir, ["333"])

    assert AdminService()._load_admin_users() == ["333"]
