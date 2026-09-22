# -*- coding: utf-8 -*-
"""
THE FINDING (review C8, section 34 F4): `load_active_containers_from_config()`
reads every `config/containers/*.json` in a loop and guards each file with

    except (IOError, OSError, PermissionError, RuntimeError,
            docker.errors.APIError, docker.errors.DockerException)

`json.load` on a truncated or malformed file raises `json.JSONDecodeError`,
which is a `ValueError` - in neither that tuple nor the identical one around
the whole function. So the exception leaves the function. And the function is
called at IMPORT TIME of `app/utils/shared_data.py` (last line of the module)
and again from `register_background_services()`, neither of which catches
anything. One container file interrupted mid-write therefore does not cost that
one container: it stops the whole application from starting.

The same loop already treats every other per-file problem as a per-file problem
- a file without `container_name` is logged and skipped. This one was the
exception, for no reason other than the type of the exception.

The counter-check (test_the_readable_files_are_still_read) keeps the fix from
becoming "swallow everything": it uses only valid files, so it never touches
the defect, and it holds that the active containers still come back while
inactive and nameless ones stay out.
"""

import json

import pytest

from app.utils import shared_data


@pytest.fixture
def containers_dir(tmp_path, monkeypatch):
    """A private config directory, as the app resolves it at call time."""
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    directory = tmp_path / "containers"
    directory.mkdir()
    return directory


def _write(directory, name, payload):
    (directory / f"{name}.json").write_text(payload, encoding="utf-8")


def test_a_truncated_file_costs_only_that_container(containers_dir):
    """THE FINDING: a half-written file must not take the start-up with it."""
    _write(containers_dir, "good", json.dumps({"container_name": "good", "active": True}))
    _write(containers_dir, "broken", '{"container_name": "broken", "acti')

    containers = shared_data.load_active_containers_from_config()

    assert containers == ["good"]


def test_a_file_that_is_not_json_at_all_is_skipped(containers_dir):
    """Not only truncation - anything unparseable is a per-file problem."""
    _write(containers_dir, "good", json.dumps({"container_name": "good"}))
    _write(containers_dir, "junk", "this is not json")

    assert shared_data.load_active_containers_from_config() == ["good"]


def test_a_file_that_is_not_utf8_is_skipped(containers_dir):
    """A file written in another encoding raises UnicodeDecodeError, which is
    not a ValueError and was not caught either."""
    _write(containers_dir, "good", json.dumps({"container_name": "good"}))
    (containers_dir / "binary.json").write_bytes(b'{"container_name": "\xff\xfe"}')

    assert shared_data.load_active_containers_from_config() == ["good"]


def test_a_directory_of_junk_is_empty_not_fatal(containers_dir):
    """The worst case - not one readable file - is an empty list, not a crash."""
    _write(containers_dir, "junk1", "nope")
    _write(containers_dir, "junk2", "{")

    assert shared_data.load_active_containers_from_config() == []


def test_the_readable_files_are_still_read(containers_dir):
    """COUNTER-CHECK: skipping the unreadable must not become skipping
    everything. With only valid files, the active ones come back and the
    inactive ones stay out - this test never touches the defect."""
    _write(containers_dir, "a", json.dumps({"container_name": "a"}))
    _write(containers_dir, "b", json.dumps({"container_name": "b", "active": False}))
    _write(containers_dir, "c", json.dumps({"active": True}))  # no name

    assert shared_data.load_active_containers_from_config() == ["a"]
