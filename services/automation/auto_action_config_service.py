# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Auto Action Config Service                     #
# ============================================================================ #
"""
Service First: Configuration Management for Auto-Actions (AAS)
Handles CRUD operations, validation, and persistence for auto_actions.json.
"""

import functools
import json
import logging
import uuid
import os
import re
import tempfile
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, asdict, field
from datetime import datetime

logger = logging.getLogger('ddc.auto_action_config_service')


# --- Validation Constants ---
DISCORD_SNOWFLAKE_PATTERN = re.compile(r'^\d{17,19}$')
MAX_RULE_NAME_LENGTH = 100
MAX_KEYWORDS = 50
MAX_KEYWORD_LENGTH = 100
MIN_PRIORITY = 1
MAX_PRIORITY = 100
MIN_COOLDOWN_MINUTES = 1
MAX_COOLDOWN_MINUTES = 10080  # 7 days
# Scope of a rule's cooldown. "container" is the default and the behaviour of every release
# before v2.4.0: the cooldown applies to each affected container separately. "rule" applies it
# to the rule as a whole, so one triggering blocks it for every container.
COOLDOWN_SCOPES = {'container', 'rule'}
MIN_DELAY_SECONDS = 0
MAX_DELAY_SECONDS = 3600  # 1 hour
VALID_ACTION_TYPES = {'RESTART', 'STOP', 'START', 'RECREATE', 'NOTIFY'}

# Trigger types. A rule without "type" is a message rule - every rule written
# before v3.0. "container_state" rules fire on the container watchdog's events
# (services/automation/container_watch.py) instead of on Discord messages.
TRIGGER_MESSAGE = 'message'
TRIGGER_CONTAINER_STATE = 'container_state'
TRIGGER_TYPES = (TRIGGER_MESSAGE, TRIGGER_CONTAINER_STATE)
CONTAINER_STATES = ('stopped', 'unhealthy', 'restart_loop', 'high_cpu', 'high_memory', 'image_update')
MIN_RESTART_THRESHOLD, MAX_RESTART_THRESHOLD = 2, 50
MIN_RESTART_WINDOW_MINUTES, MAX_RESTART_WINDOW_MINUTES = 1, 1440
MIN_RESOURCE_PERCENT, MAX_RESOURCE_PERCENT = 10, 100
# The absolute memory yardstick, for containers without a --memory limit. The
# lowest MB is deliberately above the highest percent: an event carries only its
# number, so keeping the two ranges apart makes "90" unambiguously a percentage.
MIN_RESOURCE_MB, MAX_RESOURCE_MB = 128, 1024 * 1024
MIN_RESOURCE_MINUTES, MAX_RESOURCE_MINUTES = 1, 1440
VALID_MATCH_MODES = {'any', 'all'}


# --- Validation Functions ---

def validate_discord_snowflake(value: str, field_name: str) -> Tuple[bool, str]:
    """Validate a Discord Snowflake ID (17-19 digit number)."""
    if not value:
        return True, ""  # Empty is allowed (optional field)
    if not DISCORD_SNOWFLAKE_PATTERN.match(str(value)):
        return False, f"{field_name} must be a valid Discord ID (17-19 digits), got: {value}"
    return True, ""


# ReDoS heuristic: a group that contains a repeating quantifier and is itself repeated,
# e.g. (a+)+, (\w+)*, (.*)+, ([a-z]+){2,}  (the classic catastrophic-backtracking shape)
_QUANTIFIED_GROUP_RE = re.compile(r'\(((?:[^()\\]|\\.)*)\)(?:[+*]|\{\d+,\d*\})')
_ESCAPE_OR_CHAR_CLASS_RE = re.compile(r'\\.|\[(?:[^\]\\]|\\.)*\]')
_REPEAT_QUANTIFIER_RE = re.compile(r'[+*]|\{\d+,\d*\}')
# A counted repeat directly after a group: "{2,}", "{1,5}", "{3}"
_COUNTED_REPEAT_RE = re.compile(r'^\{\d+(?:,\d*)?\}')
# A repeat followed by a separator inside the group body, e.g. "\d+\.", "[a-z]+-", "\w+\s".
# Every repetition then has to consume that separator, so there is no ambiguity to backtrack.
# Covered separators: escaped literals (\.), whitespace classes (\s, \t, \n) and plain
# punctuation/space characters. Excluded are the "wide" classes \w \d \S \D \W and \b.
_SEPARATOR_AFTER_REPEAT_RE = re.compile(
    r'(?:[+*]|\{\d+(?:,\d*)?\})\s*(?:\\[^dwSDWb]|[^\\\[\]()+*?{}|\w])(?![?*])'
)


