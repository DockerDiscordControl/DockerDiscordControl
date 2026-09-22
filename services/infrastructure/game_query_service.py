# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Game Query Service - SERVICE FIRST, non-blocking game-server player-count queries.

A thin async wrapper around the ``opengsq`` library (MIT, only depends on aiohttp
which DDC already ships). Used to enrich the per-container status with a live
"players online / max" figure for game servers (Valheim, V Rising, Project Zomboid,
Icarus, ... via the Source/A2S protocol).

Design guarantees (mirrors the existing status-fetch services):
- **Never blocks the status loop**: every query is wrapped in ``asyncio.wait_for``
  with a hard timeout; bulk queries use ``gather(return_exceptions=True)`` so one
  dead/unreachable UDP server can never kill the others or raise.
- **Lazy opengsq import**: the library is only imported the first time a query
  actually runs. When the feature is disabled the dependency is never touched and
  this module imports with zero cost (also keeps it unit-testable without opengsq).
- **Per-container TTL cache** (shorter than the Docker status cache, since game
  state changes faster) plus in-flight de-duplication.
- Returns a ``GameQueryResult`` for every call - it never raises to the caller.
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Dict, List, Optional, Tuple

from utils.logging_utils import get_module_logger

logger = get_module_logger('game_query_service')

# Default per-container cache TTL. Intentionally shorter than DDC_DOCKER_CACHE_DURATION
# (game player counts change faster than container CPU/RAM).
DEFAULT_CACHE_TTL_SECONDS = 10.0
DEFAULT_QUERY_TIMEOUT_SECONDS = 5.0
# Was 3: with six query-enabled containers that meant two sequential waves, so one dead server
# cost two full timeouts per status cycle instead of one (finding P1). Six lets a typical
# installation finish in a single wave; the per-query timeout still bounds each one.
DEFAULT_MAX_CONCURRENT = 6
# How long a resolved (host, ports) target stays valid. Resolving it opens a Docker connection
# and inspects the container, which happened for every container on every status cycle. Ports
# only change when a container is recreated, so a few minutes is safe; a wrong entry costs one
# failed query and is dropped immediately (see resolve_query_candidates).
DEFAULT_TARGET_CACHE_TTL_SECONDS = 300.0

# Whitelist of supported query protocols (also enforced by config validation).
# - 'source'       Steam A2S - most Steam dedicated survival servers (Valheim,
#                  Enshrouded, V Rising, Project Zomboid, Icarus, Rust, CS, ...).
# - 'minecraft'    Minecraft Server List Ping (TCP, default port 25565). No token.
# - 'satisfactory' Satisfactory Lightweight Query (UDP state poll, default 7777).
#                  The live player count comes from the authenticated HTTPS API and
#                  needs a per-server app token (generated in the in-game Server
#                  Manager); without it (or with no save loaded) no count is shown.
SUPPORTED_PROTOCOLS = ('source', 'minecraft', 'satisfactory', 'palworld')

# Protocols whose live player count requires a per-server credential (token / password)
# and therefore CANNOT be auto-detected - the user must pick the protocol and enter it.
TOKEN_PROTOCOLS = ('satisfactory', 'palworld')


@dataclass(frozen=True)
class GameQueryRequest:
    """A single game-server query target. ``host``/``port`` are already resolved."""
    container_name: str               # docker_name (stable key for cache/results)
    protocol: str                     # one of SUPPORTED_PROTOCOLS
    host: str
    port: int                         # primary port to try first
    timeout_seconds: float = DEFAULT_QUERY_TIMEOUT_SECONDS
    token: str = ''                   # access token (only used by TOKEN_PROTOCOLS, e.g. satisfactory)
    candidate_ports: tuple = ()       # fallback ports tried in order if the primary doesn't answer


