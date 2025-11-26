# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Auto Action Config Service                     #
# ============================================================================ #
"""
Service First: Configuration Management for Auto-Actions (AAS)
Handles CRUD operations, validation, and persistence for auto_actions.json.
"""

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
MIN_DELAY_SECONDS = 0
MAX_DELAY_SECONDS = 3600  # 1 hour
VALID_ACTION_TYPES = {'RESTART', 'STOP', 'START', 'RECREATE', 'NOTIFY'}
VALID_MATCH_MODES = {'any', 'all'}


# --- Validation Functions ---

def validate_discord_snowflake(value: str, field_name: str) -> Tuple[bool, str]:
    """Validate a Discord Snowflake ID (17-19 digit number)."""
    if not value:
        return True, ""  # Empty is allowed (optional field)
    if not DISCORD_SNOWFLAKE_PATTERN.match(str(value)):
        return False, f"{field_name} must be a valid Discord ID (17-19 digits), got: {value}"
    return True, ""


def validate_regex_pattern(pattern: str) -> Tuple[bool, str]:
    """Validate a regex pattern for correctness and ReDoS safety."""
    if not pattern:
        return True, ""  # Empty is allowed

    # Check for potentially dangerous patterns (ReDoS)
    dangerous_patterns = [
        r'(\+|\*)\+',           # Nested quantifiers like (a+)+
        r'\(\.\*\)\+',          # (.*)+
        r'\(\.\+\)\+',          # (.+)+
        r'(\w+)+',              # (\w+)+
        r'(a+)+',               # (a+)+
    ]
    for danger in dangerous_patterns:
        if re.search(danger, pattern):
            return False, f"Regex pattern may cause ReDoS (catastrophic backtracking): {pattern}"

    # Try to compile the pattern
    try:
        re.compile(pattern)
    except re.error as e:
        return False, f"Invalid regex pattern: {e}"

    # Limit pattern complexity (simple heuristic)
    if len(pattern) > 500:
        return False, "Regex pattern too long (max 500 characters)"

    return True, ""


def sanitize_string(value: str, max_length: int = 100) -> str:
    """Sanitize a string by removing potentially dangerous characters."""
    if not value:
        return ""
    # Remove HTML tags
    clean = re.sub(r'<[^>]+>', '', str(value))
    # Limit length
    return clean[:max_length].strip()


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

    # Channel IDs
    channel_ids = trigger.get('channel_ids', [])
    if not channel_ids:
        errors.append("At least one channel ID is required")
    else:
        for cid in channel_ids:
            valid, msg = validate_discord_snowflake(cid, "Channel ID")
            if not valid:
                errors.append(msg)

    # Keywords - need at least one of: required_keywords, keywords, or regex
    keywords = trigger.get('keywords', [])
    required_keywords = trigger.get('required_keywords', [])
    if not keywords and not required_keywords and not trigger.get('regex_pattern'):
        errors.append("At least one required keyword, trigger keyword, or regex pattern is required")
    if len(keywords) > MAX_KEYWORDS:
        errors.append(f"Too many keywords (max {MAX_KEYWORDS})")
    for kw in keywords:
        if len(str(kw)) > MAX_KEYWORD_LENGTH:
            errors.append(f"Keyword too long (max {MAX_KEYWORD_LENGTH} chars): {kw[:20]}...")

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
    if action_type != 'NOTIFY' and not containers:
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

    # --- Result ---
    if errors:
        return False, "; ".join(errors), warnings
    return True, "", warnings

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

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TriggerConfig':
        return cls(
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
        return {
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


class AutoActionConfigService:
    """Service for managing auto_actions.json configuration."""

    def __init__(self):
        # Robust path resolution
        try:
            self.base_dir = Path(__file__).parents[2]
        except Exception:
            self.base_dir = Path(".")
            
        self.config_file = self.base_dir / "config" / "auto_actions.json"
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
        """Load raw JSON config from file."""
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Error loading auto_actions.json: {e}")
            return {"global_settings": {}, "auto_actions": []}

    def _save_config_file(self, data: Dict[str, Any]) -> bool:
        """Save JSON config to file atomically."""
        try:
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
            if os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except:
                    pass
            return False

    # --- Public API ---

    def get_rules(self) -> List[AutoActionRule]:
        """Get all configured rules as objects."""
        data = self._load_config_file()
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
        data = self._load_config_file()
        return data.get('global_settings', {
            "enabled": True,
            "global_cooldown_seconds": 30,
            "protected_containers": ["ddc"]
        })

    def add_rule(self, rule_data: Dict[str, Any]) -> ConfigResult:
        """Add a new rule with comprehensive validation."""
        try:
            # Get protected containers for validation warnings
            config = self._load_config_file()
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

        except Exception as e:
            logger.error(f"AAS: Error adding rule: {e}")
            return ConfigResult(success=False, error=str(e))

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

        except Exception as e:
            logger.error(f"AAS: Error updating rule {rule_id}: {e}")
            return ConfigResult(success=False, error=str(e))

    def delete_rule(self, rule_id: str) -> ConfigResult:
        """Delete a rule by ID."""
        config = self._load_config_file()
        original_len = len(config.get('auto_actions', []))
        
        config['auto_actions'] = [r for r in config.get('auto_actions', []) if r.get('id') != rule_id]
        
        if len(config['auto_actions']) == original_len:
            return ConfigResult(success=False, error="Rule not found")
            
        if self._save_config_file(config):
            return ConfigResult(success=True)
        return ConfigResult(success=False, error="Failed to save config file")

    def update_global_settings(self, settings: Dict[str, Any]) -> ConfigResult:
        """Update global settings."""
        config = self._load_config_file()
        # Merge with existing settings to prevent data loss
        current = config.get('global_settings', {})
        current.update(settings)
        config['global_settings'] = current
        
        if self._save_config_file(config):
            return ConfigResult(success=True, data=current)
        return ConfigResult(success=False, error="Failed to save config file")


# Singleton instance
_service_instance = None

def get_auto_action_config_service() -> AutoActionConfigService:
    """Get the global service instance."""
    global _service_instance
    if _service_instance is None:
        _service_instance = AutoActionConfigService()
    return _service_instance