# -*- coding: utf-8 -*-
"""The status cache still holds when the next refresh is due, not a moment less.

THE FINDING (independent review of the Docker layer, 2026-09-23):
ContainerStatusService sets its cache lifetime to exactly the refresh interval:

    cache_duration = get_setting('DDC_DOCKER_CACHE_DURATION', 30)
    self._cache_ttl = float(cache_duration)

and the status loop writes its entries at the END of a bulk pass. So an entry
written at t expires at t + interval, which is when the NEXT pass STARTS - and
it is only replaced when that pass FINISHES. For the length of one pass,
get_formatted_status deletes the entry and answers None, and the status embed
falls back to "🔄 Fetching container data…" for containers that were fine a
second earlier.

MEASURED on this installation (2026-09-23), rather than taken from the review,
which quoted 21 s from an older note about 34 containers:

    7 containers, DDC_DOCKER_CACHE_DURATION = 120
    the loop really runs every 120 s   (10:07:29, 10:09:29, 10:11:29, 10:13:29)
    a pass takes 97 ms .. 2105 ms
    -> the hole is about 2 s in every 120, i.e. 1.7 % of the time

Small here. It grows linearly with the number of containers and the daemon's
speed, and it is entirely self-inflicted: the interval and the lifetime are the
same number.

AND THE INTENT IS ALREADY IN THE CODE. The status loop computes

    calculated_ttl = int(cache_duration * 2.5)

for its own cache_ttl_seconds - it knows a cache written every interval needs
more than one interval of life. That margin was simply never given to the
formatted cache in ContainerStatusService. Two caches, one margin.

Serving slightly older data is not the same as lying about it: the overviews
already mark anything older than one and a half refresh cycles as aged and say
so, so a longer lifetime cannot pass stale data off as fresh.

HOW THIS TEST CAN FAIL: it writes an entry, moves the clock on by exactly one
refresh interval, and asks for it. Getting None back is red.

COUNTER-CHECK (2026-09-23): red before - the entry was gone at exactly the
interval. The other tests keep the cache a cache: it does expire eventually,
and a fresh entry is served unchanged.
"""

from datetime import datetime, timedelta

import pytest

from services.infrastructure.container_status_service import ContainerStatusService

INTERVAL = 120.0


@pytest.fixture
def service(monkeypatch):
    monkeypatch.setenv("DDC_DOCKER_CACHE_DURATION", str(int(INTERVAL)))
    from utils import settings

    if hasattr(settings, "_settings_cache"):
        monkeypatch.setattr(settings, "_settings_cache", {}, raising=False)
    return ContainerStatusService()


def _write(service, name, when):
    service.set_formatted_status(name, {"status": "running"}, when)


def test_the_entry_is_still_there_when_the_next_pass_starts(service):
    """THE FINDING: it expired exactly as the next pass began."""
    written_at = datetime.now() - timedelta(seconds=INTERVAL)
    _write(service, "nginx", written_at)

    assert service.get_formatted_status("nginx") is not None, (
        "the status cache expired at the very moment the refresh that replaces "
        "it started - every container shows 'Loading' until that pass finishes")


def test_it_survives_a_slow_pass_too(service):
    """A pass takes time; the entry has to last until it is replaced."""
    written_at = datetime.now() - timedelta(seconds=INTERVAL + 30)
    _write(service, "nginx", written_at)

    assert service.get_formatted_status("nginx") is not None, (
        "a refresh that took 30 s left a hole for 30 s")


def test_it_does_expire_eventually(service):
    """Counter-check: a longer life must not become an endless one."""
    written_at = datetime.now() - timedelta(seconds=INTERVAL * 10)
    _write(service, "nginx", written_at)

    assert service.get_formatted_status("nginx") is None, (
        "the cache never lets go, so a container that vanished stays on screen")


def test_a_fresh_entry_is_served_unchanged(service):
    """Counter-check: the everyday read."""
    _write(service, "nginx", datetime.now())

    entry = service.get_formatted_status("nginx")

    assert entry is not None
    assert entry["data"] == {"status": "running"}


def test_the_margin_matches_the_one_the_loop_already_uses(service):
    """The loop computes cache_duration * 2.5 for its own cache. One margin."""
    assert service._cache_ttl == pytest.approx(INTERVAL * 2.5), (
        f"the formatted cache lives {service._cache_ttl}s while the loop that "
        f"writes it every {INTERVAL}s gives its own cache {INTERVAL * 2.5}s")
