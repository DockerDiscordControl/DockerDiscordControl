# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Automation Service                             #
# ============================================================================ #
"""
Service First: The "Brain" of the Auto-Action System.
Handles message matching (keywords, regex, fuzzy), safety checks, and execution.
"""

import logging
import re
import asyncio
import difflib
import multiprocessing
from typing import List, Optional, Dict, Any
from dataclasses import dataclass

from .auto_action_config_service import (TRIGGER_CONTAINER_STATE, TRIGGER_MESSAGE, AutoActionRule,
                                         get_auto_action_config_service)
from .auto_action_state_service import get_auto_action_state_service

# Import Docker Control (we reuse existing utils to ensure consistency)
from services.docker_service.docker_utils import docker_action, is_container_exists, get_docker_info
from cogs.translation_manager import _
from services.discord.embed_helper_service import fit_lines

logger = logging.getLogger('ddc.automation_service')

# Actions gated by the rule's only_if_running safety option. START is excluded (the
# option would turn every START rule into a no-op), NOTIFY doesn't touch the container.
ONLY_IF_RUNNING_ACTIONS = {"RESTART", "RECREATE", "STOP"}

# Hard budget for one trigger regex, enforced by killing the worker process.
REGEX_TIMEOUT_SECONDS = 0.5


def _regex_search_worker(pattern: str, text: str, conn) -> None:
    """Run one regex search in a child process and send back the boolean result.

    Module level (not a method) so it can be pickled for the "spawn" start method.
    """
    try:
        conn.send(bool(re.search(pattern, text, re.IGNORECASE | re.MULTILINE)))
    except Exception:
        conn.send(False)
    finally:
        try:
            conn.close()
        except Exception:
            pass

@dataclass
class TriggerContext:
    """Context object for the trigger event."""
    message_id: str
    channel_id: str
    guild_id: str
    user_id: str
    username: str
    is_webhook: bool
    content: str
    embeds_text: str  # Consolidated text from embeds

    @property
    def full_text(self) -> str:
        """Combined content and embeds for searching."""
        return f"{self.content}\n{self.embeds_text}".lower()

    @property
    def message_link(self) -> str:
        """Discord message link."""
        return f"https://discord.com/channels/{self.guild_id}/{self.channel_id}/{self.message_id}"

# One spelling for every group target (services/config/group_service.py).
from services.config.group_service import GROUP_PREFIX


# What a rule's action needs the group to be allowed to do. RECREATE has no box
# of its own: it is a restart that comes back on a new image, and Restart is the
# box an operator associates with it - asking for two he never connected to it
# would block rules that work today. NOTIFY asks for nothing, because it does
# nothing to a container.
ACTION_NEEDS = {"RESTART": "restart", "STOP": "stop", "START": "start",
                "RECREATE": "restart", "NOTIFY": None}


def _members_of_group(name: str, action: Optional[str] = None) -> list:
    """The containers of a group, or an empty list when it is gone.

    A group that was deleted resolves to nothing - never to "all", which is
    what an empty trigger list means. See rule_listens_to.

    With ``action``, the GROUP's own permissions decide whether it resolves at
    all (operator, 2026-09-24): a group he switched off, or one he did not
    allow that action, acts on nobody - whatever its members may do on their
    own. Without ``action`` nothing is gated, which is the trigger side: a
    permission says what may be DONE, not what may be WATCHED.
    """
    try:
        from services.config.group_service import get_group_service

        service = get_group_service()
        members = service.members_of(name)
        group = service.find(name) if action is not None else None
    except OSError as e:
        logger.error(f"Groups could not be read for a rule: {e}")
        return []
    if not members.exists:
        logger.warning(f"A rule names the group '{name}', which does not exist any more")
        return []
    if action is not None:
        needed = ACTION_NEEDS.get((action or "").upper(), (action or "").lower())
        if group is None or not group.active:
            logger.info(f"A rule would act on the group '{name}', which is switched off")
            return []
        if needed is not None and needed not in group.allowed_actions:
            logger.info(f"A rule would {action} the group '{name}', which may not")
            return []
    return list(members.containers)


def _resolved(names, action: Optional[str] = None) -> list:
    """Container names, with every "group:<name>" replaced by its members.

    Order is kept and a container named twice - directly and through a group -
    is acted on once. ``action`` is passed on to the groups; see there.
    """
    resolved = []
    for entry in names or []:
        if isinstance(entry, str) and entry.startswith(GROUP_PREFIX):
            candidates = _members_of_group(entry[len(GROUP_PREFIX):], action)
        else:
            candidates = [entry]
        for container in candidates:
            if container not in resolved:
                resolved.append(container)
    return resolved


