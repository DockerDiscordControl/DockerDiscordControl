# -*- coding: utf-8 -*-
"""The config cache must notice a change in config/channels, not only in config/.

THE FINDING (review E29, services/config/config_cache_service.py): the cached
configuration is held valid for as long as the **directory** mtime of
``config/`` has not moved past the timestamp of the cache entry:

    current_time = os.path.getmtime(config_dir) if config_dir.exists() else 0
    if cache_key in self._config_cache and self._cache_timestamps.get(cache_key, 0) >= current_time:
        return self._config_cache[cache_key].copy()

A directory's mtime moves when an entry in **that** directory is created,
renamed or removed. It does not move when a file inside a SUBDIRECTORY
changes - and the channel permissions and container settings, which are the
two things an operator actually edits, live in ``config/channels/*.json`` and
``config/containers/*.json``.

Today nothing breaks, because every save path goes on to call
``ConfigService.save_config``, which invalidates the cache explicitly
(`config_service.py:485`), and the bot and the web panel are one process
(measured: ``ps`` in the running container shows a single ``python3 run.py``),
so that invalidation reaches both.

What the directory check is for is the case where nothing called it: a file
edited by hand on the host - which is a normal thing to do here, because
``config/`` is mode 700 and gets edited through the Unraid shell - or a future
save path that writes a channel file without going through ``save_config``.
In both cases DDC served the old configuration until something unrelated
happened to touch ``config/`` itself, or until a restart. A channel permission
changed by hand simply did not take effect, and nothing said why.

The check now includes the subdirectories DDC keeps configuration in. Two
extra ``stat`` calls per cache lookup, against a configuration that silently
does not apply.
"""

import json
import os
import time

import pytest


@pytest.fixture
def config_dir(tmp_path):
    root = tmp_path / "config"
    (root / "channels").mkdir(parents=True)
    (root / "containers").mkdir()
    (root / "config.json").write_text(json.dumps({"a": 1}))
    (root / "channels" / "111.json").write_text(json.dumps({"name": "tech"}))
    return root


def _service():
    from services.config.config_cache_service import ConfigCacheService
    return ConfigCacheService()


def test_a_changed_channel_file_invalidates_the_cache(config_dir):
    service = _service()
    service.set_cached_config("unified", {"a": 1}, config_dir)

    assert service.get_cached_config("unified", config_dir) is not None, (
        "the cache did not even hold a fresh entry"
    )

    time.sleep(0.02)
    channel_file = config_dir / "channels" / "111.json"
    channel_file.write_text(json.dumps({"name": "tech", "commands": {"control": True}}))
    os.utime(channel_file, None)
    os.utime(channel_file.parent, None)

    assert service.get_cached_config("unified", config_dir) is None, (
        "a channel permission was changed and DDC kept serving the old "
        "configuration - the change simply did not take effect"
    )


def test_a_changed_container_file_invalidates_the_cache(config_dir):
    service = _service()
    service.set_cached_config("unified", {"a": 1}, config_dir)

    time.sleep(0.02)
    container_file = config_dir / "containers" / "alpha.json"
    container_file.write_text(json.dumps({"docker_name": "alpha"}))

    assert service.get_cached_config("unified", config_dir) is None


def test_the_top_level_still_works(config_dir):
    """Counter-check: the behaviour that was already there stays."""
    service = _service()
    service.set_cached_config("unified", {"a": 1}, config_dir)

    time.sleep(0.02)
    (config_dir / "another.json").write_text("{}")

    assert service.get_cached_config("unified", config_dir) is None


def test_an_untouched_config_is_still_served_from_cache(config_dir):
    """Counter-check, and the one that matters: do not defeat the cache."""
    service = _service()
    service.set_cached_config("unified", {"a": 1}, config_dir)

    for _ in range(3):
        assert service.get_cached_config("unified", config_dir) == {"a": 1}, (
            "an unchanged configuration was re-read - the cache is doing nothing"
        )


def test_a_missing_subdirectory_is_not_a_problem(tmp_path):
    """Not every install has both: a fresh one may have neither."""
    root = tmp_path / "config"
    root.mkdir()
    (root / "config.json").write_text("{}")

    service = _service()
    service.set_cached_config("unified", {"a": 1}, root)

    assert service.get_cached_config("unified", root) == {"a": 1}
