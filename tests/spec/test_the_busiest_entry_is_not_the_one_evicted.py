# -*- coding: utf-8 -*-
"""The cache keeps the entries it is actually using.

THE FINDING (review D34, pass 2, section 14 F4): `_cleanup_cache` says it
keeps "the most recent entries" and does this:

    sorted_items = list(self._last_sent_content.items())[-keep_entries:]

That is insertion order, not use. Updating an EXISTING key in a Python dict
does not move it to the end - only a brand-new key is appended there. So a
key written on every single pass keeps whatever position it was first given,
and is exactly the kind of entry this eviction throws away, while a key
inserted later and never touched again survives as "recent".

What the cache is for: `has_content_changed` returns True for a key it does
not know, and the caller then sends a Discord edit. Evicting the busiest
entries therefore costs exactly the API calls this service exists to save -
it throws away the entries that save the most and keeps the ones that save
the least. It bites in a large setup, where the cleanup runs at all: more
than fifty channel/container pairs.

Recency is now recorded where it happens - on a write AND on a read that
hits, because an entry the bot keeps comparing against is in use whether or
not its content changed. That is the whole point of a cache that skips
updates: the entries with the most skips are the most valuable ones.
"""

import pytest

from services.discord.conditional_update_cache_service import (
    ConditionalUpdateCacheService,
)

CONTENT = {"description": "running", "colour": 0x00FF00}


def _fill(service, count, prefix="k"):
    for index in range(count):
        service.update_content(f"{prefix}{index:02d}", dict(CONTENT))


def test_an_entry_written_on_every_pass_survives_the_cleanup():
    """The finding, driven through the public interface that triggers it."""
    service = ConditionalUpdateCacheService()
    _fill(service, 60)                       # operations 1..60, k00 is the oldest

    for _ in range(40):                      # operations 61..100 on the oldest key
        service.update_content("k00", dict(CONTENT))
    # operation 100 with 60 entries held: the cleanup runs here

    assert service.get_cache_size() == 25, (
        f"premise: the cleanup did not run ({service.get_cache_size()} entries)"
    )
    assert service.has_content_changed("k00", dict(CONTENT)) is False, (
        "the entry written on 41 of the last 100 passes was thrown out, and "
        "the next status will be sent to Discord again for nothing"
    )


def test_an_entry_nobody_touched_is_the_one_that_goes():
    """The counter-case: keeping everything is not the answer either."""
    service = ConditionalUpdateCacheService()
    _fill(service, 60)
    for _ in range(40):
        service.update_content("k00", dict(CONTENT))

    assert service.has_content_changed("k01", dict(CONTENT)) is True, (
        "k01 was written once, 99 operations ago, and is still being kept"
    )


def test_a_read_that_hits_counts_as_use():
    """A key the bot keeps comparing against is in use.

    Without this, an entry that is only ever COMPARED - the skipped updates,
    which are the ones this cache is proud of - would still drift to the
    front of the eviction queue.
    """
    service = ConditionalUpdateCacheService()
    _fill(service, 60)

    for _ in range(39):
        service.has_content_changed("k00", dict(CONTENT))
    service.update_content("k99", dict(CONTENT))   # operation 100, 61 entries

    assert service.get_cache_size() == 25, service.get_cache_size()
    assert service.has_content_changed("k00", dict(CONTENT)) is False, (
        "the entry that answered 39 comparisons was thrown out as unused"
    )


def test_the_cleanup_still_shrinks_the_cache():
    """A pin: recency must not turn into keeping everything."""
    service = ConditionalUpdateCacheService()
    _fill(service, 60)
    for _ in range(40):
        service.update_content("k00", dict(CONTENT))

    assert service.get_cache_size() == 25


def test_a_changed_content_is_still_reported_as_changed():
    """A pin on what the cache is actually asked."""
    service = ConditionalUpdateCacheService()
    service.update_content("one", dict(CONTENT))

    assert service.has_content_changed("one", dict(CONTENT)) is False
    assert service.has_content_changed("one", {"description": "stopped"}) is True
