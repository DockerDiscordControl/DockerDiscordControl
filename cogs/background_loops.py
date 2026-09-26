# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""The periodic background loops of DockerControlCog.

Moved out of cogs/docker_control.py unchanged on 2026-09-22 (roadmap Phase 3,
the cog split): heartbeat, status cache refresh, mech cache start, animation
cache warmup, inactivity check and performance cache clearing, each with its
before_loop hook. The status message edit loop stays with the message code.
_register_loop_error_handlers walks the cog class with dir(), which includes
these inherited loops.
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import tasks

from services.config.config_service import load_config
from services.config.server_config_service import get_server_config_service
from utils.logging_utils import setup_logger

from .control_helpers import _channel_has_permission
from .loop_safety import survives_one_bad_cycle

# Same logger name as the cog: log lines and log-based tests read as before the move.
logger = setup_logger('ddc.docker_control', level=logging.INFO)

# How often the inactivity check asks Discord anyway, although the gateway's
# cached last_message_id says our overview is still the newest message. That
# id is NOT corrected when a message is deleted, so an overview somebody
# removed by hand would otherwise never be noticed.
VERIFY_OVER_THE_NETWORK_EVERY = 10


def _measured_for(result, metric: str, unit: str):
    """The number THIS watcher measures for this container, or None for
    "not this watcher's container" - which ResourceWatcher reads as "not
    measured" and resets its timer for.

    Memory is measured two ways because Docker only gives one number. A
    container started with --memory has a real limit, so a percentage of it
    means something. A container started without one is reported with the
    HOST's total RAM as its limit, which made a 90 % rule fire at 56 GB: for
    20 of the operator's 26 containers the rule could never fire at all.
    Those are measured against an absolute MB threshold instead.

    memory_limited is None when nothing said which kind it is - an older
    cache entry, or a result built without the flag. Then neither watcher
    measures it, rather than guessing the yardstick.
    """
    if not result.is_running:
        return None
    if metric == 'cpu':
        return result.cpu_percent
    limited = getattr(result, 'memory_limited', None)
    if unit == '%':
        return result.memory_percent if limited is True else None
    return getattr(result, 'memory_mb', None) if limited is False else None


WATCH_STATE_FILE = "watchdog_state.json"


def _watch_state_path():
    from utils.config_paths import get_config_dir

    return get_config_dir() / WATCH_STATE_FILE


