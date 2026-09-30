# -*- coding: utf-8 -*-
"""A configuration file edited in place by hand is read again, not served from the cache.

THE FINDING (stage 4 review before v3.1.0, section 12 pass 4 F8): the cache
decides "stale" by the mtimes of the config directories. An edit in place -
nano, `cat >` - changes the FILE's mtime, not the directory's, so the old
configuration kept being served until something unrelated wrote into
config/. The check's own docstring names exactly this case as its purpose
(review E29).

THE CONTRACT: the mtimes of the .json files count too.

HOW THIS TEST CAN FAIL: an in-place edit is ignored again.

COUNTER-CHECK (2026-09-30): red before the change.
"""

import json
import os
import time

import services.config.config_service as cs_mod


def test_an_in_place_edit_takes_effect(monkeypatch, tmp_path):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(cs_mod.ConfigService, "_instance", None)
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"language": "en"}), encoding="utf-8")
    service = cs_mod.ConfigService()
    assert service.get_config()["language"] == "en"
    pinned = os.path.getmtime(tmp_path)

    time.sleep(0.05)
    with open(config_file, "r+", encoding="utf-8") as f:        # same inode, like nano
        f.seek(0)
        f.write(json.dumps({"language": "de"}))
        f.truncate()
    os.utime(tmp_path, (pinned, pinned))                          # the directory did not change

    assert service.get_config()["language"] == "de", "a hand edit was served from the cache"
