# -*- coding: utf-8 -*-
"""Bot and web process do not overwrite each other's spam settings.

THE FINDING: SpamProtectionService.save_config reads channels_config.json,
puts its own section into what it read and writes the whole file back - with
no lock of any kind, and through a FIXED temp name (channels_config.tmp). DDC
is two processes (supervisord starts the bot and the web UI) and both hold
this service: the panel saves the limits while the bot writes the same file,
and the later write replaces a file that never saw the earlier one. Two
writers also shared that one temp name, so the target could be replaced with
a mixture of both.

The lock that already guards the scheduler's tasks and the mech's state spans
the read and the write here too, and the temp file gets a unique name.

COUNTER-CHECK (2026-09-23): red before - the process that started later and
finished first had its setting thrown away by the slower one, and the file
held 11 instead of 22. test_the_rest_of_the_file_survives holds the other
side: a writer that simply replaced the file would be green on the first test
alone.
"""

import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

WRITER = textwrap.dedent('''
    import sys, time
    sys.path.insert(0, {root!r})
    from services.infrastructure import spam_protection_service as module

    # Widen the window between this process's read and its write. to_dict runs
    # after the file has been read (spam_protection_service.py:181-188), so
    # the sleep sits exactly in the read-modify-write cycle.
    real_to_dict = module.SpamProtectionConfig.to_dict
    def slow_to_dict(self):
        time.sleep({delay})
        return real_to_dict(self)
    module.SpamProtectionConfig.to_dict = slow_to_dict

    service = module.SpamProtectionService(config_dir={directory!r})
    config = service.get_config().data
    service.save_config(module.SpamProtectionConfig(
        command_cooldowns=config.command_cooldowns,
        button_cooldowns=config.button_cooldowns,
        global_enabled=config.global_enabled,
        max_commands_per_minute={value},
        max_buttons_per_minute=config.max_buttons_per_minute,
        cooldown_message=config.cooldown_message,
        log_violations=config.log_violations))
''')


def _writer(directory, value, delay):
    script = WRITER.format(root=str(ROOT), directory=str(directory),
                           value=value, delay=delay)
    return subprocess.Popen([sys.executable, "-c", script], env=dict(os.environ),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def _prepared(tmp_path):
    """A channels_config.json with a section neither writer knows about."""
    (tmp_path / "channels_config.json").write_text(json.dumps({
        "channel_permissions": {"123": {"commands": ["status"]}},
        "spam_protection": {"global_settings": {"max_commands_per_minute": 20}},
    }), encoding="utf-8")
    return tmp_path / "channels_config.json"


def _saved(config_file):
    return json.loads(config_file.read_text(encoding="utf-8"))


def test_the_later_setting_is_the_one_that_stands(tmp_path):
    config_file = _prepared(tmp_path)

    slow = _writer(tmp_path, value=11, delay=0.8)
    time.sleep(0.25)                      # the panel saves while the bot holds
    quick = _writer(tmp_path, value=22, delay=0.0)
    for process in (slow, quick):
        assert process.wait(timeout=90) == 0, process.stderr.read()

    written = _saved(config_file)["spam_protection"]["global_settings"]

    assert written["max_commands_per_minute"] == 22, (
        f"a saved setting was thrown away: the file says "
        f"{written['max_commands_per_minute']}")


def test_the_rest_of_the_file_survives(tmp_path):
    """Counter-check: this service owns one section, not the file."""
    config_file = _prepared(tmp_path)

    writer = _writer(tmp_path, value=7, delay=0.0)
    assert writer.wait(timeout=90) == 0, writer.stderr.read()

    assert _saved(config_file)["channel_permissions"] == {"123": {"commands": ["status"]}}


def test_no_temp_file_is_left_behind(tmp_path):
    """Counter-check: the fixed name channels_config.tmp is gone for good."""
    _prepared(tmp_path)

    writer = _writer(tmp_path, value=9, delay=0.0)
    assert writer.wait(timeout=90) == 0, writer.stderr.read()

    leftovers = [p.name for p in tmp_path.iterdir()
                 if p.name != "channels_config.json" and not p.name.endswith(".lock")]
    assert leftovers == [], f"left behind: {leftovers}"
