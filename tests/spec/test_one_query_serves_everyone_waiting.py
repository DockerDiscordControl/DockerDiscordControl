# -*- coding: utf-8 -*-
"""Two callers waiting for the same server share one query.

THE FINDING (review C63, section 19 F4): the module's "Design guarantees"
list "Per-container TTL cache ... plus in-flight de-duplication", and
``__init__`` declares ``self._in_flight: Dict[str, asyncio.Future]`` for it.
No method ever reads or writes that field. Two calls for the same container
while its cache entry is empty or expired - a bulk status refresh and an
on-demand check overlapping - each ran their own query.

That is not just duplicated work. ``_fetch`` walks the candidate ports with a
hard timeout on each, and the module's own notes record the measured case: a
Valheim server whose first candidate port never answers costs a full 5 s
timeout before the second one does. Two overlapping cycles pay that twice,
against the same server, for the same answer.
"""

import asyncio

import pytest

from services.infrastructure.game_query_service import (
    GameQueryRequest, GameQueryResult, GameQueryService)


def _request(name="valheim"):
    return GameQueryRequest(container_name=name, protocol="source",
                            host="10.0.0.5", port=2457)


@pytest.fixture
def service():
    return GameQueryService(cache_ttl_seconds=60.0)


def _slow_fetch(service, monkeypatch, delay=0.05):
    """Count the queries and make each one take a moment."""
    calls = []

    async def _fetch(request):
        calls.append(request.container_name)
        await asyncio.sleep(delay)
        return GameQueryResult(success=True, container_name=request.container_name,
                               players_online=3, max_players=10)

    monkeypatch.setattr(service, "_fetch", _fetch)
    return calls


@pytest.mark.asyncio
async def test_two_callers_at_once_cost_one_query(service, monkeypatch):
    calls = _slow_fetch(service, monkeypatch)

    first, second = await asyncio.gather(service.get_game_query(_request()),
                                         service.get_game_query(_request()))

    assert calls == ["valheim"], (
        f"the same server was queried {len(calls)} times for one answer"
    )
    assert first.players_online == 3
    assert second.players_online == 3


@pytest.mark.asyncio
async def test_the_waiter_gets_the_same_answer(service, monkeypatch):
    """Sharing a query must mean sharing its result, not an empty one."""
    _slow_fetch(service, monkeypatch)

    results = await asyncio.gather(*[service.get_game_query(_request()) for _ in range(5)])

    assert [r.success for r in results] == [True] * 5
    assert {r.players_online for r in results} == {3}


@pytest.mark.asyncio
async def test_two_different_servers_are_two_queries(service, monkeypatch):
    """Counter-check: de-duplication is per container, not global."""
    calls = _slow_fetch(service, monkeypatch)

    await asyncio.gather(service.get_game_query(_request("valheim")),
                         service.get_game_query(_request("zomboid")))

    assert sorted(calls) == ["valheim", "zomboid"]


@pytest.mark.asyncio
async def test_a_later_call_queries_again(service, monkeypatch):
    """Counter-check: the de-duplication must end when the query does, or a
    container would be queried once and never again."""
    calls = _slow_fetch(service, monkeypatch)
    service._cache_ttl = 0.0        # no TTL cache in the way

    await service.get_game_query(_request())
    await service.get_game_query(_request())

    assert calls == ["valheim", "valheim"]


@pytest.mark.asyncio
async def test_the_cache_still_answers(service, monkeypatch):
    """Counter-check: a fresh cache entry must still save the query entirely."""
    calls = _slow_fetch(service, monkeypatch)

    await service.get_game_query(_request())
    second = await service.get_game_query(_request())

    assert calls == ["valheim"]
    assert second.cached is True


@pytest.mark.asyncio
async def test_a_finished_query_left_behind_is_not_reused(service, monkeypatch):
    """The entry is cleared by a done-callback, and those run via call_soon -
    so there is a window in which a finished task is still in `_in_flight`.
    Handing its old result to a caller that arrives then would answer a fresh
    question with a stale answer (found by mutation M2 of review C63).
    """
    calls = _slow_fetch(service, monkeypatch)
    service._cache_ttl = 0.0        # no TTL cache in the way

    stale = asyncio.get_running_loop().create_future()
    stale.set_result(GameQueryResult(success=True, container_name="valheim",
                                     players_online=99, max_players=99))
    service._in_flight["valheim"] = stale

    result = await service.get_game_query(_request())

    assert calls == ["valheim"], "the leftover entry was awaited instead of querying"
    assert result.players_online == 3
