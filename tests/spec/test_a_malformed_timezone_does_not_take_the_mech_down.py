# -*- coding: utf-8 -*-
"""A malformed timezone in the progress config falls back to Europe/Zurich.

THE FINDING (stage 4 review before v3.1.0, section 24 pass 4 F7): a
timezone value that ZoneInfo rejects with ValueError ('', 'Europe/Zurich/',
'a/../b', an absolute path) escaped ProgressRuntime.timezone(), whose
except tuple named unknown keys but not ValueError. progress_service calls
it at import (TZ = runtime.timezone()), so the whole module failed to
import and every mech and donation feature was down - instead of the
fallback the code intends.

THE CONTRACT: any unusable timezone value logs a warning and gives
Europe/Zurich.

HOW THIS TEST CAN FAIL: a malformed value raises again.

COUNTER-CHECK (2026-09-30): red before the change (ValueError for the
three malformed values; the unknown key was already caught).
"""

import json
from zoneinfo import ZoneInfo

import pytest


@pytest.mark.parametrize("value", ["", "Europe/Zurich/", "a/../b", "Mars/Olympus"])
def test_the_fallback_applies(tmp_path, monkeypatch, value):
    from services.mech.progress import reset_progress_runtime
    from services.mech.progress.runtime import get_progress_runtime
    from services.mech.progress_paths import clear_progress_paths_cache

    monkeypatch.setenv("DDC_PROGRESS_DATA_DIR", str(tmp_path / "progress"))
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path / "ddc_config"))
    reset_progress_runtime()
    clear_progress_paths_cache()
    try:
        runtime = get_progress_runtime()
        runtime.paths.config_file.parent.mkdir(parents=True, exist_ok=True)
        runtime.paths.config_file.write_text(json.dumps({"timezone": value}), encoding="utf-8")

        assert runtime.timezone(refresh=True) == ZoneInfo("Europe/Zurich")
    finally:
        reset_progress_runtime()
        clear_progress_paths_cache()
