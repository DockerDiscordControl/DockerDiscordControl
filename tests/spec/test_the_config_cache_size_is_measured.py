# -*- coding: utf-8 -*-
"""The config cache's reported size grows with what it holds.

THE FINDING (stage 4 review before v3.1.0, section 38 pass 4):
cache_size_mb was sys.getsizeof of the outer dict alone, so it reported
about 0.00 MB whatever the content - in the /performance_stats JSON and in
a debug line. A number that cannot move tells nobody anything.

THE CONTRACT: the size is estimated from the content (its JSON length),
so megabytes of server names show as megabytes.

HOW THIS TEST CAN FAIL: the figure stays near zero for a large cache.

COUNTER-CHECK (2026-09-30): red before the change (about 0.0001).
"""

import utils.config_cache as config_cache


def test_two_megabytes_of_names_read_as_megabytes(monkeypatch):
    cache = config_cache.ConfigCache(max_cache_age_minutes=15)
    monkeypatch.setattr(config_cache, "_config_cache", cache)
    servers = [{"name": f"{i:04d}" + "x" * 1000, "docker_name": f"c{i}"} for i in range(2000)]
    config_cache.init_config_cache({"servers": servers})

    size = config_cache.get_cache_memory_stats()["cache_size_mb"]
    assert 1.5 < size < 3.0, size


def test_an_empty_cache_is_near_zero(monkeypatch):
    cache = config_cache.ConfigCache(max_cache_age_minutes=15)
    monkeypatch.setattr(config_cache, "_config_cache", cache)
    assert config_cache.get_cache_memory_stats()["cache_size_mb"] < 0.001
