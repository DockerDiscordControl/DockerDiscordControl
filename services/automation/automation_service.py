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
from typing import List, Optional, Dict, Any
from dataclasses import dataclass

from .auto_action_config_service import get_auto_action_config_service, AutoActionRule
from .auto_action_state_service import get_auto_action_state_service

# Import Docker Control (we reuse existing utils to ensure consistency)
from services.docker_service.docker_utils import docker_action, is_container_exists

logger = logging.getLogger('ddc.automation_service')

@dataclass
class TriggerContext:
    """Context object for the trigger event."""
    message_id: str
    channel_id: str
    user_id: str
    username: str
    is_webhook: bool
    content: str
    embeds_text: str  # Consolidated text from embeds
    
    @property
    def full_text(self) -> str:
        """Combined content and embeds for searching."""
        return f"{self.content}\n{self.embeds_text}".lower()

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
                if await self._execute_rule(rule, context, settings, bot_instance):
                    executed_rules.append(rule.name)
                    
        return executed_rules

    def _pre_filter_rules(self, rules: List[AutoActionRule], ctx: TriggerContext) -> List[AutoActionRule]:
        """Fast filter rules based on metadata (Channel, User)."""
        candidates = []
        for rule in rules:
            if not rule.enabled:
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
                # Run regex in thread with 500ms timeout to prevent ReDoS hanging
                matched = await asyncio.wait_for(
                    asyncio.to_thread(
                        self._safe_regex_search,
                        rule.trigger.regex_pattern,
                        search_text
                    ),
                    timeout=0.5  # 500ms timeout for regex execution
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
        """
        Blocking regex search, designed to run in a separate thread.
        """
        # Basic protection: Cap input size
        if len(text) > 10000:
            text = text[:10000]
            
        try:
            return bool(re.search(pattern, text, re.IGNORECASE | re.MULTILINE))
        except Exception:
            return False

    async def _execute_rule(self, rule: AutoActionRule, ctx: TriggerContext, 
                           global_settings: Dict, bot) -> bool:
        """Execute the action defined in the rule."""
        
        # 1. Check Protected Containers (Question 18)
        protected = global_settings.get('protected_containers', [])
        target_containers = rule.action.containers
        
        for container in target_containers:
            if container.lower() in [p.lower() for p in protected]:
                logger.warning(f"AAS: Blocked action on protected container '{container}'")
                self.state_service.record_trigger(
                    rule.id, rule.name, container, rule.action.type, "SKIPPED", "Protected container"
                )
                return False

        # 2. Check Cooldowns with atomic lock (Question 17/14)
        # Use acquire_execution_lock for atomic check-and-set to prevent race conditions
        for container in target_containers:
            can_execute, reason = self.state_service.acquire_execution_lock(
                rule.id,
                container,
                global_settings.get('global_cooldown_seconds', 30),
                rule.cooldown_minutes
            )
            if not can_execute:
                logger.info(f"AAS: Skipped rule '{rule.name}' - {reason}")
                self.state_service.record_trigger(
                    rule.id, rule.name, container, rule.action.type, "SKIPPED", reason
                )
                return False

        # 3. Execute Action (Action 11, 9)
        # We execute actions sequentially for now
        action_type = rule.action.type.upper()
        success_count = 0
        
        for container in target_containers:
            logger.info(f"AAS: Executing {action_type} on {container}...")
            
            # Check if container exists
            if not await is_container_exists(container):
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

            # Send Feedback Message (Question 12)
            notification_channel_id = rule.action.notification_channel_id or ctx.channel_id
            if not rule.action.silent and bot:
                # Professional compact format
                delay_info = f" ({rule.action.delay_seconds}s delay)" if rule.action.delay_seconds > 0 else ""
                await self._send_feedback(
                    bot,
                    notification_channel_id,
                    f"⚡ `{action_type}` **{container}**{delay_info} — *{rule.name}*"
                )

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

        return success_count > 0

    async def _send_feedback(self, bot, channel_id, message):
        """Helper to send feedback to Discord."""
        try:
            channel = bot.get_channel(int(channel_id))
            if channel:
                await channel.send(message)
        except Exception as e:
            logger.warning(f"Failed to send AAS feedback: {e}")

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
