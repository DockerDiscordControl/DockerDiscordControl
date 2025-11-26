# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Auto Action State Service                      #
# ============================================================================ #
"""
Service First: State Management for Auto-Actions
Handles runtime state, cooldown tracking, and execution history.
Persists to config/auto_actions_state.json to survive restarts (optional but good practice).
"""

import json
import logging
import time
import os
import tempfile
from pathlib import Path
from typing import Dict, Any, List, Optional
from threading import Lock
from dataclasses import dataclass, asdict, field

logger = logging.getLogger('ddc.auto_action_state_service')

@dataclass
class TriggerEvent:
    """Represents a single execution of an auto-action."""
    timestamp: float
    rule_id: str
    rule_name: str
    container: str
    action: str
    result: str  # SUCCESS, FAILED, SKIPPED
    details: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

class AutoActionStateService:
    """Service for managing AAS runtime state."""

    def __init__(self):
        try:
            self.base_dir = Path(__file__).parents[2]
        except Exception:
            self.base_dir = Path(".")
            
        self.state_file = self.base_dir / "config" / "auto_actions_state.json"
        self._lock = Lock()
        
        # Runtime State
        self.global_last_triggered = 0.0
        self.rule_cooldowns: Dict[str, float] = {}  # rule_id -> timestamp
        self.container_cooldowns: Dict[str, float] = {} # container_name -> timestamp
        self.trigger_history: Dict[str, List[Dict[str, Any]]] = {} # container -> list of events
        
        self._load_state()
        logger.info("AutoActionStateService initialized")

    def _load_state(self):
        """Load state from disk with migration support for old key names."""
        if not self.state_file.exists():
            return

        try:
            with open(self.state_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            needs_migration = False

            with self._lock:
                # Migration: Handle old key name 'global_cooldown_last_triggered' -> 'global_last_triggered'
                if 'global_cooldown_last_triggered' in data and 'global_last_triggered' not in data:
                    self.global_last_triggered = data.get('global_cooldown_last_triggered', 0.0)
                    needs_migration = True
                    logger.info("AAS State: Migrated 'global_cooldown_last_triggered' -> 'global_last_triggered'")
                else:
                    self.global_last_triggered = data.get('global_last_triggered', 0.0)

                self.rule_cooldowns = data.get('rule_cooldowns', {})
                self.container_cooldowns = data.get('container_cooldowns', {})
                self.trigger_history = data.get('trigger_history', {})

            # Save migrated state to update file format
            if needs_migration:
                logger.info("AAS State: Saving migrated state to disk")
                self._save_state()

        except Exception as e:
            logger.error(f"Error loading AAS state: {e}")

    def _save_state(self):
        """Persist state to disk (async safe via lock)."""
        # Note: We don't need to save on every single event to avoid IO spam.
        # But for V1 reliability, we'll save on significant changes.
        try:
            data = {
                'global_last_triggered': self.global_last_triggered,
                'rule_cooldowns': self.rule_cooldowns,
                'container_cooldowns': self.container_cooldowns,
                'trigger_history': self.trigger_history
            }
            
            temp_dir = str(self.state_file.parent)
            fd, temp_path = tempfile.mkstemp(dir=temp_dir, text=True, suffix='.json.tmp')
            
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
                
            if os.name == 'posix':
                os.rename(temp_path, self.state_file)
            else:
                if self.state_file.exists():
                    self.state_file.unlink()
                os.rename(temp_path, self.state_file)
                
        except Exception as e:
            logger.error(f"Error saving AAS state: {e}")
            if os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except:
                    pass

    # --- Public API ---

    def check_cooldown(self, rule_id: str, container: str,
                      global_cooldown: int, rule_cooldown_mins: int) -> tuple[bool, str]:
        """
        Check if action is blocked by any cooldown.
        Returns: (is_blocked, reason)

        Note: This is a read-only check. Use acquire_execution_lock() for atomic check+set.
        """
        now = time.time()

        with self._lock:
            # 1. Global Cooldown
            if (now - self.global_last_triggered) < global_cooldown:
                remaining = int(global_cooldown - (now - self.global_last_triggered))
                return True, f"Global cooldown active ({remaining}s remaining)"

            # 2. Container Cooldown (using rule specific time)
            # We map container cooldowns to rules essentially, but user asked for "Per Container" cooldowns.
            # If rule says 24h cooldown, it applies to the container affected by this rule.
            last_run = self.container_cooldowns.get(container, 0)
            cooldown_sec = rule_cooldown_mins * 60

            if (now - last_run) < cooldown_sec:
                remaining_min = int((cooldown_sec - (now - last_run)) / 60)
                return True, f"Container '{container}' cooldown active ({remaining_min}m remaining)"

        return False, ""

    def acquire_execution_lock(self, rule_id: str, container: str,
                               global_cooldown: int, rule_cooldown_mins: int) -> tuple[bool, str]:
        """
        Atomic check-and-set for cooldowns. Prevents race conditions.

        This method checks cooldowns AND sets them in a single atomic operation,
        preventing two concurrent messages from both passing the cooldown check.

        Returns: (can_execute, reason)
            - (True, "") if execution is allowed (cooldowns have been set)
            - (False, reason) if blocked by cooldown
        """
        now = time.time()

        with self._lock:
            # 1. Global Cooldown Check
            if (now - self.global_last_triggered) < global_cooldown:
                remaining = int(global_cooldown - (now - self.global_last_triggered))
                return False, f"Global cooldown active ({remaining}s remaining)"

            # 2. Container Cooldown Check
            last_run = self.container_cooldowns.get(container, 0)
            cooldown_sec = rule_cooldown_mins * 60

            if (now - last_run) < cooldown_sec:
                remaining_min = int((cooldown_sec - (now - last_run)) / 60)
                return False, f"Container '{container}' cooldown active ({remaining_min}m remaining)"

            # 3. ATOMIC: Set cooldowns immediately to prevent race condition
            # This ensures no other concurrent check can pass between our check and the actual execution
            self.global_last_triggered = now
            self.container_cooldowns[container] = now
            self.rule_cooldowns[rule_id] = now

        # Note: We don't save state here - that happens in record_trigger()
        # This is intentional: if execution fails, the state will be corrected in record_trigger()
        return True, ""

    def release_execution_lock(self, rule_id: str, container: str, success: bool):
        """
        Call this after acquire_execution_lock if execution failed.
        This resets the cooldowns that were set during acquire.

        Args:
            success: If True, cooldowns remain set. If False, cooldowns are reset.
        """
        if success:
            return  # Cooldowns stay set

        # Reset cooldowns if execution failed
        with self._lock:
            # We could reset to previous values, but for simplicity we just reset to 0
            # This allows immediate retry after failure
            if rule_id in self.rule_cooldowns:
                del self.rule_cooldowns[rule_id]
            if container in self.container_cooldowns:
                del self.container_cooldowns[container]
            # Don't reset global_last_triggered as other rules may have set it

    def record_trigger(self, rule_id: str, rule_name: str, container: str, action: str, result: str, details: str = ""):
        """
        Record a trigger event and finalize cooldown state.

        If result is SUCCESS, cooldowns remain set (from acquire_execution_lock).
        If result is FAILED/SKIPPED and was not blocked by cooldown, reset cooldowns
        to allow immediate retry.
        """
        now = time.time()

        with self._lock:
            # Update/confirm cooldowns only on success
            if result == "SUCCESS":
                # Confirm cooldowns (may have been set by acquire_execution_lock)
                self.global_last_triggered = now
                self.container_cooldowns[container] = now
                self.rule_cooldowns[rule_id] = now
            elif result == "FAILED":
                # Execution failed - release the lock to allow retry
                # Only reset if this was set by acquire_execution_lock (not if blocked by cooldown)
                if "cooldown" not in details.lower():
                    if container in self.container_cooldowns:
                        # Reset to 0 to allow immediate retry
                        self.container_cooldowns[container] = 0
                        logger.debug(f"AAS: Released container cooldown for '{container}' after failed execution")
                    if rule_id in self.rule_cooldowns:
                        self.rule_cooldowns[rule_id] = 0
                        logger.debug(f"AAS: Released rule cooldown for '{rule_id}' after failed execution")

            elif result == "SKIPPED":
                # Rule was skipped (blocked at acquisition stage by cooldown or protected container)
                # No cooldown state changes needed - cooldowns were never acquired
                # Just log for clarity
                logger.debug(f"AAS: Recorded skipped trigger for rule '{rule_name}' on '{container}': {details}")

            # Add history entry
            event = TriggerEvent(
                timestamp=now,
                rule_id=rule_id,
                rule_name=rule_name,
                container=container,
                action=action,
                result=result,
                details=details
            )
            
            if container not in self.trigger_history:
                self.trigger_history[container] = []
                
            # Add to front
            self.trigger_history[container].insert(0, event.to_dict())
            
            # Prune history (Question 21: max 100 entries per container)
            if len(self.trigger_history[container]) > 100:
                self.trigger_history[container] = self.trigger_history[container][:100]
                
        # Persist state
        self._save_state()

    def get_history(self, container: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Get execution history."""
        with self._lock:
            if container:
                return self.trigger_history.get(container, [])[:limit]
            
            # Flatten all history if no container specified
            all_events = []
            for events in self.trigger_history.values():
                all_events.extend(events)
            
            # Sort by timestamp desc
            all_events.sort(key=lambda x: x['timestamp'], reverse=True)
            return all_events[:limit]

# Singleton
_state_service = None

def get_auto_action_state_service() -> AutoActionStateService:
    global _state_service
    if _state_service is None:
        _state_service = AutoActionStateService()
    return _state_service