def _repeated_group_bodies(pattern: str) -> List[str]:
    """Bodies of groups that are themselves repeated, e.g. the "a+" of "(a+)+".

    Parsed by scanning parentheses so nested groups are seen too: the regex-based scan this
    replaces could not span "((a+))+" and missed it (V2 review B2).
    """
    bodies: List[str] = []
    stack: List[int] = []
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == '\\':
            i += 2
            continue
        if ch == '[':  # character class: skip to its end, brackets inside are literal
            i += 1
            while i < len(pattern) and pattern[i] != ']':
                i += 2 if pattern[i] == '\\' else 1
            i += 1
            continue
        if ch == '(':
            stack.append(i)
        elif ch == ')' and stack:
            start = stack.pop()
            rest = pattern[i + 1:]
            if rest[:1] in ('+', '*') or _COUNTED_REPEAT_RE.match(rest):
                bodies.append(pattern[start + 1:i])
        i += 1
    return bodies


def _has_ambiguous_alternation(body: str) -> bool:
    """True for alternations whose branches can match the same text, e.g. (a|a), (0|0|0), (\\s|\\s).

    Such a group needs no inner quantifier to blow up once the group itself is repeated.
    """
    depth = 0
    branches: List[str] = []
    current = []
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == '\\':
            current.append(body[i:i + 2])
            i += 2
            continue
        if ch == '[':
            start = i
            i += 1
            while i < len(body) and body[i] != ']':
                i += 2 if body[i] == '\\' else 1
            i += 1
            current.append(body[start:i])
            continue
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        if ch == '|' and depth == 0:
            branches.append(''.join(current).strip())
            current = []
        else:
            current.append(ch)
        i += 1
    branches.append(''.join(current).strip())
    if len(branches) < 2:
        return False
    seen = set()
    for branch in branches:
        normalized = branch.lstrip('?:')
        if normalized in seen:
            return True
        seen.add(normalized)
    return False


def _has_nested_quantifier(pattern: str) -> bool:
    """Check a regex pattern (as text) for catastrophic-backtracking shapes.

    Flags a repeated group whose body either repeats itself ("(a+)+", "(\\w+)*") or contains an
    ambiguous alternation ("(a|a)+"). A body that must consume a fixed separator, such as
    "(\\d+\\.)+\\d+" or "([a-z0-9-]+\\.)+[a-z]{2,}", is safe and stays allowed: every repetition
    makes progress, so there is nothing to backtrack into.
    """
    for body in _repeated_group_bodies(pattern):
        stripped = _ESCAPE_OR_CHAR_CLASS_RE.sub('', body)
        if _REPEAT_QUANTIFIER_RE.search(stripped):
            # A literal separator after the repeat (the "(\d+\.)+" shape) keeps it safe
            if _SEPARATOR_AFTER_REPEAT_RE.search(body):
                continue
            return True
        if _has_ambiguous_alternation(body):
            return True
    return False


def validate_regex_pattern(pattern: str) -> Tuple[bool, str]:
    """Validate a regex pattern for correctness and ReDoS safety."""
    if not pattern:
        return True, ""  # Empty is allowed

    # Limit pattern complexity (simple heuristic) - checked first to bound the checks below
    if len(pattern) > 500:
        return False, "Regex pattern too long (max 500 characters)"

    # Check for potentially dangerous patterns (ReDoS). The pattern is inspected as text;
    # applying a danger list as regexes flagged nearly every pattern with a word char.
    if _has_nested_quantifier(pattern):
        return False, f"Regex pattern may cause ReDoS (catastrophic backtracking): {pattern}"

    # Try to compile the pattern
    try:
        re.compile(pattern)
    except re.error as e:
        return False, f"Invalid regex pattern: {e}"

    return True, ""