def rule_listens_to(rule, container: str) -> bool:
    """Whether a container-state rule is about this container.

    An EMPTY trigger list means every container - that is the meaning it has
    always had. A list that names only groups which no longer exist resolves
    to nothing and the rule listens to NOTHING, because the alternative is a
    rule written for five containers quietly firing on all of them.
    """
    if not rule.trigger.containers:
        return True
    return container in _resolved(rule.trigger.containers)


# DDC's own container name, looked up once (None: not known yet, "": none).
_own_name: Optional[str] = None


def _own_container_name() -> str:
    """The name of the container DDC runs in, or "" outside one.

    Blocking (one Docker call through the proxy) - callers run it in a thread.
    A failed lookup is not remembered, so the next action asks again.
    """
    global _own_name
    if _own_name is None:
        from services.docker_service.self_restart import describe_self, own_container_id

        if not own_container_id():
            _own_name = ""
        else:
            ok, name = describe_self()
            if not ok:
                return ""
            _own_name = name
    return _own_name


async def protected_names(settings: Dict) -> set:
    """The containers no rule may act on: the configured list AND DDC itself.

    THE LIST ALONE DID NOT HOLD DDC. Its default names "ddc", and the
    container is called "dockerdiscordcontrol" on the operator's server and in
    every template (audit 2026-09-26). A rule with no container list and
    RESTART on high_memory would have restarted DDC - and the process dies
    before the cooldown is written, so it would do it again every time.
    """
    names = {str(p).lower() for p in settings.get('protected_containers', []) or []}
    own = await asyncio.to_thread(_own_container_name)
    if own:
        names.add(own.lower())
    return names


def rule_may_act_on(rule, container: str) -> bool:
    """Whether a container-state rule may DO its action to this container.

    Such a rule acts on the container the event is about, not on its action
    list, so containers_of_action never saw it - and until 2026-09-26 a rule
    reaching a container only through "group:<name>" went on restarting it
    after the operator switched the group off or took its box away. A
    container named directly, or a rule with no container list, involves no
    group and is not gated here. NOTIFY does nothing, so it is never gated.
    """
    action = getattr(rule.action, "type", None)
    if ACTION_NEEDS.get((action or "").upper(), "") is None:
        return True
    entries = rule.trigger.containers or []
    if not entries or container in entries:
        return True
    groups = [entry for entry in entries
              if isinstance(entry, str) and entry.startswith(GROUP_PREFIX)]
    return container in _resolved(groups, action)


def containers_of_action(rule) -> list:
    """The containers a rule's action is about, groups resolved.

    A group only resolves here if it is allowed to do what the rule does.
    """
    return _resolved(rule.action.containers, getattr(rule.action, "type", None))


