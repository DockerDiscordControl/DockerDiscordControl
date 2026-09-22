#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Remembering the query port that actually answered (finding P1c).

Measured on the live installation: Valheim publishes 2456, 2457 and 2458, and
_candidate_ports offered them in that order - but only 2457 answers A2S.

    port 2456 -> 5005 ms, timeout
    port 2457 ->   66 ms, success
    port 2458 -> 5005 ms (never reached)

_fetch tries the candidates in order and stops at the first success, so every
status cycle burned a full 5 s timeout before succeeding. The reported query
duration hid this completely, because only the successful attempt is timed - the
statistics said "61 ms" while the wall clock said 5071 ms. That was the real
cause of the residual ~5.09 s per cycle, after two other explanations of mine had
been disproven by measurement.

Promoting the winning port turns one timeout per cycle into one timeout once.
"""

import time

import pytest

from services.infrastructure.game_query_service import (
    DEFAULT_TARGET_CACHE_TTL_SECONDS,
    GameQueryService,
)

CONTAINER = "Valheim"
KEY = (CONTAINER, "", 0, "source")


@pytest.fixture
def service():
    return GameQueryService()


def _seed(service, ports, host="172.17.0.16", ts=None):
    service._target_cache[KEY] = (ts if ts is not None else time.monotonic(), host, list(ports))


def _ports(service):
    return service._target_cache[KEY][2]


class TestPromotion:
    def test_answering_port_moves_to_the_front(self, service):
        _seed(service, [2456, 2457, 2458])
        service._promote_target_port(CONTAINER, 2457)
        assert _ports(service) == [2457, 2456, 2458]

    def test_the_other_candidates_are_kept(self, service):
        """They stay as fallbacks - the winner may stop answering later."""
        _seed(service, [2456, 2457, 2458])
        service._promote_target_port(CONTAINER, 2458)
        assert sorted(_ports(service)) == [2456, 2457, 2458]
        assert _ports(service)[0] == 2458

    def test_already_first_keeps_its_order_but_is_refreshed(self, service):
        """A success must refresh the entry even when nothing needs reordering.

        The first version of this test asserted the entry was left untouched - my own
        assumption, written an hour before the measurement disproved it. Because the entry was
        only refreshed when the order actually changed, it aged out TTL seconds after the last
        *reorder* instead of the last *success*: the learned order was lost, the wrong port was
        tried again, and the 5 s timeout came back every ~5 cycles. Measured over 39 cycles,
        the timeout returned at cycles 1, 9, 14, 19, 24, 29, 34 and 39.
        """
        stale = time.monotonic() - (DEFAULT_TARGET_CACHE_TTL_SECONDS - 5)
        _seed(service, [2457, 2456], ts=stale)

        service._promote_target_port(CONTAINER, 2457)

        assert _ports(service) == [2457, 2456], "order must not change"
        assert service._target_cache[KEY][0] > stale, "a success must keep the entry alive"

    def test_unknown_port_is_ignored(self, service):
        """A manually configured port is not part of the cached candidates."""
        _seed(service, [2456, 2457])
        service._promote_target_port(CONTAINER, 9999)
        assert _ports(service) == [2456, 2457]

    def test_timestamp_is_refreshed(self, service):
        """A server that keeps answering should keep its learned order, not lose it to the TTL."""
        stale = time.monotonic() - (DEFAULT_TARGET_CACHE_TTL_SECONDS - 5)
        _seed(service, [2456, 2457], ts=stale)
        service._promote_target_port(CONTAINER, 2457)
        assert service._target_cache[KEY][0] > stale

    def test_host_is_preserved(self, service):
        _seed(service, [2456, 2457], host="10.0.0.5")
        service._promote_target_port(CONTAINER, 2457)
        assert service._target_cache[KEY][1] == "10.0.0.5"

    def test_empty_candidate_list_is_harmless(self, service):
        _seed(service, [])
        service._promote_target_port(CONTAINER, 2457)  # must not raise
        assert _ports(service) == []

    def test_unknown_container_is_harmless(self, service):
        service._promote_target_port("never-cached", 2457)  # must not raise
        assert service._target_cache == {}

    def test_other_containers_are_untouched(self, service):
        _seed(service, [2456, 2457])
        other_key = ("Icarus", "", 0, "source")
        service._target_cache[other_key] = (time.monotonic(), "172.17.0.10", [27015, 17777])

        service._promote_target_port(CONTAINER, 2457)
        assert service._target_cache[other_key][2] == [27015, 17777]


class TestInteractionWithInvalidation:
    def test_a_failed_query_still_drops_the_learned_order(self, service):
        """A recreated container gets new ports; the learned order must not survive that."""
        _seed(service, [2456, 2457])
        service._promote_target_port(CONTAINER, 2457)
        assert _ports(service)[0] == 2457

        service._invalidate_target(CONTAINER)
        assert KEY not in service._target_cache
