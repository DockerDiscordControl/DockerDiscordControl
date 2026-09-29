# -*- coding: utf-8 -*-
"""One broken container file does not take down the whole container list.

THE FINDING (stage 4 review before v3.1.0, section 13, both passes,
verified 2026-09-29). ServerConfigService._load_container_configs handles
a file with invalid JSON - it is counted as unreadable and skipped. A file
that is not valid UTF-8, or whose top level is null, a number or true,
raised UnicodeDecodeError / TypeError past the per-file handlers: the whole
container list failed - every overview, every panel - for one bad file.
_load_json_file in config_service handles the same cases.

THE CONTRACT: such a file is counted as unreadable and skipped like
invalid JSON; the other containers are listed.

HOW THIS TEST CAN FAIL: a new kind of bad file raises out of the list again.

COUNTER-CHECK (2026-09-29): written before the fix and red then.
"""

import json

import pytest


@pytest.mark.parametrize("name,raw", [("null.json", b"null"), ("number.json", b"7"),
                                      ("true.json", b"true"), ("binary.json", b"\xff\xfe\x00")])
def test_a_bad_file_is_skipped_and_the_rest_listed(tmp_path, monkeypatch, name, raw):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    containers = tmp_path / "containers"
    containers.mkdir()
    (containers / "good.json").write_text(json.dumps({"container_name": "good"}), encoding="utf-8")
    (containers / name).write_bytes(raw)
    from services.config.server_config_service import ServerConfigService

    servers = ServerConfigService().get_all_servers()

    assert [s.get("docker_name") for s in servers] == ["good"], servers