class AutomationService:
    """Core logic for Auto-Actions."""

    def __init__(self):
        self.config_service = get_auto_action_config_service()
        self.state_service = get_auto_action_state_service()
        logger.info("AutomationService initialized")

    async def process_message(self, context: TriggerContext, bot_instance=None) -> List[str]:
        """
        Main entry point: Process a Discord message against all rules.
        
        Args:
            context: The message context
            bot_instance: Discord bot instance (for sending feedback)
            
        Returns:
            List of executed rule names (for logging/debug)
        """
        # 1. Global Check
        settings = self.config_service.get_global_settings()
        if not settings.get('enabled', True):
            return []

        # 2. Get Candidates (Filter by Channel/User first for performance)
        rules = self.config_service.get_rules()
        candidates = self._pre_filter_rules(rules, context)
        
        if not candidates:
            return []

        executed_rules = []
        
        # 3. Deep Matching (Regex/Keywords)
        # We sort by priority (descending) to execute highest priority first
        candidates.sort(key=lambda r: r.priority, reverse=True)
        
        for rule in candidates:
            # Check Trigger Match
            is_match, match_reason = await self._check_match(rule, context)
            
            if is_match:
                logger.info(f"AAS Match: Rule '{rule.name}' matched on {match_reason}")
                
                # 4. Safety Checks (Cooldowns, Protected Containers)
                try:
                    if await self._execute_rule(rule, context, settings, bot_instance):
                        executed_rules.append(rule.name)
                except BaseException as e:
                    # BaseException on purpose: a cancellation must reach whoever
                    # issued it, and the locks still have to go - so it is caught
                    # here, the release runs, and the handler re-raises at the end
                    # (review C60). It used to be named in the tuple and swallowed
                    # like an ordinary error.
                    # _execute_rule locks every target container up front. An exception in the
                    # middle (e.g. DockerConnectionError when the socket blips, or cancellation
                    # during the action delay) would otherwise leave them locked for the rule
                    # cooldown - 24 h by default, and persisted on the next trigger. Release
                    # what this rule holds so the next trigger can run (V2 review B1).
                    # A failed release used to be logged at DEBUG while the line
                    # below said "released" regardless - the log claimed the
                    # opposite of what happened, and the container stayed locked
                    # for up to the rule cooldown unnoticed (SPEC.md Z8).
                    still_locked = []
                    # The same list _execute_rule locked: groups resolved, or the
                    # release would look for a container named "group:<name>" and
                    # leave the real ones locked for the rule cooldown.
                    for container in containers_of_action(rule):
                        try:
                            self.state_service.release_execution_lock(rule.id, container, success=False)
                        except Exception:  # never mask the original error
                            still_locked.append(container)
                            logger.error(f"AAS: could not release the cooldown of '{container}' - it stays "
                                         f"locked for rule '{rule.name}' until the cooldown runs out",
                                         exc_info=True)
                    outcome = ("released its container cooldowns" if not still_locked
                               else f"could NOT release the cooldowns of {', '.join(still_locked)}")
                    if isinstance(e, Exception):
                        logger.error(f"AAS: Rule '{rule.name}' failed with {type(e).__name__}: {e}; "
                                     f"{outcome}", exc_info=True)
                    else:
                        # A cancellation or a shutdown signal is not a failure of
                        # the rule, and it is not this loop's to swallow.
                        logger.warning(f"AAS: Rule '{rule.name}' was stopped by "
                                       f"{type(e).__name__}; {outcome}")
                        raise
                    
        return executed_rules

    def _pre_filter_rules(self, rules: List[AutoActionRule], ctx: TriggerContext) -> List[AutoActionRule]:
        """Fast filter rules based on metadata (Channel, User)."""
        candidates = []
        for rule in rules:
            if not rule.enabled:
                continue
            # Container-state rules fire on watchdog events, never on a message -
            # with no channel list they would otherwise pass the channel check below.
            if rule.trigger.type != TRIGGER_MESSAGE:
                continue
                
            # Channel Check
            if rule.trigger.channel_ids and str(ctx.channel_id) not in rule.trigger.channel_ids:
                continue
                
            # Source Check (User ID) - if whitelist is set, must match
            if rule.trigger.allowed_user_ids and str(ctx.user_id) not in rule.trigger.allowed_user_ids:
                # Also check allowed usernames (less secure but requested)
                if not (rule.trigger.allowed_usernames and ctx.username in rule.trigger.allowed_usernames):
                    continue
            
            # Webhook Check
            if rule.trigger.is_webhook is not None:
                if rule.trigger.is_webhook != ctx.is_webhook:
                    continue
                    
            candidates.append(rule)
        return candidates

    async def _check_match(self, rule: AutoActionRule, ctx: TriggerContext) -> tuple[bool, str]:
        """Check text content against keywords/regex (Async wrapper)."""
        
        # Determine search scope
        search_text = ""
        if "content" in rule.trigger.search_in:
            search_text += ctx.content + "\n"
        if "embeds" in rule.trigger.search_in:
            search_text += ctx.embeds_text
            
        search_text = search_text.lower() # Case insensitive (Question 7)
        
        # 1. Regex Match (Question 3: Security via Threading + Timeout)
        if rule.trigger.regex_pattern:
            try:
                # The real budget is enforced inside _safe_regex_search by killing the worker
                # process; this timeout only bounds process start-up and teardown, which a
                # cancelled await CAN interrupt.
                matched = await asyncio.wait_for(
                    asyncio.to_thread(
                        self._safe_regex_search,
                        rule.trigger.regex_pattern,
                        search_text
                    ),
                    timeout=REGEX_TIMEOUT_SECONDS + 10
                )
                if matched:
                    return True, f"Regex: {rule.trigger.regex_pattern}"
                # Regex didn't match - if this is a regex-only rule, return here
                if not rule.trigger.keywords:
                    return False, f"Regex pattern did not match: {rule.trigger.regex_pattern[:50]}"
            except asyncio.TimeoutError:
                logger.warning(f"AAS: Regex timeout in rule '{rule.name}' - pattern may be too complex")
                # If regex-only rule, fail; otherwise try keywords
                if not rule.trigger.keywords:
                    return False, "Regex timeout (pattern too complex)"
            except Exception as e:
                logger.error(f"Regex error in rule '{rule.name}': {e}")
                # Don't fail the whole rule if keywords exist, try them next

        # 2. Negative Lookahead (Ignore Keywords) - Check first
        for ignore in rule.trigger.ignore_keywords:
            if ignore.lower() in search_text:
                return False, f"Ignored keyword: {ignore}"

        # 3. Required Keywords - ALL must match (AND logic)
        if rule.trigger.required_keywords:
            missing_required = []
            for req_kw in rule.trigger.required_keywords:
                if req_kw.lower() not in search_text:
                    missing_required.append(req_kw)

            if missing_required:
                return False, f"Missing required keyword(s): {', '.join(missing_required)}"

        # 4. Trigger Keywords - At least one must match (based on match_mode)
        # If no trigger keywords defined but required keywords matched, that's enough
        if not rule.trigger.keywords:
            if rule.trigger.required_keywords:
                return True, f"Required keyword(s) matched: {', '.join(rule.trigger.required_keywords)}"
            return False, "No trigger conditions configured"

        # Match Logic for trigger keywords
        matched_keywords = []
        for keyword in rule.trigger.keywords:
            kw = keyword.lower()

            # Exact substring match
            if kw in search_text:
                matched_keywords.append(kw)
                continue

            # Fuzzy Match (Question 8) - Only if keyword is long enough
            if len(kw) > 4:
                # Check against words in text
                words = search_text.split()
                for word in words:
                    ratio = difflib.SequenceMatcher(None, kw, word).ratio()
                    if ratio > 0.85: # 85% similarity threshold
                        matched_keywords.append(f"{kw}~{word}")
                        break

        if rule.trigger.match_mode == "all":
            if len(matched_keywords) == len(rule.trigger.keywords):
                return True, f"All keywords: {matched_keywords}"
        else: # "any"
            if len(matched_keywords) > 0:
                return True, f"Keyword: {matched_keywords[0]}"

        return False, "No trigger keyword matched"

    def _safe_regex_search(self, pattern: str, text: str) -> bool:
        """Regex search with a hard timeout, run in a separate PROCESS.

        A thread cannot be cancelled and CPython's ``re`` never releases the GIL, so a
        catastrophic pattern would freeze the whole bot (measured: 1.3 s for 23 characters,
        exponential from there) no matter what timeout the caller uses. A process can be
        killed, so the budget is real (V2 review B2). Falls back to an in-process search
        only if a worker cannot be started; validation rejects the dangerous shapes.
        """
        # Basic protection: Cap input size
        if len(text) > 10000:
            text = text[:10000]

        try:
            # "fork" (Linux, the only platform the image runs on): the child inherits the
            # already-imported modules. "spawn" would re-import the main module, which fails
            # inside the bot and under pytest ("start a new process before the current process
            # has finished its bootstrapping phase") and made every search return False.
            methods = multiprocessing.get_all_start_methods()
            ctx = multiprocessing.get_context("fork" if "fork" in methods else "spawn")
            parent_conn, child_conn = ctx.Pipe(duplex=False)
            proc = ctx.Process(target=_regex_search_worker,
                               args=(pattern, text, child_conn), daemon=True)
            proc.start()
            child_conn.close()
            got_result = parent_conn.poll(REGEX_TIMEOUT_SECONDS)
            result = parent_conn.recv() if got_result else None
            parent_conn.close()

            if got_result:
                # Result is in; the child may still be exiting - that is not a timeout.
                proc.join(timeout=1)
                if proc.is_alive():
                    proc.kill()
                    proc.join(timeout=1)
                return bool(result)

            # No result within the budget: this is the ReDoS case, kill the worker.
            if proc.is_alive():
                proc.kill()  # the budget is enforced here, not by a cancelled await
                proc.join(timeout=1)
                logger.warning(f"AAS: regex search exceeded {REGEX_TIMEOUT_SECONDS}s and was "
                               f"killed - pattern too complex: {pattern[:60]}")
                return False

            # Worker died without sending anything (crash, OOM): don't report "no match",
            # that would silently disable the rule. Fall back to an in-process search.
            proc.join(timeout=1)
            logger.warning(f"AAS: regex worker exited without a result (exit code "
                           f"{proc.exitcode}); falling back to an in-process search")
            return bool(re.search(pattern, text, re.IGNORECASE | re.MULTILINE))
        except Exception as e:
            logger.error(f"AAS: could not run the regex in a worker process ({e}); "
                         f"falling back to an in-process search", exc_info=True)
            try:
                return bool(re.search(pattern, text, re.IGNORECASE | re.MULTILINE))
            except Exception:
                return False

    async def _execute_rule(self, rule: AutoActionRule, ctx: TriggerContext, 
                           global_settings: Dict, bot) -> bool:
        """Execute the action defined in the rule."""
        
        # 1. Check Protected Containers (Question 18)
        protected = await protected_names(global_settings)
        # Groups resolved: a rule may target "group:<name>", and asking Docker
        # to restart a container of that name would simply fail. A group that
        # is gone resolves to nothing, and nothing is what happens.
        target_containers = containers_of_action(rule)
        
        for container in target_containers:
            if container.lower() in protected:
                logger.warning(f"AAS: Blocked action on protected container '{container}'")
                self.state_service.record_trigger(
                    rule.id, rule.name, container, rule.action.type, "SKIPPED", "Protected container"
                )
                return False

        # 2. Check Cooldowns with atomic lock (Question 17/14)
        # One atomic check-and-set for ALL target containers: the global cooldown is checked
        # once per rule (so a multi-container rule can't block itself) and nothing is locked
        # unless every container passes.
        can_execute, reason, blocked_container = self.state_service.acquire_execution_locks(
            rule.id,
            target_containers,
            global_settings.get('global_cooldown_seconds', 30),
            rule.cooldown_minutes,
            rule.cooldown_scope
        )
        if not can_execute:
            logger.info(f"AAS: Skipped rule '{rule.name}' - {reason}")
            self.state_service.record_trigger(
                rule.id, rule.name, blocked_container, rule.action.type, "SKIPPED", reason
            )
            return False

        # 3. Execute Action (Action 11, 9)
        # We execute actions sequentially for now
        action_type = rule.action.type.upper()
        success_count = 0
        skipped_not_running = []  # targets skipped by only_if_running -> one Discord notice

        # One announcement for the whole rule, not one per container: a ticked
        # group of 200 members was 200 messages into one channel, and Discord's
        # rate limit stops them long before the containers are done. The
        # only_if_running notices were consolidated for the same reason.
        if not rule.action.silent and bot and target_containers:
            delay_info = (f" ({rule.action.delay_seconds}s delay)"
                          if rule.action.delay_seconds > 0 else "")
            named = fit_lines([f"**{name}**" for name in target_containers], separator=", ",
                              limit=1500,
                              more=lambda count: _("… and {count} more").format(count=count))
            await self._send_feedback(
                bot, rule.action.notification_channel_id or ctx.channel_id,
                f"⚡ `{action_type}` {named}{delay_info} — *{rule.name}* · "
                f"[Trigger]({ctx.message_link})")

        for container in target_containers:
            logger.info(f"AAS: Executing {action_type} on {container}...")
            
            # Three answers, not two: True, False, or None when DDC could not
            # ask. Only a definite False is "not found" - an unreachable Docker
            # used to produce the same verdict, so the operator was told their
            # container was gone and the action was skipped. An unknown falls
            # THROUGH to the action, exactly as an unknown running state does
            # below (review E25): if the container really is gone, the Docker
            # call says so with Docker's own reason.
            exists = await is_container_exists(container)
            if exists is None:
                logger.warning(f"AAS: could not check whether '{container}' exists - "
                               f"attempting {action_type} anyway")
            if exists is False:
                logger.warning(f"AAS: Container '{container}' not found")
                self.state_service.record_trigger(
                    rule.id, rule.name, container, rule.action.type, "FAILED", "Container not found"
                )
                if not rule.action.silent and bot:
                    await self._send_feedback(
                        bot,
                        rule.action.notification_channel_id or ctx.channel_id,
                        f"⚠️ Container `{container}` not found — *{rule.name}*"
                    )
                continue

            # Safety: only_if_running - don't touch a container that was stopped on purpose.
            # Only a confirmed "not running" skips; an unknown state falls through to the
            # action - and now says so (review E25). See _honours_only_if_running.
            if rule.only_if_running and action_type in ONLY_IF_RUNNING_ACTIONS:
                if await self._honours_only_if_running(rule, action_type, container):
                    skip_reason = "Container not running (only_if_running)"
                    logger.info(f"AAS: Skipped {action_type} on '{container}' for rule '{rule.name}' - {skip_reason}")
                    # Nothing was executed - release the cooldown acquired above
                    self.state_service.release_execution_lock(rule.id, container, success=False)
                    self.state_service.record_trigger(
                        rule.id, rule.name, container, rule.action.type, "SKIPPED", skip_reason
                    )
                    skipped_not_running.append(container)
                    continue

            notification_channel_id = rule.action.notification_channel_id or ctx.channel_id

            # Handle Delay
            if rule.action.delay_seconds > 0:
                await asyncio.sleep(rule.action.delay_seconds)

            # Docker Action
            result = False
            error_detail = ""
            
            if action_type == "NOTIFY":
                result = True # Already notified above
            
            elif action_type == "RECREATE":
                # Question 9: Implies Pull + Restart
                # DockerUtils doesn't support pull yet directly in simple calls, 
                # so we map RECREATE to RESTART for V1 MVP, but logging intent.
                # Real implementation would need DockerClientPool expansion.
                logger.info(f"AAS: Recreate requested - executing Restart (MVP)")
                result = await docker_action(container, "restart")
                
            elif action_type in ["START", "STOP", "RESTART"]:
                result = await docker_action(container, action_type.lower())
                
            # Record Result
            status = "SUCCESS" if result else "FAILED"
            self.state_service.record_trigger(
                rule.id, rule.name, container, action_type, status, error_detail
            )

            if result:
                success_count += 1
                # Trigger status refresh after successful action
                await self._trigger_status_refresh(bot, container)
            else:
                # Question 11: Force Kill logic would go here in V2
                if not rule.action.silent and bot:
                    await self._send_feedback(
                        bot, notification_channel_id,
                        f"⚠️ `{action_type}` **{container}** failed — *{rule.name}*"
                    )

        # Increment trigger count if at least one action succeeded
        if success_count > 0:
            self.config_service.increment_trigger_count(rule.id)
        else:
            # Nothing was executed: free the rule's own cooldown, once. The per-container
            # outcomes no longer touch it - otherwise one failed container wiped the
            # cooldown the successful one had just set (review B10).
            self.state_service.release_rule_cooldown(rule.id)

        # only_if_running skips were only visible in the history: post ONE notice per rule
        # trigger, same channel and silent handling as the other feedback messages
        if skipped_not_running and not rule.action.silent and bot:
            await self._send_feedback(
                bot,
                rule.action.notification_channel_id or ctx.channel_id,
                self._only_if_running_notice(rule.name, skipped_not_running)
            )

        return success_count > 0

    async def process_container_events(self, events, bot=None, control_channel_id=None) -> List[str]:
        """Run the container-state rules against the watchdog's events.

        The second trigger type of the auto-action system (Phase 4a). The notice
        goes to the rule's notification channel, or the control channel when the
        rule names none (operator decision 2026-09-22).
        """
        settings = self.config_service.get_global_settings()
        if not settings.get('enabled', True) or not events:
            return []
        rules = sorted((r for r in self.config_service.get_rules()
                        if r.enabled and r.trigger.type == TRIGGER_CONTAINER_STATE),
                       key=lambda r: r.priority, reverse=True)
        executed = []
        # NO GLOBAL COOLDOWN FOR WATCHDOG EVENTS. Its job is to stop a chatty
        # Discord channel from firing rules every second; a watchdog event
        # happens once per state change, and the watcher has already stored the
        # new state - an event held back is an event lost. It was checked once
        # per poll until 2026-09-26, which still lost every event of a poll that
        # came within 30 s of one that acted (every poll, at the default
        # interval), and every event after a first one that was refused. The
        # per-rule-and-container cooldown still applies to each of them.
        global_cooldown = 0
        for event in events:
            for rule in rules:
                if event.kind not in rule.trigger.states:
                    continue
                if not rule_listens_to(rule, event.container):
                    continue
                if not self._measured_by_this_rule(event, rule):
                    continue  # measured with another rule's threshold/window
                if await self._execute_container_rule(rule, event, settings, bot,
                                                      control_channel_id, global_cooldown):
                    executed.append(rule.name)
        return executed

    @staticmethod
    def _measured_by_this_rule(event, rule: AutoActionRule) -> bool:
        """Restart loops and resource thresholds are measured per setting: an event
        belongs only to the rules whose threshold and window produced it."""
        trigger = rule.trigger
        # high_memory has TWO of its own settings, not one: percent for the
        # containers with a --memory limit, MB for the containers without one.
        # Both watchers report for the same rule, so both count as its own. The
        # two ranges cannot overlap (MIN_RESOURCE_MB > MAX_RESOURCE_PERCENT), so
        # no rule can claim the other yardstick's number by accident.
        own = {
            'restart_loop': [(trigger.restart_threshold, trigger.restart_window_minutes)],
            'high_cpu': [(trigger.cpu_threshold_percent, trigger.resource_minutes)],
            'high_memory': [(trigger.memory_threshold_percent, trigger.resource_minutes),
                            (trigger.memory_threshold_mb, trigger.resource_minutes)],
        }.get(event.kind)
        return own is None or (event.threshold, event.window_minutes) in own

    async def _execute_container_rule(self, rule: AutoActionRule, event, settings: Dict,
                                      bot, control_channel_id, global_cooldown: int = 30) -> bool:
        """One container-state rule for one event.

        Its own path, not _execute_rule: there is no triggering message to link,
        the target is the container the event is about, and only_if_running does
        not apply - a stopped container is "not running" by definition, and
        restarting it is what such a rule exists for.
        """
        container = event.container
        action_type = rule.action.type.upper()
        channel_id = rule.action.notification_channel_id or control_channel_id
        # Where a notice goes: the rule's channel, and the control channel when
        # that one cannot be reached (see _notify).
        channels = tuple(dict.fromkeys(c for c in (rule.action.notification_channel_id,
                                                   control_channel_id) if c))
        protected = await protected_names(settings)

        # Before the locks, so a refused action spends no cooldown.
        if not rule_may_act_on(rule, container):
            logger.info(f"AAS: Skipped watchdog rule '{rule.name}' for '{container}' - "
                        f"no group it is reached through may {action_type}")
            self.state_service.record_trigger(rule.id, rule.name, container, action_type, "SKIPPED",
                                              "Group may not")
            return False

        can_execute, reason, _blocked = self.state_service.acquire_execution_locks(
            rule.id, [container], global_cooldown, rule.cooldown_minutes, rule.cooldown_scope)
        if not can_execute:
            logger.info(f"AAS: Skipped watchdog rule '{rule.name}' for '{container}' - {reason}")
            self.state_service.record_trigger(rule.id, rule.name, container, action_type, "SKIPPED", reason)
            return False

        # After the cooldowns, not before: this used to be the one message in the
        # engine with no rate limit, so a protected container flapping healthy ->
        # unhealthy -> healthy posted once per poll.
        if action_type != 'NOTIFY' and container.lower() in protected:
            logger.warning(f"AAS: Blocked {action_type} on protected container '{container}' (watchdog)")
            self.state_service.record_trigger(rule.id, rule.name, container, action_type, "SKIPPED",
                                              "Protected container")
            if bot and channels and not rule.action.silent:
                await self._notify(bot, channels,
                                          f"🚨 {event.reason} — *{rule.name}* (protected: no `{action_type}`)")
            return False

        if not channel_id:
            logger.warning(f"AAS: watchdog rule '{rule.name}' has no channel to report to "
                           f"(no notification channel and no control channel): {event.reason}")
        if action_type != 'NOTIFY' and rule.action.delay_seconds > 0:
            # A DELAYED ACTION RUNS BESIDE THE STATUS LOOP, NOT INSIDE IT. It was
            # awaited here until 2026-09-26, and this is called from the status
            # loop: for up to an hour (the delay's maximum) no status update, no
            # watchdog, and the notes of DDC's own stops ran out meanwhile. And
            # nothing looked again after the wait, so a container that had
            # recovered in the meantime was restarted anyway.
            task = asyncio.create_task(self._act_on_container(
                rule, event, action_type, container, bot, channels, delayed=True))
            delayed = self.__dict__.setdefault('_delayed_actions', set())
            delayed.add(task)
            task.add_done_callback(delayed.discard)
            return True
        return await self._act_on_container(rule, event, action_type, container, bot, channels)

    async def _act_on_container(self, rule: AutoActionRule, event, action_type: str, container: str,
                                bot, channels, delayed: bool = False) -> bool:
        """The action of one container-state rule, its notice and its record.

        The lock was taken by the caller; every way out of here settles it.
        """
        try:
            if action_type == 'NOTIFY':
                # silent, like every other branch: the rule's own setting decides.
                # A notice that reached nobody is a FAILED notify: it used to be
                # recorded SUCCESS and spend the cooldown (audit 2026-09-26).
                result = True
                if bot and channels and not rule.action.silent:
                    result = await self._notify(bot, channels, f"🚨 {event.reason} — *{rule.name}*")
            else:
                if bot and channels and not rule.action.silent:
                    await self._notify(bot, channels,
                                              f"🚨 {event.reason} → `{action_type}` — *{rule.name}*")
                if delayed:
                    await asyncio.sleep(rule.action.delay_seconds)
                    if not await self._condition_still_holds(event, container):
                        logger.info(f"AAS: '{container}' recovered during the {rule.action.delay_seconds}s "
                                    f"delay of '{rule.name}' - {action_type} not carried out")
                        self.state_service.release_execution_lock(rule.id, container, success=False)
                        self.state_service.record_trigger(rule.id, rule.name, container, action_type,
                                                          "SKIPPED", f"{event.kind}: recovered during the delay")
                        if bot and channels and not rule.action.silent:
                            await self._notify(bot, channels,
                                                      f"✅ **{container}** recovered - no `{action_type}` "
                                                      f"— *{rule.name}*")
                        return False
                verb = 'restart' if action_type in ('RESTART', 'RECREATE') else action_type.lower()
                result = await docker_action(container, verb)
                if result:
                    await self._trigger_status_refresh(bot, container)
                elif bot and channels and not rule.action.silent:
                    await self._notify(bot, channels,
                                              f"⚠️ `{action_type}` **{container}** failed — *{rule.name}*")
        except BaseException:
            # The lock was taken above; an error or a cancellation must not leave
            # the container locked for the whole cooldown.
            self.state_service.release_execution_lock(rule.id, container, success=False)
            raise

        self.state_service.record_trigger(rule.id, rule.name, container, action_type,
                                          "SUCCESS" if result else "FAILED", event.kind)
        if result:
            self.config_service.increment_trigger_count(rule.id)
        else:
            self.state_service.release_rule_cooldown(rule.id)
        return bool(result)

    async def _condition_still_holds(self, event, container: str) -> bool:
        """After a delay: is the container still in the state that fired the rule?

        Only stopped and unhealthy can be read back in one look; for the others,
        and whenever Docker cannot be asked, the answer is yes - acting as the
        rule says is what happened before this check existed.
        """
        if event.kind not in ('stopped', 'unhealthy'):
            return True
        try:
            info = await get_docker_info(container)
        except Exception as e:  # noqa: BLE001 - a failed look must not cancel the action
            logger.warning(f"AAS: Could not look at '{container}' after the delay: {e}")
            return True
        if not info:
            return True
        state = info.get('State', {}) or {}
        if event.kind == 'stopped':
            return not state.get('Running', False)
        return bool(state.get('Running')) and (state.get('Health') or {}).get('Status') == 'unhealthy'

    @staticmethod
    def _only_if_running_notice(rule_name: str, containers: List[str]) -> str:
        """Discord notice for rule targets skipped because they are not running."""
        names = ", ".join(f"`{c}`" for c in containers)
        try:
            return _("⏭️ Auto-Action '{rule}' skipped: {containers} not running (option 'only if running').").format(
                rule=rule_name, containers=names)
        except (KeyError, IndexError, ValueError):
            # Broken placeholder in a translation - fall back to the English source text
            return "⏭️ Auto-Action '{rule}' skipped: {containers} not running (option 'only if running').".format(
                rule=rule_name, containers=names)

    async def _honours_only_if_running(self, rule, action_type: str, container: str) -> bool:
        """Whether "only if running" says to SKIP this container.

        Three answers come back from _get_running_state, and only a confirmed
        ``False`` skips. That is the behaviour this code has always had, and it
        is deliberate: failing closed would mean a transient Docker hiccup
        silently stops automations from working at all.

        The unknown case is the one worth a word, and it had none (review E25).
        ``only_if_running`` exists so that a container the operator stopped ON
        PURPOSE is not touched - it guards RESTART, RECREATE and STOP. When the
        state cannot be determined, the action runs anyway, so that container
        can come back up. Whether that is the right trade-off is the operator's
        call and is written up in docs/quality/reviews/AUTOMATION_SERVICE.md.
        Whether it happens in silence is not: if a container they stopped comes
        back, there has to be a line that explains it.
        """
        state = await self._get_running_state(container)
        if state is False:
            return True
        if state is None:
            logger.warning(
                "AAS: '%s' asked for 'only if running' and the state of '%s' "
                "could not be determined - running %s anyway. If that container "
                "was stopped on purpose, this is why it came back.",
                getattr(rule, "name", "?"), container, action_type)
        return False

    async def _get_running_state(self, container: str) -> Optional[bool]:
        """Return True/False for the container's running state, or None if it can't be determined."""
        try:
            info = await get_docker_info(container)
        except Exception as e:
            logger.warning(f"AAS: Could not determine running state of '{container}': {e}")
            return None
        if not info:
            return None
        return bool(info.get('State', {}).get('Running', False))

    async def _send_feedback(self, bot, channel_id, message) -> bool:
        """Send one message to one channel. True when it was sent.

        A channel the bot cannot see used to be skipped without a word - the
        rule looked as if it had reported (audit 2026-09-26).
        """
        try:
            channel = bot.get_channel(int(channel_id))
            if channel:
                await channel.send(message)
                return True
            logger.warning(f"AAS: channel {channel_id} is unknown to the bot or not visible to it - "
                           f"a notice could not be delivered there")
        except Exception as e:
            logger.warning(f"Failed to send AAS feedback: {e}")
        return False

    async def _notify(self, bot, channels, message) -> bool:
        """Send to the first of ``channels`` that takes it. True when one did."""
        for channel_id in channels:
            if await self._send_feedback(bot, channel_id, message):
                return True
        return False

    async def _trigger_status_refresh(self, bot, container_name: str):
        """Trigger status refresh after AAS action via DockerControlCog."""
        try:
            # Get DockerControlCog from bot
            docker_cog = bot.get_cog('DockerControlCog')
            if docker_cog and hasattr(docker_cog, 'trigger_status_refresh'):
                await docker_cog.trigger_status_refresh(container_name, delay_seconds=5)
                logger.info(f"AAS: Triggered status refresh for {container_name}")
            else:
                logger.warning(f"AAS: DockerControlCog not available for status refresh")
        except Exception as e:
            logger.warning(f"AAS: Failed to trigger status refresh: {e}")

# Singleton
_automation_service = None

def get_automation_service() -> AutomationService:
    global _automation_service
    if _automation_service is None:
        _automation_service = AutomationService()
    return _automation_service