def sanitize_string(value: str, max_length: int = 100) -> str:
    """Sanitize a string by removing potentially dangerous characters."""
    if not value:
        return ""
    # Limit length FIRST to prevent ReDoS attacks (CodeQL py/polynomial-redos)
    truncated = str(value)[:max_length * 2]
    # Remove HTML tags using simple character replacement (ReDoS-safe)
    # Instead of regex, strip < and > characters entirely
    clean = truncated.replace('<', '').replace('>', '')
    # Final length limit
    return clean[:max_length].strip()


class ConfigUnreadable(RuntimeError):
    """auto_actions.json exists but could not be read - never write over it."""


UNREADABLE_MESSAGE = ("auto_actions.json could not be read; not overwriting it - "
                      "repair or restore the file first")


def validate_rule_data(rule_data: Dict[str, Any], protected_containers: List[str] = None) -> Tuple[bool, str, List[str]]:
    """
    Comprehensive validation of rule data.

    Returns:
        Tuple of (is_valid, error_message, warnings_list)
    """
    errors = []
    warnings = []

    # --- Basic Info Validation ---
    name = rule_data.get('name', '')
    if not name or not name.strip():
        errors.append("Rule name is required")
    elif len(name) > MAX_RULE_NAME_LENGTH:
        errors.append(f"Rule name too long (max {MAX_RULE_NAME_LENGTH} chars)")

    priority = rule_data.get('priority', 10)
    if not isinstance(priority, int) or priority < MIN_PRIORITY or priority > MAX_PRIORITY:
        errors.append(f"Priority must be between {MIN_PRIORITY} and {MAX_PRIORITY}")

    # --- Trigger Validation ---
    trigger = rule_data.get('trigger', {})
    trigger_type = trigger.get('type', TRIGGER_MESSAGE)
    if trigger_type not in TRIGGER_TYPES:
        errors.append(f"Invalid trigger type: {trigger_type}. Must be one of: {TRIGGER_TYPES}")
    elif trigger_type == TRIGGER_CONTAINER_STATE:
        _validate_container_state_trigger(trigger, errors)

    # Channel IDs (message rules only - a container-state rule watches containers)
    channel_ids = trigger.get('channel_ids', [])
    if not channel_ids and trigger_type == TRIGGER_MESSAGE:
        errors.append("At least one channel ID is required")
    else:
        for cid in channel_ids:
            valid, msg = validate_discord_snowflake(cid, "Channel ID")
            if not valid:
                errors.append(msg)

    # Keywords - need at least one of: required_keywords, keywords, or regex
    keywords = trigger.get('keywords', [])
    required_keywords = trigger.get('required_keywords', [])
    if (trigger_type == TRIGGER_MESSAGE and not keywords and not required_keywords
            and not trigger.get('regex_pattern')):
        errors.append("At least one required keyword, trigger keyword, or regex pattern is required")
    if len(keywords) > MAX_KEYWORDS:
        errors.append(f"Too many keywords (max {MAX_KEYWORDS})")
    for kw in keywords:
        if len(str(kw)) > MAX_KEYWORD_LENGTH:
            # str(kw), not kw: the length above is measured on str(kw) as well, so a
            # keyword that is not text gets here - and slicing it raised TypeError out
            # of the validator instead of reporting the keyword (review B33).
            errors.append(f"Keyword too long (max {MAX_KEYWORD_LENGTH} chars): {str(kw)[:20]}...")

    # Regex pattern
    regex_pattern = trigger.get('regex_pattern')
    if regex_pattern:
        valid, msg = validate_regex_pattern(regex_pattern)
        if not valid:
            errors.append(msg)

    # Match mode
    match_mode = trigger.get('match_mode', 'any')
    if match_mode not in VALID_MATCH_MODES:
        errors.append(f"Invalid match_mode: {match_mode}. Must be one of: {VALID_MATCH_MODES}")

    # Source filter - User IDs
    source_filter = trigger.get('source_filter', {})
    for uid in source_filter.get('allowed_user_ids', []):
        valid, msg = validate_discord_snowflake(uid, "User ID")
        if not valid:
            errors.append(msg)

    # --- Action Validation ---
    action = rule_data.get('action', {})

    action_type = action.get('type', 'NOTIFY').upper()
    if action_type not in VALID_ACTION_TYPES:
        errors.append(f"Invalid action type: {action_type}. Must be one of: {VALID_ACTION_TYPES}")

    containers = action.get('containers', [])
    # DDC cannot pull (the proxy refuses POST /images/create on purpose), so a
    # restart on an image update would restart the OLD image.
    if (trigger_type == TRIGGER_CONTAINER_STATE and 'image_update' in trigger.get('states', [])
            and action_type != 'NOTIFY'):
        errors.append("An image-update rule can only notify: DDC cannot pull the new image, "
                      "so a restart would run the old one")
    # A container-state rule acts on the container the event is about.
    if action_type != 'NOTIFY' and not containers and trigger_type == TRIGGER_MESSAGE:
        errors.append("At least one target container is required for this action type")

    # Check for protected containers (warning, not error)
    if protected_containers and containers:
        protected_lower = [p.lower() for p in protected_containers]
        for container in containers:
            if container.lower() in protected_lower:
                warnings.append(f"Container '{container}' is protected - action will be blocked at runtime")

    delay = action.get('delay_seconds', 0)
    if not isinstance(delay, int) or delay < MIN_DELAY_SECONDS or delay > MAX_DELAY_SECONDS:
        errors.append(f"Delay must be between {MIN_DELAY_SECONDS} and {MAX_DELAY_SECONDS} seconds")

    # Notification channel
    notif_channel = action.get('notification_channel_id')
    if notif_channel:
        valid, msg = validate_discord_snowflake(notif_channel, "Notification Channel ID")
        if not valid:
            errors.append(msg)

    # --- Safety Validation ---
    safety = rule_data.get('safety', {})

    cooldown = safety.get('cooldown_minutes', 1440)
    if not isinstance(cooldown, int) or cooldown < MIN_COOLDOWN_MINUTES or cooldown > MAX_COOLDOWN_MINUTES:
        errors.append(f"Cooldown must be between {MIN_COOLDOWN_MINUTES} and {MAX_COOLDOWN_MINUTES} minutes")

    # Missing scope is not an error: rules written by older versions have no such key and keep
    # the previous per-container behaviour.
    scope = safety.get('cooldown_scope', 'container')
    if scope not in COOLDOWN_SCOPES:
        errors.append(f"Cooldown scope must be one of {', '.join(sorted(COOLDOWN_SCOPES))}")

    # --- Result ---
    if errors:
        return False, "; ".join(errors), warnings
    return True, "", warnings

