# -*- coding: utf-8 -*-
"""A guild_id stored as a JSON number is read as that guild.

THE FINDING (stage 4 review before v3.1.0, section 38 pass 4):
get_cached_guild_id accepted only a digit STRING, so a guild_id stored as a
number read as "no guild" and every slash command was declared global -
while the startup sync (str(...).isdigit()) took the same value and synced
only that guild. The two readers disagreed. The panel always writes a
string; the trigger is a hand-edited or externally written config.json.

THE CONTRACT: an int or a digit string is the guild; anything else
(a bool, text, 0) is none. Both the cached and the uncached path agree.

HOW THIS TEST CAN FAIL: a number reads as "no guild" again.

COUNTER-CHECK (2026-09-30): red before the change (None).
"""

import pytest

import utils.config_cache as config_cache
from cogs.control_helpers import get_guild_id

GUILD = 123456789012345678


@pytest.fixture
def fresh_cache(monkeypatch):
    monkeypatch.setattr(config_cache, "_config_cache", config_cache.ConfigCache(max_cache_age_minutes=15))


@pytest.mark.parametrize("stored", [GUILD, str(GUILD)])
def test_the_cached_path(fresh_cache, stored):
    config_cache.init_config_cache({"guild_id": stored})
    assert get_guild_id() == [GUILD]


@pytest.mark.parametrize("stored", [GUILD, str(GUILD)])
def test_the_uncached_path(fresh_cache, monkeypatch, stored):
    monkeypatch.setattr(config_cache, "get_cached_config", lambda: {"guild_id": stored})
    assert config_cache.get_cached_guild_id() == GUILD


@pytest.mark.parametrize("stored", [True, "abc", "", None, 0, -5, 12.5])
def test_anything_else_is_no_guild(fresh_cache, stored):
    config_cache.init_config_cache({"guild_id": stored})
    assert config_cache.get_cached_guild_id() is None
