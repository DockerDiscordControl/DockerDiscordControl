# -*- coding: utf-8 -*-
"""Two configuration loads at once do not erase each other's read error.

THE FINDING (stage 4 review before v3.1.0, section 13 pass 4 F3, verified
2026-09-29). get_config resets the shared list self._read_errors at the
start of every load, without a lock. With config.json unreadable and two
threads loading at once (bot and web panel), the second load's reset wiped
the first one's recorded error: the first returned - and cached - a
configuration with no password hash and no config_read_errors. The panel
login then treats "no hash" as first-time setup (admin/setup), and /setup
may write a password over the unreadable file.

THE CONTRACT: a load's read errors belong to that load: one load cannot
reset another's while it runs.

HOW THIS TEST CAN FAIL: the reset and the load run unguarded again.

COUNTER-CHECK (2026-09-29): written before the fix and red then.
"""

import importlib
import threading


def test_the_second_load_does_not_wipe_the_first_ones_error(tmp_path, monkeypatch):
    (tmp_path / "config.json").write_text('{"broken": ', encoding="utf-8")
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    module = importlib.import_module("services.config.config_service")
    monkeypatch.setattr(module.ConfigService, "_instance", None)
    service = module.ConfigService()

    real = service._loader_service.load_modular_config
    a_loaded, b_reset, release = threading.Event(), threading.Event(), threading.Event()
    results = {}

    def loader():
        if threading.current_thread().name == "B":
            b_reset.set()               # B has done its reset and stands before its own read
            release.wait(3)
            return real()
        config = real()                 # A records its read error here
        a_loaded.set()
        b_reset.wait(1)                 # ... and lets B reset before it finishes
        return config

    monkeypatch.setattr(service._loader_service, "load_modular_config", loader)

    def a():
        results["A"] = service.get_config(force_reload=True)

    def b():
        a_loaded.wait(3)
        service.get_config(force_reload=True)

    ta, tb = threading.Thread(target=a, name="A"), threading.Thread(target=b, name="B")
    ta.start()
    tb.start()
    ta.join(5)
    release.set()
    tb.join(5)

    assert "config_read_errors" in results["A"], "A's read error was wiped by B's reset"