def _validate_container_state_trigger(trigger: Dict[str, Any], errors: List[str]) -> None:
    states = trigger.get('states', [])
    if not states:
        errors.append("At least one container state (stopped, unhealthy, restart_loop) is required")
    for state in states:
        if state not in CONTAINER_STATES:
            errors.append(f"Invalid container state: {state}. Must be one of: {CONTAINER_STATES}")
    threshold = trigger.get('restart_threshold', 3)
    if not isinstance(threshold, int) or not MIN_RESTART_THRESHOLD <= threshold <= MAX_RESTART_THRESHOLD:
        errors.append(f"Restart threshold must be between {MIN_RESTART_THRESHOLD} and {MAX_RESTART_THRESHOLD}")
    window = trigger.get('restart_window_minutes', 10)
    if not isinstance(window, int) or not MIN_RESTART_WINDOW_MINUTES <= window <= MAX_RESTART_WINDOW_MINUTES:
        errors.append(f"Restart window must be between {MIN_RESTART_WINDOW_MINUTES} and "
                      f"{MAX_RESTART_WINDOW_MINUTES} minutes")
    for key, label in (('cpu_threshold_percent', 'CPU threshold'), ('memory_threshold_percent', 'Memory threshold')):
        value = trigger.get(key, 90)
        if not isinstance(value, int) or not MIN_RESOURCE_PERCENT <= value <= MAX_RESOURCE_PERCENT:
            errors.append(f"{label} must be between {MIN_RESOURCE_PERCENT} and {MAX_RESOURCE_PERCENT} percent")
    megabytes = trigger.get('memory_threshold_mb', 4096)
    if not isinstance(megabytes, int) or not MIN_RESOURCE_MB <= megabytes <= MAX_RESOURCE_MB:
        errors.append(f"Memory threshold must be between {MIN_RESOURCE_MB} and {MAX_RESOURCE_MB} MB")
    minutes = trigger.get('resource_minutes', 5)
    if not isinstance(minutes, int) or not MIN_RESOURCE_MINUTES <= minutes <= MAX_RESOURCE_MINUTES:
        errors.append(f"Resource duration must be between {MIN_RESOURCE_MINUTES} and {MAX_RESOURCE_MINUTES} minutes")