def _load_watch_state() -> dict:
    """The watchdog's last known container states, or {} (never raises)."""
    import json

    try:
        data = json.loads(_watch_state_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_watch_state(states: dict) -> None:
    import json

    from utils.atomic_io import atomic_write_text

    try:
        atomic_write_text(_watch_state_path(), json.dumps(states, indent=2, sort_keys=True))
    except OSError as e:
        logger.warning(f"[WATCHDOG] Could not keep the container states for the next start: {e}")


def _forget_watch_state() -> None:
    try:
        _watch_state_path().unlink()
    except FileNotFoundError:
        pass
    except OSError as e:
        logger.warning(f"[WATCHDOG] Could not remove {WATCH_STATE_FILE}: {e}")


class BackgroundLoopsMixin:
    """Periodic loops, mixed into DockerControlCog."""


    # --- Status Watchdog (Heartbeat) Loop ---
    @tasks.loop(minutes=5)
    @survives_one_bad_cycle
    async def heartbeat_send_loop(self):
        """
        Status Watchdog: Pings an external monitoring URL periodically.

        This implements a "Dead Man's Switch" pattern - if DDC stops running,
        the monitoring service (e.g., Healthchecks.io, Uptime Kuma) will detect
        the missing ping and send an alert.

        Security: Only outbound HTTPS requests, no tokens or data shared.
        """
        try:
            import aiohttp

            # Load heartbeat configuration
            current_config = load_config() or self.config or {}
            heartbeat_config = current_config.get('heartbeat', {})

            # ONE decision, shared with the startup banner: switched on AND
            # carrying a URL. It used to be made here a second time, so the two
            # could drift - and _heartbeat_enabled already survives a config
            # that holds null instead of an empty string (review B11), which
            # this copy did not.
            from cogs.docker_control import _heartbeat_enabled

            if not _heartbeat_enabled(current_config):
                return

            ping_url = (heartbeat_config.get('ping_url') or '').strip()

            # Security: Only allow HTTPS
            if not ping_url.startswith('https://'):
                logger.warning("[Watchdog] Monitoring URL must use HTTPS - skipping ping")
                return

            # Get interval and update loop if needed
            try:
                interval_minutes = int(heartbeat_config.get('interval', 5))
                interval_minutes = max(1, min(60, interval_minutes))  # Clamp 1-60
            except (ValueError, TypeError):
                interval_minutes = 5

            if self.heartbeat_send_loop.minutes != interval_minutes:
                try:
                    self.heartbeat_send_loop.change_interval(minutes=interval_minutes)
                    logger.info(f"[Watchdog] Interval updated to {interval_minutes} minutes")
                except Exception as e:
                    logger.warning(f"[Watchdog] Failed to update interval: {e}")

            # Ping the monitoring URL
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(ping_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        if resp.status == 200:
                            logger.debug(f"[Watchdog] Ping successful")
                        else:
                            logger.warning(f"[Watchdog] Ping returned status {resp.status}")
            except aiohttp.ClientError as e:
                logger.warning(f"[Watchdog] Ping failed: {e}")
            except Exception as e:
                logger.error(f"[Watchdog] Unexpected error during ping: {e}")

        except Exception as e:
            logger.error(f"[Watchdog] Error in heartbeat loop: {e}", exc_info=True)

    @heartbeat_send_loop.before_loop
    async def before_heartbeat_loop(self):
        """Wait until the bot is ready before starting the watchdog loop."""
        await self.bot.wait_until_ready()
        logger.info("[Watchdog] Status monitoring loop ready")

    # --- Status Cache Update Loop ---
    @tasks.loop(seconds=30)
    @survives_one_bad_cycle
    async def status_update_loop(self):
        """Periodically updates the cache with the latest container statuses."""
        # Load configuration first
        config = load_config()
        if not config:
            logger.error("Status Update Loop: Could not load configuration. Skipping cycle.")
            return

        # Get cache duration from environment
        from utils.settings import get_setting
        cache_duration = get_setting('DDC_DOCKER_CACHE_DURATION', 30)

        # Update cache TTL based on current interval
        calculated_ttl = int(cache_duration * 2.5)
        if self.cache_ttl_seconds != calculated_ttl:
            self.cache_ttl_seconds = calculated_ttl
            logger.info(f"[STATUS_LOOP] Cache TTL updated to {calculated_ttl} seconds (interval: {cache_duration}s)")
        # Keep the published interval in sync when the setting changes at runtime.
        self.status_refresh_interval_seconds = cache_duration

        # Dynamically change the loop interval if needed
        if self.status_update_loop.seconds != cache_duration:
            try:
                self.status_update_loop.change_interval(seconds=cache_duration)
                logger.info(f"[STATUS_LOOP] Cache update interval changed to {cache_duration} seconds")
            except (discord.errors.DiscordException, RuntimeError, OSError, KeyError) as e:
                logger.error(f"[STATUS_LOOP] Failed to change interval: {e}", exc_info=True)

        # Configuration already loaded and validated above
        # SERVICE FIRST: Use ServerConfigService instead of direct config access
        server_config_service = get_server_config_service()
        servers = server_config_service.get_all_servers()
        if not servers:
            return # No servers to update

        container_names = [s.get('docker_name') for s in servers if s.get('docker_name')]

        logger.debug(f"[STATUS_LOOP] Bulk updating cache for {len(container_names)} containers")
        start_time = time.time()

        try:
            # RACE CONDITION PROTECTION: Use semaphore to prevent concurrent status updates
            if not hasattr(self, '_status_update_semaphore'):
                self._status_update_semaphore = asyncio.Semaphore(1)

            async with self._status_update_semaphore:
                # Bulk fetch returns ContainerStatusResult objects
                results = await self.bulk_fetch_container_status(container_names)

                success_count = 0
                error_count = 0
                failed_names = set()

                # Process ContainerStatusResult objects
                for name, result in results.items():
                    if result.success:
                        # Cache ContainerStatusResult directly
                        self.status_cache_service.set(name, result, datetime.now(timezone.utc))
                        success_count += 1
                    else:
                        logger.warning(f"[STATUS_LOOP] Failed to fetch status for {name}. Error: {result.error_message}")
                        error_count += 1
                        failed_names.add(name)

                # Missing from the results (fetch raised) = failed, see _background_cache_population
                failed_names.update(n for n in container_names if n not in results)
                self._mark_status_cache_refreshed(failed_names)
                duration_ms = (time.time() - start_time) * 1000
                logger.info(f"[STATUS_LOOP] Cache updated: {success_count} success, {error_count} errors in {duration_ms:.1f}ms")

            await self._feed_container_watchdog(results, config)

        except (discord.errors.DiscordException, RuntimeError, ValueError, OSError) as e:
            logger.error(f"[STATUS_LOOP] Unexpected error during status update loop: {e}", exc_info=True)

    async def _feed_container_watchdog(self, results, config):
        """Hand this cycle's container states to the watchdog and its rules (Phase 4a).

        Only when an enabled container-state rule exists. One base watcher gives
        stopped/unhealthy; each distinct restart threshold/window among the rules
        gets its own watcher for restart_loop, so every rule is measured by its
        own settings. A container with a pending DDC action is "expected": a stop
        the user asked for is not an alarm. The notice channel defaults to the
        first control channel.
        """
        from services.automation.auto_action_config_service import (TRIGGER_CONTAINER_STATE,
                                                                    get_auto_action_config_service)
        from services.automation.automation_service import get_automation_service
        from services.automation.container_watch import (RESTART_LOOP, RESOURCE_KINDS, ContainerState,
                                                         ContainerWatcher, ResourceWatcher,
                                                         running_for_the_watchdog)
        from services.config.channel_roles import control_channel_ids

        rules = [r for r in get_auto_action_config_service().get_rules()
                 if r.enabled and r.trigger.type == TRIGGER_CONTAINER_STATE]
        if not rules:
            # Nothing watches, so nothing is remembered. The watchers used to be
            # kept here, and the first poll after the rules came back compared
            # against a state from days ago: a maintenance stop made meanwhile was
            # reported, and a restart rule acted on it (audit 2026-09-26).
            self.__dict__.pop('_container_watchers', None)
            _forget_watch_state()
            return
        control = control_channel_ids(config or {})
        control_id = control[0] if control else None
        if any('image_update' in r.trigger.states for r in rules):
            self._maybe_check_image_updates(list(results), control_id)
        watchers = self.__dict__.setdefault('_container_watchers', {})
        snapshot = {name: ContainerState(running_for_the_watchdog(result), getattr(result, 'health', None),
                                         getattr(result, 'restart_count', None))
                    for name, result in results.items()
                    if result.success and not getattr(result, 'not_found', False)}
        from services.automation.own_actions import expected_stops, forget as forget_own_action

        # pending_actions holds only the single-container button's action, and
        # only for a second or two; own_actions holds every stop or restart DDC
        # carried out, long enough for the next poll to see the new state.
        # monotonic, not the wall clock: an NTP correction used to delay a report
        # (a step back makes "how long has it been hot" negative) or to satisfy
        # "for five minutes" on a single sample (a step forward).
        now = time.monotonic()
        expected = set(getattr(self, 'pending_actions', {}) or {}) | expected_stops(now)
        if 'base' not in watchers:
            # A fresh process: pick up where the last one left off (F11).
            watchers['base'] = ContainerWatcher()
            watchers['base'].restore(_load_watch_state())
        base = watchers['base']
        events = [e for e in base.observe(snapshot, now, expected) if e.kind != RESTART_LOOP]
        kept = base.export()
        if kept != self.__dict__.get('_saved_watch_state'):
            _save_watch_state(kept)
            self.__dict__['_saved_watch_state'] = kept
        # The note has done its work once this poll has seen the container stopped
        for name in (n for n, state in snapshot.items() if not state.running and n in expected):
            forget_own_action(name)
        restart_keys = {(r.trigger.restart_threshold, r.trigger.restart_window_minutes)
                        for r in rules if RESTART_LOOP in r.trigger.states}
        for key in restart_keys:  # each setting observed once per cycle, however many rules share it
            if key not in watchers:
                watchers[key] = ContainerWatcher(key[0], key[1] * 60)
                watchers[key].observe(snapshot, now, expected)  # baseline, like the base watcher
                continue
            events.extend(e for e in watchers[key].observe(snapshot, now, expected) if e.kind == RESTART_LOOP)
        # Resource thresholds (Phase 4b): one watcher per metric, threshold, duration
        # and unit. Memory has TWO units - a container with a --memory limit is
        # measured in percent of it, one without against an absolute MB threshold,
        # because Docker reports the host's whole RAM as the limit when there is
        # none. So a high_memory rule builds both watchers and each is handed None
        # for the other's containers, which ResourceWatcher reads as "not measured".
        resource_keys = set()
        for rule in rules:
            for metric, kind in RESOURCE_KINDS.items():
                if kind not in rule.trigger.states:
                    continue
                if metric == 'cpu':
                    resource_keys.add(('cpu', rule.trigger.cpu_threshold_percent,
                                       rule.trigger.resource_minutes, '%'))
                else:
                    resource_keys.add(('memory', rule.trigger.memory_threshold_percent,
                                       rule.trigger.resource_minutes, '%'))
                    resource_keys.add(('memory', rule.trigger.memory_threshold_mb,
                                       rule.trigger.resource_minutes, 'MB'))
        for key in resource_keys:
            metric, threshold, minutes, unit = key
            watcher = watchers.setdefault(key, ResourceWatcher(metric, threshold, minutes, unit=unit))
            values = {name: _measured_for(result, metric, unit)
                      for name, result in results.items()
                      if result.success and not getattr(result, 'not_found', False)}
            events.extend(watcher.observe(values, now))
        # A setting no rule uses any more is forgotten, with its per-container
        # bookkeeping: the dict used to grow by one watcher per threshold the
        # operator ever typed, and a returning setting came back with its old
        # "already reported" memory, so a container hot the whole time stayed
        # unreported.
        in_use = {'base'} | restart_keys | resource_keys
        for key in [k for k in watchers if k not in in_use]:
            del watchers[key]
        if not events:
            return
        try:
            await get_automation_service().process_container_events(
                events, bot=self.bot, control_channel_id=control_id)
        except (discord.errors.DiscordException, RuntimeError, ValueError, OSError, KeyError) as e:
            logger.error(f"[WATCHDOG] Could not act on {len(events)} container event(s): {e}", exc_info=True)

    def _maybe_check_image_updates(self, container_names, control_channel_id):
        """Start the image-update check (Phase 4d) at most once per interval, as a
        tracked background task - asking registries must not delay the status loop."""
        from services.automation.image_updates import CHECK_INTERVAL_SECONDS

        now = time.monotonic()  # a duration, so the same steady clock
        last = self.__dict__.get('_last_image_check')
        if last is not None and now - last < CHECK_INTERVAL_SECONDS:
            return
        self.__dict__['_last_image_check'] = now
        task = asyncio.create_task(self._check_image_updates(container_names, control_channel_id))
        asyncio.create_task(self._track_task(task))

    async def _check_image_updates(self, container_names, control_channel_id):
        """Compare each container's image with the registry and hand updates to the rules.

        Reads the container (GET /containers/{id}/json) and its image
        (GET /images/{name}/json, the proxy's reserved read-only endpoint)
        through the client factory; asks the registry by HEAD. Never pulls.
        """
        from services.automation.automation_service import get_automation_service
        from services.automation.image_updates import (ImageUpdateChecker, read_running_image,
                                                       remote_digest)
        from services.docker_service.client_factory import build_docker_client

        checker = self.__dict__.setdefault('_image_update_checker', ImageUpdateChecker())

        def read_local(name):
            client = build_docker_client(timeout=20)
            try:
                return read_running_image(client, name)
            finally:
                client.close()

        events = []
        for name in container_names:
            try:
                image_name, ref, local = await asyncio.to_thread(read_local, name)
            except Exception as e:  # noqa: BLE001 - one container must not stop the others
                logger.info(f"[WATCHDOG] Image check skipped for {name}: {e}")
                continue
            if ref is None:
                continue
            events.extend(checker.observe(name, image_name, await remote_digest(ref), local))
        if not events:
            return
        try:
            await get_automation_service().process_container_events(
                events, bot=self.bot, control_channel_id=control_channel_id)
        except Exception as e:  # noqa: BLE001 - a tracked task's failure must not vanish
            # _track_task catches four types; anything else ended as asyncio's
            # "exception was never retrieved" with nothing in the DDC log.
            logger.error(f"[WATCHDOG] Image update notice failed: {e}", exc_info=True)

    @status_update_loop.before_loop
    async def before_status_update_loop(self):
        """Wait until the bot is ready before starting the loop."""
        await self.bot.wait_until_ready()

    # --- Mech Status Cache Startup ---
    @tasks.loop(count=1)  # Only run once to start the background loop
    async def start_mech_cache_loop(self):
        """Start the MechStatusCacheService background loop."""
        try:
            # DEBUG, and nothing after the await. start_background_loop() does
            # not start a loop and return - it IS the loop, and this task is
            # its host, so anything written after it can never run. A
            # "started successfully" line sat here and had been unreachable
            # since the day it was written; its absence read exactly like a
            # failure nobody reported.
            #
            # The service announces itself, with its interval and TTL, on a
            # logger that reaches the files since 6375c2af. A failure still
            # lands in the except clause below.
            logger.debug("Handing this task to the MechStatusCacheService loop")
            await self.mech_status_cache_service.start_background_loop()
        except (discord.errors.DiscordException, RuntimeError, ValueError, OSError) as e:
            logger.error(f"Failed to start MechStatusCacheService background loop: {e}", exc_info=True)

    @start_mech_cache_loop.before_loop
    async def before_start_mech_cache_loop(self):
        """Wait until the bot is ready before starting the mech cache."""
        await self.bot.wait_until_ready()

    # --- Initial Animation Cache Warmup (NON-BLOCKING OPTIMIZATION) ---
    @tasks.loop(count=1)  # Only run once to perform initial cache warmup
    async def initial_animation_cache_warmup(self):
        """Perform initial animation cache warmup in background after startup completes."""
        try:
            # PERFORMANCE OPTIMIZATION: Let startup complete first, then cache in background
            logger.info("Scheduling animation cache warmup in background (startup optimization)")

            # Wait for bot to be fully ready and operational
            await self.bot.wait_until_ready()

            # Additional delay to ensure Discord channels are loaded and bot is responsive
            await asyncio.sleep(15)  # Let all startup processes complete first

            logger.info("Starting background animation cache warmup...")

            from services.mech.animation_cache_service import get_animation_cache_service
            animation_cache = get_animation_cache_service()

            # Run cache warmup with parallel optimization
            await self._perform_optimized_cache_warmup(animation_cache)

            logger.info("Background animation cache warmup completed successfully")
        except (discord.errors.DiscordException, RuntimeError, ValueError, OSError) as e:
            logger.error(f"Failed to perform background animation cache warmup: {e}", exc_info=True)

    async def _perform_optimized_cache_warmup(self, animation_cache):
        """Perform cache warmup with parallel processing for better performance."""
        try:
            # Get current mech status for cache warmup
            from services.mech.mech_status_cache_service import get_mech_status_cache_service, MechStatusCacheRequest
            from services.mech.speed_levels import get_combined_mech_status

            cache_service = get_mech_status_cache_service()
            cache_request = MechStatusCacheRequest(include_decimals=True)
            mech_result = cache_service.get_cached_status(cache_request)

            if not mech_result.success:
                logger.warning("Could not get mech status for optimized warmup - using fallback")
                # Use fallback: cache current level animation
                await animation_cache.perform_initial_cache_warmup()
                return

            current_level = mech_result.level
            current_power = mech_result.power

            # Calculate current speed level
            if current_level >= 11:
                current_speed_level = 100  # Level 11 always has maximum speed
            else:
                # Real level + its power bar maximum (not a level guessed from the power amount)
                speed_status = get_combined_mech_status(
                    current_power, evolution_level=current_level,
                    power_max=getattr(getattr(mech_result, 'bars', None), 'Power_max_for_level', None))
                current_speed_level = speed_status['speed']['level']

            logger.info(f"Optimized cache warmup: Level {current_level}, Power {current_power:.2f}, Speed {current_speed_level}")

            # PARALLEL OPTIMIZATION: Generate small and big animations simultaneously
            small_task = asyncio.create_task(
                self._cache_small_animation_async(animation_cache, current_level, current_speed_level, current_power)
            )
            big_task = asyncio.create_task(
                self._cache_big_animation_async(animation_cache, current_level, current_speed_level, current_power)
            )

            # Wait for both to complete in parallel (much faster than serial)
            await asyncio.gather(small_task, big_task, return_exceptions=True)

        except (discord.errors.DiscordException, RuntimeError, ValueError) as e:
            logger.error(f"Error in optimized cache warmup: {e}", exc_info=True)
            # Fallback to original implementation
            await animation_cache.perform_initial_cache_warmup()

    async def _cache_small_animation_async(self, animation_cache, level, speed_level, power):
        """Cache small animation asynchronously."""
        try:
            logger.debug(f"Parallel caching: Small animation Level {level}, Speed {speed_level}")
            # Run in thread pool to avoid blocking the event loop
            await asyncio.to_thread(
                animation_cache.get_animation_with_speed_and_power, level, speed_level, power
            )
            logger.debug(f"Completed: Small animation Level {level}")
        except (discord.errors.DiscordException, RuntimeError, ValueError) as e:
            logger.warning(f"Failed to cache small animation: {e}")

    async def _cache_big_animation_async(self, animation_cache, level, speed_level, power):
        """Cache big animation asynchronously."""
        try:
            logger.debug(f"Parallel caching: Big animation Level {level}, Speed {speed_level}")
            # Run in thread pool to avoid blocking the event loop
            await asyncio.to_thread(
                animation_cache.get_animation_with_speed_and_power_big, level, speed_level, power
            )
            logger.debug(f"Completed: Big animation Level {level}")
        except (discord.errors.DiscordException, RuntimeError, ValueError) as e:
            logger.warning(f"Failed to cache big animation: {e}")

    @initial_animation_cache_warmup.before_loop
    async def before_initial_animation_cache_warmup(self):
        """Minimal delay before starting background cache warmup."""
        # No additional wait needed - the loop itself handles timing
        pass

    # --- Inactivity Check Loop ---
    @tasks.loop(seconds=30)
    @survives_one_bad_cycle
    async def inactivity_check_loop(self):
        """Checks for channel inactivity and regenerates messages if needed."""
        config = load_config()
        if not config:
            logger.error("Inactivity Check Loop: Could not load configuration. Skipping cycle.")
            return

        now_utc = datetime.now(timezone.utc)
        channel_permissions = config.get('channel_permissions', {})

        try:
            if not self.initial_messages_sent:
                logger.info("Inactivity check loop: Initial messages not sent yet, skipping.")
                return

            logger.debug("Inactivity check loop running")

            # Bookkeeping, not news: this said the same thing every thirty
            # seconds whatever happened. The cycle reports itself when it acts.
            logger.debug(f"Currently tracking {len(self.last_channel_activity)} channels for activity: {list(self.last_channel_activity.keys())}")

            # Check each channel we've previously registered activity for
            for channel_id, last_activity_time in list(self.last_channel_activity.items()):
                channel_config = channel_permissions.get(str(channel_id))

                logger.debug(f"Checking channel {channel_id}")

                # Skip channels with no config
                if not channel_config:
                    logger.debug(f"Channel {channel_id} has no specific config, skipping")
                    continue

                recreate_enabled = channel_config.get('recreate_messages_on_inactivity', True)
                timeout_minutes = channel_config.get('inactivity_timeout_minutes', 10)

                logger.debug(f"Channel {channel_id} - recreate_enabled={recreate_enabled}, timeout_minutes={timeout_minutes}")

                if not recreate_enabled or timeout_minutes <= 0:
                    logger.debug(f"Channel {channel_id} - Recreate disabled or timeout <= 0, skipping")
                    continue

                # Calculate time since last activity
                time_since_last_activity = now_utc - last_activity_time
                inactivity_threshold = timedelta(minutes=timeout_minutes)

                logger.debug(f"Channel {channel_id} - Time since last activity: {time_since_last_activity}, threshold: {inactivity_threshold}")

                # Check if we've passed the inactivity threshold
                if time_since_last_activity >= inactivity_threshold:
                    # NOT logger.info. This says what is about to be CONSIDERED,
                    # and in the overwhelming majority of cycles the answer is
                    # "nothing to do" - the operator read 36 of these lines in 18
                    # minutes and concluded his panels were being recreated twice a
                    # minute. They were not. Only an actual regeneration is news.
                    logger.debug(f"Channel {channel_id} has been inactive for {time_since_last_activity}, checking whether the overview is still at the bottom")

                    try:
                        # The cheap answer first. Asking Discord costs a
                        # fetch_channel plus a history read per channel per cycle -
                        # on a one-minute timeout some 5,760 calls a day - to learn
                        # almost every time that nothing moved. The gateway already
                        # knows the newest message id, and while that is still one
                        # of our own tracked overviews there is nothing to do.
                        cached_channel = self.bot.get_channel(channel_id)
                        cached_last_message_id = getattr(cached_channel, 'last_message_id', None)
                        tracked_ids = set(self.channel_server_message_ids.get(channel_id, {}).values())
                        tracked_ids.discard(None)
                        skipped = self.__dict__.setdefault('_inactivity_cheap_skips', {})

                        if (cached_last_message_id is not None and cached_last_message_id in tracked_ids
                                and skipped.get(channel_id, 0) < VERIFY_OVER_THE_NETWORK_EVERY):
                            skipped[channel_id] = skipped.get(channel_id, 0) + 1
                            self.last_channel_activity[channel_id] = now_utc
                            logger.debug(f"Channel {channel_id}: our overview {cached_last_message_id} is still the newest message (cached) - nothing to do")
                            continue
                        skipped[channel_id] = 0

                        # Fetch the Discord channel
                        channel = await self.bot.fetch_channel(channel_id)

                        if not isinstance(channel, discord.TextChannel):
                            logger.warning(f"Channel {channel_id} is not a text channel, removing from activity tracking")
                            del self.last_channel_activity[channel_id]
                            continue

                        logger.debug(f"Successfully fetched channel {channel.name} ({channel_id})")

                        # Check the last message to confirm inactivity
                        history = await channel.history(limit=3).flatten()

                        logger.debug(f"Found {len(history)} messages in recent history for channel {channel.name}")

                        # If there are no messages at all, regenerate
                        if not history:
                            logger.info(f"No messages found in channel {channel.name} ({channel_id}). Regenerating")
                            # Determine the mode: control or status
                            has_control_permission = _channel_has_permission(channel_id, 'control', config)
                            regeneration_mode = 'control' if has_control_permission else 'status'
                            logger.debug(f"Regeneration mode for empty channel: {regeneration_mode}")
                            await self._regenerate_channel(channel, regeneration_mode, config)
                            self.last_channel_activity[channel_id] = now_utc
                            continue

                        # Check if the last message is from our bot
                        # Safety check: ensure bot.user is available
                        if self.bot.user is None:
                            logger.warning(f"Bot user is None, cannot check message author. Skipping channel {channel_id}")
                            continue

                        last_msg = history[0]
                        bot_user_id = self.bot.user.id

                        # Log detailed info for debugging recreation issues
                        logger.debug(f"Channel {channel.name}: Last message author={last_msg.author.id} ({last_msg.author.name}), bot_id={bot_user_id}")

                        # Check if last message is from our bot (by user ID or application ID)
                        bot_app_id = getattr(self.bot, 'application_id', None)
                        is_from_bot = (last_msg.author.id == bot_user_id or
                                      (hasattr(last_msg, 'application_id') and bot_app_id and last_msg.application_id == bot_app_id))

                        if is_from_bot:
                            # FIX A: Distinguish our OWN managed overview/admin-overview (already at
                            # the bottom -> nothing to do) from a STRAY bot message such as a
                            # restart/update notification that has buried our overview.
                            if not self._overview_buried_by_stray(channel_id, last_msg.id):
                                self.last_channel_activity[channel_id] = now_utc
                                logger.debug(f"Last message in channel {channel.name} ({channel_id}) is our managed overview (or no tracking) - resetting inactivity timer, no regeneration")
                                continue

                            # Our overview is buried under a stray bot message -> move it to the bottom
                            logger.info(f"Channel {channel.name} ({channel_id}): own overview buried under stray bot message {last_msg.id} - will regenerate to move it to the bottom")
                        else:
                            # The last message is from a user (foreign), regenerate as before
                            logger.info(f"Last message in channel {channel.name} is NOT from our bot (author_id={last_msg.author.id}, bot_id={bot_user_id}). Will regenerate")

                        # Determine the mode: control or status
                        has_control_permission = _channel_has_permission(channel_id, 'control', config)
                        has_status_permission = _channel_has_permission(channel_id, 'serverstatus', config)

                        logger.debug(f"Channel permissions - control: {has_control_permission}, status: {has_status_permission}")

                        regeneration_mode = 'control' if has_control_permission else 'status'

                        # Force the mode to be valid
                        if not has_control_permission and not has_status_permission:
                            logger.warning(f"Channel {channel.name} has neither control nor status permissions. Cannot regenerate")
                            continue

                        logger.debug(f"Will regenerate with mode: {regeneration_mode}")

                        # FIX A USED TO STAND HERE: don't regenerate while a user is
                        # mid-interaction, because deleting the message they are
                        # pressing would no-op their click. The only thing that ever
                        # marked an interaction was the mech expand/collapse pair, so
                        # with those gone the check answered False for every channel,
                        # every cycle. The per-channel lock below is what actually
                        # serialises a delete-and-post today (FIX B).

                        # Attempt channel regeneration with improved error handling
                        try:
                            logger.debug(f"Starting inactivity regeneration for {channel.name} ({channel_id}) in mode '{regeneration_mode}'")
                            await self._regenerate_channel(channel, regeneration_mode, config)

                            # Reset activity timer only on successful regeneration
                            self.last_channel_activity[channel_id] = now_utc
                            logger.info(f"✅ Channel {channel.name} ({channel_id}) successfully regenerated due to inactivity. Mode: {regeneration_mode}")

                        except (discord.errors.DiscordException, RuntimeError, OSError) as regen_error:
                            logger.error(f"❌ Failed to regenerate channel {channel.name} ({channel_id}) due to inactivity: {regen_error}", exc_info=True)
                            # Don't reset activity timer on failure - try again next cycle
                            # But prevent infinite retries by adding a small delay
                            error_delay = timedelta(minutes=2)
                            self.last_channel_activity[channel_id] = now_utc - inactivity_threshold + error_delay
                            logger.warning(f"Delaying next regeneration attempt for {channel.name} by {error_delay}")

                    except discord.NotFound:
                        logger.warning(f"Channel {channel_id} not found. Removing from activity tracking")
                        del self.last_channel_activity[channel_id]
                    except discord.Forbidden:
                        logger.error(f"Cannot access channel {channel_id} (forbidden). Continuing tracking but regeneration not possible")
                    except (discord.errors.DiscordException, RuntimeError, OSError) as e:
                        logger.error(f"Error during inactivity check for channel {channel_id}: {e}", exc_info=True)
                else:
                    logger.debug(f"Channel {channel_id} - Inactivity threshold not reached yet")
        except (discord.errors.DiscordException, RuntimeError, ValueError) as e:
            logger.error(f"Error in inactivity_check_loop: {e}", exc_info=True)

    @inactivity_check_loop.before_loop
    async def before_inactivity_check_loop(self):
        """Wait until the bot is ready before starting the loop."""
        await self.bot.wait_until_ready()

    # --- Performance Cache Clear Loop ---
    @tasks.loop(minutes=5)
    @survives_one_bad_cycle
    async def performance_cache_clear_loop(self):
        """Clears performance caches every 5 minutes to prevent memory buildup."""
        try:
            logger.debug("Running performance cache clear loop")

            # Import and clear the control UI performance caches
            from .control_ui import _clear_caches
            _clear_caches()

            # Clear any other performance-critical caches
            if hasattr(self, '_embed_cache'):
                # Clear embed cache if it's getting too large (>100 entries)
                if len(self._embed_cache.get('translated_terms', {})) > 100:
                    self._embed_cache['translated_terms'].clear()
                    logger.debug("Cleared embed translation cache due to size")

                if len(self._embed_cache.get('box_elements', {})) > 100:
                    self._embed_cache['box_elements'].clear()
                    logger.debug("Cleared embed box elements cache due to size")

            logger.debug("Performance cache clear completed")

        except (discord.errors.DiscordException, RuntimeError, ValueError,
                ImportError, TypeError, AttributeError) as e:
            # ImportError for the deferred import of _clear_caches, and
            # TypeError/AttributeError for len()/.clear() on an _embed_cache
            # entry that is not a mapping - the three this body can actually
            # produce and did not name. The decorator above is the second
            # answer: even something not listed here costs one cycle, not the
            # loop.
            logger.error(f"Error in performance_cache_clear_loop: {e}", exc_info=True)

    @performance_cache_clear_loop.before_loop
    async def before_performance_cache_clear_loop(self):
        """Wait until the bot is ready before starting the loop."""
        await self.bot.wait_until_ready()