@dataclass
class GameQueryResult:
    """Result of a game-server query. ``success=False`` never raises - it carries an error_type."""
    success: bool
    container_name: str
    players_online: Optional[int] = None
    max_players: Optional[int] = None
    query_duration_ms: float = 0.0
    cached: bool = False
    # 'timeout' | 'unreachable' | 'no_query' | 'disabled' | 'bad_config'
    error_type: Optional[str] = None
    error_message: Optional[str] = None

    @classmethod
    def disabled(cls, container_name: str) -> 'GameQueryResult':
        return cls(success=False, container_name=container_name, error_type='disabled')

    @classmethod
    def no_query(cls, container_name: str, message: str = "no query target") -> 'GameQueryResult':
        return cls(success=False, container_name=container_name,
                   error_type='no_query', error_message=message)


class GameQueryService:
    """Singleton service that queries game servers via opengsq, cached and non-blocking."""

    def __init__(self, cache_ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS):
        self._cache_ttl = cache_ttl_seconds
        # container_name -> (timestamp, GameQueryResult)
        self._cache: Dict[str, Tuple[float, GameQueryResult]] = {}
        # container_name -> the query task the waiters share (see get_game_query)
        self._in_flight: Dict[str, asyncio.Task] = {}
        # (container, host override, port override, protocol) -> (timestamp, host, ports).
        # Avoids re-inspecting every container over Docker on every status cycle (finding P1).
        self._target_cache: Dict[Tuple[str, str, int, str], Tuple[float, Optional[str], List[int]]] = {}

    # --- protocol dispatch -------------------------------------------------

    async def _query_protocol(self, protocol: str, host: str, port: int,
                              timeout: float, token: str = '') -> Tuple[Optional[int], Optional[int]]:
        """Run the actual opengsq query. Returns (players_online, max_players).

        opengsq is imported LAZILY here so the module loads (and the feature stays
        zero-cost) when the dependency is absent / the feature is off. Raises on any
        protocol/network error - the caller wraps this in a timeout + try/except.
        """
        if protocol == 'source':
            from opengsq.protocols.source import Source  # lazy import
            info = await Source(host=host, port=port, timeout=timeout).get_info()
            players = getattr(info, 'players', None)
            max_players = getattr(info, 'max_players', None)
            return players, max_players
        if protocol == 'minecraft':
            from opengsq.protocols.minecraft import Minecraft  # lazy import
            status = await Minecraft(host=host, port=port, timeout=timeout).get_status()
            players = (status or {}).get('players') or {}
            return players.get('online'), players.get('max')
        if protocol == 'satisfactory':
            from opengsq.protocols.satisfactory import Satisfactory  # lazy import
            # The UDP state poll works without auth, but the live player count comes
            # from the authenticated HTTPS API (needs a token from the in-game Server
            # Manager) and only when a save is loaded (server_state == 3). Otherwise
            # opengsq returns 0/0 or "Not Available" -> we report no count rather than 0/0.
            status = await Satisfactory(host=host, port=port,
                                        app_token=(token or ''), timeout=timeout).get_status()
            if status is None:
                return None, None
            players = getattr(status, 'num_players', None)
            max_players = getattr(status, 'max_players', None)
            players = players if isinstance(players, int) else None
            max_players = max_players if isinstance(max_players, int) and max_players > 0 else None
            if max_players is None:
                return None, None
            return players, max_players
        if protocol == 'palworld':
            from opengsq.protocols.palworld import Palworld  # lazy import
            # Palworld's REST API uses HTTP Basic auth with the fixed username "admin" and the
            # server's AdminPassword (passed here as the token). Default REST API port is 8212.
            status = await Palworld(host=host, port=port, api_username='admin',
                                    api_password=(token or ''), timeout=timeout).get_status()
            if status is None:
                return None, None
            players = getattr(status, 'num_players', None)
            max_players = getattr(status, 'max_players', None)
            players = players if isinstance(players, int) else None
            max_players = max_players if isinstance(max_players, int) and max_players > 0 else None
            if max_players is None:
                return None, None
            return players, max_players
        raise ValueError(f"unsupported protocol: {protocol}")

    # --- single query ------------------------------------------------------

    async def get_game_query(self, request: GameQueryRequest) -> GameQueryResult:
        """Query one server (cache-first). Always returns a result, never raises."""
        if request.protocol not in SUPPORTED_PROTOCOLS:
            return GameQueryResult(success=False, container_name=request.container_name,
                                   error_type='bad_config',
                                   error_message=f"unsupported protocol '{request.protocol}'")
        if not request.host or not request.port:
            return GameQueryResult.no_query(request.container_name)

        cached = self._get_cached(request.container_name)
        if cached is not None:
            return cached

        # In-flight de-duplication, the guarantee the module docstring makes.
        # `_in_flight` was declared for it in __init__ and never read or written
        # by anything, so two calls for the same container with no fresh cache
        # entry - a bulk status refresh and an on-demand check overlapping -
        # each ran their own query. _fetch walks the candidate ports with a hard
        # timeout on each, and this module's own notes record the measured case:
        # a Valheim server whose first candidate port never answers costs a full
        # 5 s timeout. Two overlapping cycles paid that twice for one answer
        # (review C63).
        name = request.container_name
        running = self._in_flight.get(name)
        if running is None or running.done():
            running = asyncio.ensure_future(self._fetch_and_cache(request))
            self._in_flight[name] = running
            # Cleared when the query ends, not when the first caller stops
            # waiting - otherwise a cancelled caller would leave the entry
            # behind and the next one would start a second query anyway.
            running.add_done_callback(
                lambda task, key=name: self._in_flight.pop(key, None)
                if self._in_flight.get(key) is task else None)

        # shield: a caller that is cancelled must not cancel the query the
        # others are waiting for.
        return await asyncio.shield(running)

    async def _fetch_and_cache(self, request: GameQueryRequest) -> GameQueryResult:
        """The one query behind however many callers are waiting for it."""
        result = await self._fetch(request)
        if not result.success:
            # The cached target may be stale (container recreated on different ports), so
            # re-resolve next time instead of retrying a dead address for the full TTL.
            self._invalidate_target(request.container_name)
        self._cache[request.container_name] = (time.monotonic(), result)
        return result

    def _get_cached(self, container_name: str) -> Optional[GameQueryResult]:
        entry = self._cache.get(container_name)
        if entry is None:
            return None
        ts, result = entry
        if (time.monotonic() - ts) >= self._cache_ttl:
            return None
        # Return a shallow copy flagged as cached so callers can tell.
        return GameQueryResult(
            success=result.success, container_name=result.container_name,
            players_online=result.players_online, max_players=result.max_players,
            query_duration_ms=result.query_duration_ms, cached=True,
            error_type=result.error_type, error_message=result.error_message,
        )

    def _promote_target_port(self, container_name: str, port: int) -> None:
        """Move the port that actually answered to the front of the cached candidate list.

        Many servers publish a game port and a separate query port, and only the latter answers
        A2S. _candidate_ports orders them by a heuristic, which can be wrong: measured on the
        live installation, Valheim's list was [2456, 2457, 2458] while only 2457 answers - so
        every status cycle burned a full 5 s timeout on 2456 before succeeding on 2457 (the
        reported query duration hid it, because only the successful attempt is timed).

        Remembering the winner turns that into a single timeout, once, instead of one per cycle.
        The entry's timestamp is refreshed so a server that keeps answering keeps its learned
        order; a failed query still drops the entry entirely (see _invalidate_target), so a
        recreated container with different ports re-resolves after one failure.
        """
        now = time.monotonic()
        for key in [k for k in self._target_cache if k[0] == container_name]:
            _, host, ports = self._target_cache[key]
            if not ports or port not in ports:
                continue
            if ports[0] == port:
                # Already first - but still refresh the entry. Measured after the first version
                # of this method: it only refreshed when it reordered, so the entry aged out
                # DEFAULT_TARGET_CACHE_TTL_SECONDS after the last reorder rather than after the
                # last success. The learned order was then lost, the wrong port tried again, and
                # a 5 s timeout reappeared every ~5 cycles like clockwork.
                self._target_cache[key] = (now, host, ports)
                continue
            reordered = [port] + [p for p in ports if p != port]
            self._target_cache[key] = (now, host, reordered)
            logger.debug("[GAME_QUERY] %s answers on port %d - trying it first from now on",
                         container_name, port)

    def _invalidate_target(self, container_name: str) -> None:
        """Drop the cached (host, ports) for a container after a query failed.

        A recreated container usually gets different published ports. Without this the stale
        target would be retried for the whole target-cache TTL. The cache key also carries the
        configured host/port overrides, so it cannot be rebuilt from the request alone - every
        entry belonging to the container is dropped instead (there are only a handful).
        """
        for key in [k for k in self._target_cache if k[0] == container_name]:
            del self._target_cache[key]

    async def _fetch(self, request: GameQueryRequest) -> GameQueryResult:
        """Query the primary port, falling back to candidate ports until one answers.

        Many game servers publish BOTH a game port and a separate query port (e.g. Icarus
        17777 game + 27015 query); only the latter answers A2S. Candidate ports are already
        ordered most-likely-first by _candidate_ports, so the primary usually succeeds with
        no extra latency. Never raises; returns the first success or the last failure.
        """
        ports_to_try = [request.port] + [p for p in request.candidate_ports if p != request.port]
        last_result: Optional[GameQueryResult] = None
        for port in ports_to_try:
            result = await self._fetch_one(request, port)
            if result.success:
                # Remember the winner: without this the same wrong primary port is retried on
                # every single cycle, costing a full timeout each time (finding P1c).
                self._promote_target_port(request.container_name, port)
                return result
            last_result = result
        return last_result or GameQueryResult.no_query(request.container_name)

    async def _fetch_one(self, request: GameQueryRequest, port: int) -> GameQueryResult:
        """Run a single query against one port with a hard timeout. Never raises."""
        start = time.monotonic()
        try:
            players, max_players = await asyncio.wait_for(
                self._query_protocol(request.protocol, request.host, port,
                                     request.timeout_seconds, request.token),
                timeout=request.timeout_seconds,
            )
            duration_ms = (time.monotonic() - start) * 1000.0
            return GameQueryResult(
                success=True, container_name=request.container_name,
                players_online=players, max_players=max_players,
                query_duration_ms=duration_ms,
            )
        except asyncio.TimeoutError:
            logger.debug(f"[GAME_QUERY] Timeout querying {request.container_name} "
                         f"({request.protocol} {request.host}:{port})")
            return GameQueryResult(success=False, container_name=request.container_name,
                                   error_type='timeout',
                                   query_duration_ms=(time.monotonic() - start) * 1000.0)
        except (OSError, ValueError, RuntimeError, ConnectionError) as e:
            # Dead server / refused / malformed response - degrade gracefully. (CancelledError
            # is intentionally NOT caught: it must propagate to honour cooperative cancellation.)
            logger.debug(f"[GAME_QUERY] Query failed for {request.container_name}: {e}")
            return GameQueryResult(success=False, container_name=request.container_name,
                                   error_type='unreachable', error_message=str(e),
                                   query_duration_ms=(time.monotonic() - start) * 1000.0)
        except Exception as e:  # noqa: BLE001 - opengsq may raise lib-specific errors; never propagate
            logger.warning(f"[GAME_QUERY] Unexpected error for {request.container_name}: {e}")
            return GameQueryResult(success=False, container_name=request.container_name,
                                   error_type='unreachable', error_message=str(e),
                                   query_duration_ms=(time.monotonic() - start) * 1000.0)

    # --- bulk query --------------------------------------------------------

    async def get_bulk_game_queries(self, requests: List[GameQueryRequest],
                                    max_concurrent: int = DEFAULT_MAX_CONCURRENT
                                    ) -> Dict[str, GameQueryResult]:
        """Query many servers concurrently. One dead server never kills the others.

        Returns {container_name: GameQueryResult}. Always returns one entry per
        request; an internal error becomes an 'unreachable' result (never raises).
        """
        if not requests:
            return {}

        semaphore = asyncio.Semaphore(max(1, max_concurrent))

        async def _guarded(req: GameQueryRequest) -> GameQueryResult:
            async with semaphore:
                return await self.get_game_query(req)

        tasks = [_guarded(req) for req in requests]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        out: Dict[str, GameQueryResult] = {}
        for req, res in zip(requests, results):
            if isinstance(res, GameQueryResult):
                out[req.container_name] = res
            else:
                logger.debug(f"[GAME_QUERY] Bulk task error for {req.container_name}: {res}")
                out[req.container_name] = GameQueryResult(
                    success=False, container_name=req.container_name,
                    error_type='unreachable', error_message=str(res))
        return out

    # --- support detection -------------------------------------------------

    # Protocols we can auto-probe without extra credentials (satisfactory needs a token,
    # so it is never auto-probed - those checkboxes stay enabled).
    AUTO_PROBE_PROTOCOLS = ('source', 'minecraft')

    async def detect_support(self, container_name: str, configured_host: str = '',
                             configured_port: int = 0) -> Tuple[bool, Optional[str], Optional[int]]:
        """Probe whether a container answers a player-count query on any published port.

        Tries each auto-probeable protocol across all candidate ports (Source/A2S over UDP,
        Minecraft over TCP). Returns (supported, protocol, port_or_None). Best-effort: never
        raises. A short timeout keeps it cheap; a non-answering container simply yields False.
        """
        for proto in self.AUTO_PROBE_PROTOCOLS:
            host, ports = await self.resolve_query_candidates(
                container_name, configured_host, configured_port, proto)
            if not host or not ports:
                continue
            req = GameQueryRequest(
                container_name=f"__probe__:{container_name}", protocol=proto,
                host=host, port=ports[0], candidate_ports=tuple(ports[1:]),
                timeout_seconds=3.0)
            result = await self._fetch(req)  # bypasses the player-count cache by design
            if result.success:
                return True, proto, None
        return False, None, None

    # --- query-target resolution (port autodiscovery) ----------------------

    async def resolve_query_port(self, container_name: str,
                                 configured_port: int = 0,
                                 protocol: str = 'source') -> Optional[int]:
        """Resolve the host port to query for a container.

        A non-zero ``configured_port`` (manual override) always wins. Otherwise the
        first published host port is auto-discovered from the Docker API, preferring the
        transport the ``protocol`` actually uses (TCP for minecraft, UDP otherwise).
        Returns None when no target can be determined (-> caller emits a 'no_query' result).
        """
        if configured_port and configured_port > 0:
            return int(configured_port)
        try:
            from services.docker_service.docker_client_pool import get_docker_client_async
            async with get_docker_client_async(timeout=5.0, operation='game_query_port',
                                               container_name=container_name) as client:
                # Blocking SDK call - keep it off the event loop
                container = await asyncio.to_thread(client.containers.get, container_name)
                ports = container.attrs.get('NetworkSettings', {}).get('Ports', {}) or {}
                return self._first_published_port(ports, protocol)
        except Exception as e:  # noqa: BLE001 - autodiscovery is best-effort
            logger.debug(f"[GAME_QUERY] Port autodiscovery failed for {container_name}: {e}")
            return None

    async def resolve_query_candidates(self, container_name: str, configured_host: str = '',
                                       configured_port: int = 0,
                                       protocol: str = 'source') -> Tuple[Optional[str], List[int]]:
        """Resolve (host, [ports]) - an ordered list of candidate ports to try.

        Overrides win: a non-empty ``configured_host`` and/or non-zero ``configured_port``
        are used as-is (a manual port yields a single candidate). Otherwise the host is the
        container's own Docker IP and the ports are ALL published ports ordered most-likely-
        queryable first (see _candidate_ports). Returns (None, []) when nothing usable found.
        """
        host = (configured_host or '').strip() or None
        manual_port = int(configured_port) if configured_port and configured_port > 0 else None
        if host and manual_port:
            return host, [manual_port]

        # Autodiscovery below costs a Docker connection plus a container inspect, and it ran for
        # every container on every status cycle (finding P1). Published ports only change when a
        # container is recreated, so the result is cached briefly.
        cache_key = (container_name, host or '', manual_port or 0, protocol)
        cached = self._target_cache.get(cache_key)
        if cached is not None:
            ts, cached_host, cached_ports = cached
            if (time.monotonic() - ts) < DEFAULT_TARGET_CACHE_TTL_SECONDS:
                return cached_host, list(cached_ports)
            del self._target_cache[cache_key]

        ports: List[int] = []
        try:
            from services.docker_service.docker_client_pool import get_docker_client_async
            async with get_docker_client_async(timeout=5.0, operation='game_query_target',
                                               container_name=container_name) as client:
                # Blocking SDK call - keep it off the event loop
                attrs = (await asyncio.to_thread(client.containers.get, container_name)).attrs
                net = attrs.get('NetworkSettings', {}) or {}
                if host is None:
                    host = self._container_ip(net)
                ports = [manual_port] if manual_port else self._candidate_ports(net.get('Ports', {}) or {}, protocol)
        except Exception as e:  # noqa: BLE001 - autodiscovery is best-effort
            logger.debug(f"[GAME_QUERY] Target autodiscovery failed for {container_name}: {e}")
            ports = [manual_port] if manual_port else []
        if host and ports:
            self._target_cache[cache_key] = (time.monotonic(), host, list(ports))
            return host, ports
        return None, []

    async def resolve_query_target(self, container_name: str, configured_host: str = '',
                                   configured_port: int = 0,
                                   protocol: str = 'source') -> Tuple[Optional[str], Optional[int]]:
        """Resolve (host, port) for the first candidate port - back-compat wrapper."""
        host, ports = await self.resolve_query_candidates(
            container_name, configured_host, configured_port, protocol)
        return host, (ports[0] if ports else None)

    @staticmethod
    def _container_ip(network_settings: dict) -> Optional[str]:
        """Best-effort container IP from Docker NetworkSettings (default bridge or first network)."""
        ip = network_settings.get('IPAddress')
        if ip:
            return ip
        for net in (network_settings.get('Networks') or {}).values():
            if net and net.get('IPAddress'):
                return net['IPAddress']
        return None

    # Steam A2S query ports conventionally live in this band (default 27015). When a Source
    # server publishes BOTH a game port and a query port (e.g. Icarus 17777 game + 27015
    # query), A2S only answers on the query port - so float this band to the front.
    _STEAM_QUERY_RANGE = (27000, 27100)

    @classmethod
    def _candidate_ports(cls, ports: dict, protocol: str = 'source') -> List[int]:
        """Ordered list of published host ports to try, most-likely-queryable first.

        Ports has the shape {"7777/udp": [{"HostIp": "...", "HostPort": "7777"}], ...}.
        Prefers the transport the protocol uses (TCP for minecraft, UDP otherwise); for
        Source/A2S, ports in the Steam query range are floated ahead of game ports. The
        remaining ports follow as fallbacks. De-duplicated, order preserved.
        """
        def _host_port(bindings):
            if bindings:
                hp = bindings[0].get('HostPort')
                if hp:
                    try:
                        return int(hp)
                    except (TypeError, ValueError):
                        return None
            return None

        preferred_suffix = '/tcp' if protocol in ('minecraft', 'palworld') else '/udp'
        preferred, other = [], []
        for spec, bindings in ports.items():
            p = _host_port(bindings)
            if p is None:
                continue
            (preferred if str(spec).endswith(preferred_suffix) else other).append(p)

        if protocol == 'source':
            lo, hi = cls._STEAM_QUERY_RANGE
            preferred.sort(key=lambda p: 0 if lo <= p <= hi else 1)  # stable: Steam range first

        ordered, seen = [], set()
        for p in preferred + other:
            if p not in seen:
                seen.add(p)
                ordered.append(p)
        return ordered

    @classmethod
    def _first_published_port(cls, ports: dict, protocol: str = 'source') -> Optional[int]:
        """First candidate port (back-compat wrapper around _candidate_ports). Returns int or None."""
        candidates = cls._candidate_ports(ports, protocol)
        return candidates[0] if candidates else None

    # --- maintenance -------------------------------------------------------

    def clear_cache(self) -> None:
        self._cache.clear()


# --- Singleton -------------------------------------------------------------

_instance: Optional[GameQueryService] = None


def get_game_query_service() -> GameQueryService:
    """Get the singleton GameQueryService (lazy, no opengsq import on construction)."""
    global _instance
    if _instance is None:
        _instance = GameQueryService()
    return _instance


def reset_game_query_service() -> None:
    """Reset the singleton (primarily for tests)."""
    global _instance
    _instance = None