# --- Data Models ---

@dataclass
class TriggerConfig:
    """Configuration for message triggers."""
    channel_ids: List[str]
    keywords: List[str]
    required_keywords: List[str] = field(default_factory=list)  # Must ALL match
    ignore_keywords: List[str] = field(default_factory=list)
    match_mode: str = "any"  # "any" | "all" (for regular keywords only)
    regex_pattern: Optional[str] = None
    search_in: List[str] = field(default_factory=lambda: ["content", "embeds"])
    # Source filters
    allowed_user_ids: List[str] = field(default_factory=list)
    allowed_usernames: List[str] = field(default_factory=list)
    is_webhook: Optional[bool] = None
    # Container-state trigger (v3.0 watchdog); unused by message rules.
    type: str = TRIGGER_MESSAGE
    states: List[str] = field(default_factory=list)
    containers: List[str] = field(default_factory=list)   # empty = every container
    restart_threshold: int = 3
    restart_window_minutes: int = 10
    # Resource thresholds (Phase 4b): high_cpu / high_memory above this for resource_minutes
    cpu_threshold_percent: int = 90
    # Memory has two yardsticks, picked per container: percent of the container's
    # --memory limit, or these absolute MB when it was started without one.
    memory_threshold_percent: int = 90
    memory_threshold_mb: int = 4096
    resource_minutes: int = 5

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TriggerConfig':
        return cls(
            type=data.get('type', TRIGGER_MESSAGE),
            states=data.get('states', []),
            containers=data.get('containers', []),
            restart_threshold=data.get('restart_threshold', 3),
            restart_window_minutes=data.get('restart_window_minutes', 10),
            cpu_threshold_percent=data.get('cpu_threshold_percent', 90),
            memory_threshold_percent=data.get('memory_threshold_percent', 90),
            memory_threshold_mb=data.get('memory_threshold_mb', 4096),
            resource_minutes=data.get('resource_minutes', 5),
            channel_ids=data.get('channel_ids', []),
            keywords=data.get('keywords', []),
            required_keywords=data.get('required_keywords', []),
            ignore_keywords=data.get('ignore_keywords', []),
            match_mode=data.get('match_mode', 'any'),
            regex_pattern=data.get('regex_pattern'),
            search_in=data.get('search_in', ["content", "embeds"]),
            allowed_user_ids=data.get('source_filter', {}).get('allowed_user_ids', []),
            allowed_usernames=data.get('source_filter', {}).get('allowed_usernames', []),
            is_webhook=data.get('source_filter', {}).get('is_webhook')
        )

    def to_dict(self) -> Dict[str, Any]:
        data = {
            "channel_ids": self.channel_ids,
            "keywords": self.keywords,
            "required_keywords": self.required_keywords,
            "ignore_keywords": self.ignore_keywords,
            "match_mode": self.match_mode,
            "regex_pattern": self.regex_pattern,
            "search_in": self.search_in,
            "source_filter": {
                "allowed_user_ids": self.allowed_user_ids,
                "allowed_usernames": self.allowed_usernames,
                "is_webhook": self.is_webhook
            }
        }
        # Message rules keep exactly the shape older versions wrote.
        if self.type != TRIGGER_MESSAGE:
            data.update({
                "type": self.type,
                "states": self.states,
                "containers": self.containers,
                "restart_threshold": self.restart_threshold,
                "restart_window_minutes": self.restart_window_minutes,
                "cpu_threshold_percent": self.cpu_threshold_percent,
                "memory_threshold_percent": self.memory_threshold_percent,
                "memory_threshold_mb": self.memory_threshold_mb,
                "resource_minutes": self.resource_minutes,
            })
        return data

@dataclass
class ActionConfig:
    """Configuration for the action to execute."""
    type: str  # RESTART, STOP, START, RECREATE, NOTIFY
    containers: List[str]
    delay_seconds: int = 0
    notification_channel_id: Optional[str] = None
    silent: bool = False

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ActionConfig':
        return cls(
            type=data.get('type', 'NOTIFY'),
            containers=data.get('containers', []),
            delay_seconds=data.get('delay_seconds', 0),
            notification_channel_id=data.get('notification_channel_id'),
            silent=data.get('silent', False)
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "containers": self.containers,
            "delay_seconds": self.delay_seconds,
            "notification_channel_id": self.notification_channel_id,
            "silent": self.silent
        }

@dataclass
class AutoActionRule:
    """Full Auto-Action Rule definition."""
    id: str
    name: str
    enabled: bool
    trigger: TriggerConfig
    action: ActionConfig
    priority: int = 10
    # Safety settings
    cooldown_minutes: int = 1440
    # Scope of the cooldown above: "container" (default, and the behaviour of every release
    # before v2.4.0) applies it per affected container, so a rule covering three containers can
    # act on each of them once per cooldown. "rule" applies it to the whole rule, so one
    # triggering blocks the rule itself for that duration. The default keeps existing
    # installations working exactly as before.
    cooldown_scope: str = "container"
    only_if_running: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AutoActionRule':
        return cls(
            id=data.get('id', str(uuid.uuid4())),
            name=data.get('name', 'New Rule'),
            enabled=data.get('enabled', True),
            priority=data.get('priority', 10),
            trigger=TriggerConfig.from_dict(data.get('trigger', {})),
            action=ActionConfig.from_dict(data.get('action', {})),
            cooldown_minutes=data.get('safety', {}).get('cooldown_minutes', 1440),
            cooldown_scope=data.get('safety', {}).get('cooldown_scope', 'container'),
            only_if_running=data.get('safety', {}).get('only_if_running', True),
            metadata=data.get('metadata', {})
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "enabled": self.enabled,
            "priority": self.priority,
            "trigger": self.trigger.to_dict(),
            "action": self.action.to_dict(),
            "safety": {
                "cooldown_minutes": self.cooldown_minutes,
                "cooldown_scope": self.cooldown_scope,
                "only_if_running": self.only_if_running
            },
            "metadata": self.metadata
        }

@dataclass
class ConfigResult:
    """Standard result wrapper."""
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None


def _under_lock(method):
    """Serialise one read-modify-write on auto_actions.json.

    The write itself is atomic; the CYCLE is not. Without this, a rule firing
    (increment_trigger_count) and the panel creating a rule could both read the
    file and the later write would carry a copy that never saw the other's
    change - the panel answered "created" for a rule that was not on disk and
    never ran.

    Both sides live in ONE process (the bot's loop and a waitress worker
    thread), so this is a thread race. flock serialises it all the same:
    cross_process_lock opens a fresh descriptor each time, so two threads
    conflict just as two processes do - and it also keeps out a `docker exec`
    or an edit made on the host.

    Nothing decorated here calls anything else decorated here; a second flock
    on the same file from the same thread would block for ever.
    """
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        from utils.atomic_io import cross_process_lock

        with cross_process_lock(self.config_file):
            return method(self, *args, **kwargs)

    return wrapper


class AutoActionConfigService:
    """Service for managing auto_actions.json configuration."""

    def __init__(self):
        # Robust path resolution
        try:
            self.base_dir = Path(__file__).parents[2]
        except Exception:
            self.base_dir = Path(".")
            
        # Via utils/config_paths.py (DDC_CONFIG_DIR). Derived from
        # Path(__file__).parents[2] before: the file sat outside a volume given
        # by DDC_CONFIG_DIR, and in test runs it landed in the real config/.
        from utils.config_paths import get_config_dir
        self.config_file = get_config_dir() / "auto_actions.json"
        self._ensure_config_exists()
        logger.info(f"AutoActionConfigService initialized: {self.config_file}")

    def _ensure_config_exists(self):
        """Ensure the config file exists with default structure."""
        if not self.config_file.exists():
            default_config = {
                "global_settings": {
                    "enabled": True,
                    "global_cooldown_seconds": 30,
                    "audit_channel_id": None,
                    "audit_level": "actions_only",
                    "protected_containers": ["ddc", "portainer"],
                    "log_all_checks": False
                },
                "auto_actions": []
            }
            self._save_config_file(default_config)

    def _load_config_file(self) -> Dict[str, Any]:
        """Load raw JSON config from file.

        An unreadable file raises ConfigUnreadable. It used to answer with an EMPTY
        structure, which every writer then saved back over the file: one bad read
        (a partial copy, a hand edit, disk trouble) wiped every rule the operator had
        and reported success (review B, section 10 F1). Readers may fall back to
        "no rules" - that only stops automation - but nothing may WRITE on top of a
        configuration it could not read.
        """
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Error loading auto_actions.json: {e}")
            raise ConfigUnreadable(str(e)) from e

    def _load_for_reading(self) -> Dict[str, Any]:
        """The configuration, or an empty one if it cannot be read (readers only)."""
        try:
            return self._load_config_file()
        except ConfigUnreadable:
            return {"global_settings": {}, "auto_actions": []}

    def _save_config_file(self, data: Dict[str, Any]) -> bool:
        """Save JSON config to file atomically."""
        temp_path = None
        try:
            # temp_path before the try: mkstemp itself can fail - an unwritable
            # config directory, no inodes left - and the cleanup below asks for
            # temp_path. Unbound, it raised UnboundLocalError from inside the
            # handler and replaced the real error with a confusing one (review B29).
            temp_dir = str(self.config_file.parent)
            fd, temp_path = tempfile.mkstemp(dir=temp_dir, text=True, suffix='.json.tmp')
            
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
                
            # Atomic rename
            if os.name == 'posix':
                os.rename(temp_path, self.config_file)
            else:
                if self.config_file.exists():
                    self.config_file.unlink()
                os.rename(temp_path, self.config_file)
            return True
        except Exception as e:
            logger.error(f"Error saving auto_actions.json: {e}", exc_info=True)
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except Exception:
                    pass
            return False

    # --- Public API ---

    def get_rules(self) -> List[AutoActionRule]:
        """Get all configured rules as objects."""
        data = self._load_for_reading()
        rules = []
        for rule_data in data.get('auto_actions', []):
            try:
                rules.append(AutoActionRule.from_dict(rule_data))
            except Exception as e:
                logger.error(f"Skipping invalid rule data: {e}")
        return rules

    def get_rule(self, rule_id: str) -> Optional[AutoActionRule]:
        """Get a specific rule by ID."""
        rules = self.get_rules()
        for rule in rules:
            if rule.id == rule_id:
                return rule
        return None

    def get_global_settings(self) -> Dict[str, Any]:
        """Get global AAS settings."""
        data = self._load_for_reading()
        return data.get('global_settings', {
            "enabled": True,
            "global_cooldown_seconds": 30,
            "protected_containers": ["ddc"]
        })

    @_under_lock
    def add_rule(self, rule_data: Dict[str, Any]) -> ConfigResult:
        """Add a new rule with comprehensive validation."""
        try:
            # Get protected containers for validation warnings
            config = self._load_config_file()   # raises ConfigUnreadable - see below
            protected = config.get('global_settings', {}).get('protected_containers', [])

            # Validate rule data
            is_valid, error_msg, warnings = validate_rule_data(rule_data, protected)
            if not is_valid:
                return ConfigResult(success=False, error=f"Validation failed: {error_msg}")

            # Sanitize rule name
            rule_data['name'] = sanitize_string(rule_data.get('name', ''), MAX_RULE_NAME_LENGTH)

            # Ensure ID is generated if missing
            if 'id' not in rule_data or not rule_data['id']:
                rule_data['id'] = str(uuid.uuid4())

            rule_data['metadata'] = {
                "created_at": datetime.utcnow().isoformat(),
                "trigger_count": 0,
                "validation_warnings": warnings  # Store any warnings
            }

            new_rule = AutoActionRule.from_dict(rule_data)

            config['auto_actions'].append(new_rule.to_dict())

            if self._save_config_file(config):
                logger.info(f"AAS: Rule '{new_rule.name}' created (ID: {new_rule.id})")
                if warnings:
                    logger.warning(f"AAS: Rule '{new_rule.name}' has warnings: {warnings}")
                return ConfigResult(success=True, data=new_rule)
            else:
                return ConfigResult(success=False, error="Failed to save config file")

        except ConfigUnreadable as e:
            return ConfigResult(success=False, error=f"{UNREADABLE_MESSAGE}: {e}")
        except Exception as e:
            logger.error(f"AAS: Error adding rule: {e}")
            return ConfigResult(success=False, error=str(e))

    @_under_lock
    def update_rule(self, rule_id: str, rule_data: Dict[str, Any]) -> ConfigResult:
        """Update an existing rule with comprehensive validation."""
        try:
            config = self._load_config_file()
            protected = config.get('global_settings', {}).get('protected_containers', [])

            # Validate rule data
            is_valid, error_msg, warnings = validate_rule_data(rule_data, protected)
            if not is_valid:
                return ConfigResult(success=False, error=f"Validation failed: {error_msg}")

            # Sanitize rule name
            rule_data['name'] = sanitize_string(rule_data.get('name', ''), MAX_RULE_NAME_LENGTH)

            found = False

            for i, rule in enumerate(config.get('auto_actions', [])):
                if rule.get('id') == rule_id:
                    # Preserve metadata but update warnings
                    metadata = rule.get('metadata', {})
                    metadata['updated_at'] = datetime.utcnow().isoformat()
                    metadata['validation_warnings'] = warnings
                    rule_data['id'] = rule_id  # Ensure ID matches
                    rule_data['metadata'] = metadata

                    updated_rule = AutoActionRule.from_dict(rule_data)
                    config['auto_actions'][i] = updated_rule.to_dict()
                    found = True
                    break

            if not found:
                return ConfigResult(success=False, error=f"Rule {rule_id} not found")

            if self._save_config_file(config):
                logger.info(f"AAS: Rule '{rule_data.get('name', rule_id)}' updated")
                if warnings:
                    logger.warning(f"AAS: Rule '{rule_data.get('name', rule_id)}' has warnings: {warnings}")
                return ConfigResult(success=True, data=rule_id)
            else:
                return ConfigResult(success=False, error="Failed to save config file")

        except ConfigUnreadable as e:
            return ConfigResult(success=False, error=f"{UNREADABLE_MESSAGE}: {e}")
        except Exception as e:
            logger.error(f"AAS: Error updating rule {rule_id}: {e}")
            return ConfigResult(success=False, error=str(e))

    @_under_lock
    def delete_rule(self, rule_id: str) -> ConfigResult:
        """Delete a rule by ID."""
        try:
            config = self._load_config_file()
        except ConfigUnreadable as e:
            return ConfigResult(success=False, error=f"{UNREADABLE_MESSAGE}: {e}")
        original_len = len(config.get('auto_actions', []))
        
        config['auto_actions'] = [r for r in config.get('auto_actions', []) if r.get('id') != rule_id]
        
        if len(config['auto_actions']) == original_len:
            return ConfigResult(success=False, error="Rule not found")
            
        if self._save_config_file(config):
            return ConfigResult(success=True)
        return ConfigResult(success=False, error="Failed to save config file")

    @_under_lock
    def update_global_settings(self, settings: Dict[str, Any]) -> ConfigResult:
        """Update global settings."""
        try:
            config = self._load_config_file()
        except ConfigUnreadable as e:
            return ConfigResult(success=False, error=f"{UNREADABLE_MESSAGE}: {e}")
        # Merge with existing settings to prevent data loss
        current = config.get('global_settings', {})
        current.update(settings)
        config['global_settings'] = current
        
        if self._save_config_file(config):
            return ConfigResult(success=True, data=current)
        return ConfigResult(success=False, error="Failed to save config file")

    @_under_lock
    def increment_trigger_count(self, rule_id: str) -> bool:
        """Increment the trigger count for a rule after successful execution."""
        try:
            config = self._load_config_file()
            rules = config.get('auto_actions', [])   # ConfigUnreadable -> caught below

            for rule in rules:
                if rule.get('id') == rule_id:
                    if 'metadata' not in rule:
                        rule['metadata'] = {'trigger_count': 0}
                    rule['metadata']['trigger_count'] = rule['metadata'].get('trigger_count', 0) + 1
                    rule['metadata']['last_triggered'] = datetime.utcnow().isoformat()

                    if self._save_config_file(config):
                        logger.debug(f"AAS: Incremented trigger count for rule {rule_id}")
                        return True
                    return False

            logger.warning(f"AAS: Rule {rule_id} not found for trigger count increment")
            return False
        except Exception as e:
            logger.error(f"AAS: Error incrementing trigger count: {e}")
            return False


# Singleton instance
_service_instance = None

def get_auto_action_config_service() -> AutoActionConfigService:
    """Get the global service instance."""
    global _service_instance
    if _service_instance is None:
        _service_instance = AutoActionConfigService()
    return _service_instance