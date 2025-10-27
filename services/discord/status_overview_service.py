"""
Discord Status Overview Service

SERVICE FIRST implementation for managing Discord status overview messages (/ss commands).
Handles refresh/recreate logic based on Web UI configuration.

SAFE MIGRATION APPROACH:
- Phase 1: Service as "Decision Layer" only
- Phase 2: Web UI Settings Integration
- Phase 3: Gradual logic consolidation

This service provides:
- Update timing decisions based on Web UI refresh/recreate settings
- Channel-specific configuration management
- Integration with existing docker_control.py logic (NON-BREAKING)
"""

import asyncio
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple, Any, Union
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class StatusOverviewUpdateConfig:
    """Configuration for status overview updates from Web UI."""
    enable_auto_refresh: bool = True
    update_interval_minutes: int = 10
    recreate_messages_on_inactivity: bool = True
    inactivity_timeout_minutes: int = 10

@dataclass
class UpdateDecision:
    """Decision result for status overview updates."""
    should_update: bool
    should_recreate: bool
    reason: str
    next_check_time: Optional[datetime] = None
    skip_reason: Optional[str] = None

class StatusOverviewService:
    """
    SERVICE FIRST: Discord Message Update Decision Layer

    UNIFIED APPROACH: Handles update decisions for both:
    - Status Overview messages (/ss commands)
    - Individual Server messages (control channels)

    This ensures Web UI refresh/recreate settings are consistently applied across
    the entire application, not just overview messages.
    """

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self._config_cache = {}  # Channel ID -> UpdateConfig
        self._cache_timestamp = 0
        self._cache_ttl = 60  # Cache configs for 60 seconds

    def make_update_decision(self, channel_id: int, global_config: Dict[str, Any],
                           last_update_time: Optional[datetime] = None,
                           reason: str = "auto_update",
                           force_refresh: bool = False,
                           force_recreate: bool = False,
                           last_channel_activity: Optional[datetime] = None) -> UpdateDecision:
        """
        DECISION LAYER: Determine if and how status overview should be updated.

        This integrates Web UI refresh/recreate settings with existing logic.

        Args:
            channel_id: Discord channel ID
            global_config: Application configuration
            last_update_time: When this channel was last updated (from calling code)
            reason: Reason for this update check
            force_refresh: Force update regardless of timing (manual commands)
            force_recreate: Force recreation regardless of settings
            last_channel_activity: When this channel was last active (for inactivity-based recreation)

        Returns:
            UpdateDecision: What action to take
        """
        try:
            # Get channel-specific configuration from Web UI
            config = self._get_channel_update_config(channel_id, global_config)

            # FORCE REFRESH: Manual commands always update
            if force_refresh:
                return UpdateDecision(
                    should_update=True,
                    should_recreate=force_recreate,
                    reason=f"force_refresh_{reason}",
                    next_check_time=None
                )

            # CHECK AUTO REFRESH ENABLED
            if not config.enable_auto_refresh:
                return UpdateDecision(
                    should_update=False,
                    should_recreate=False,
                    reason="auto_refresh_disabled_in_web_ui",
                    skip_reason="Auto-refresh disabled in Web UI for this channel"
                )

            # CHECK UPDATE INTERVAL
            should_update_by_time = True
            time_reason = "no_previous_update"

            if last_update_time:
                time_since_update = datetime.now(timezone.utc) - last_update_time
                update_interval = timedelta(minutes=config.update_interval_minutes)

                if time_since_update < update_interval:
                    remaining_seconds = (update_interval - time_since_update).total_seconds()
                    should_update_by_time = False
                    time_reason = f"interval_not_reached_({remaining_seconds:.1f}s_remaining)"
                else:
                    time_reason = f"interval_reached_({config.update_interval_minutes}m)"

            # CHECK RECREATE REQUIREMENTS
            should_recreate = self._should_recreate_message(channel_id, config, force_recreate, last_channel_activity)

            # FINAL DECISION
            should_update = should_update_by_time or should_recreate or force_recreate

            if not should_update:
                return UpdateDecision(
                    should_update=False,
                    should_recreate=False,
                    reason=f"no_update_needed_{time_reason}",
                    skip_reason=f"Update not needed: {time_reason}",
                    next_check_time=self._calculate_next_check_time(last_update_time, config)
                )

            return UpdateDecision(
                should_update=True,
                should_recreate=should_recreate,
                reason=f"update_decided_{time_reason}_recreate_{should_recreate}",
                next_check_time=self._calculate_next_check_time(datetime.now(timezone.utc), config)
            )

        except Exception as e:
            self.logger.error(f"Error in make_update_decision: {e}")
            # SAFE FALLBACK: Always allow updates on error to prevent stale data
            return UpdateDecision(
                should_update=True,
                should_recreate=False,
                reason=f"error_fallback_{e}",
                skip_reason=None
            )

    def _should_recreate_message(self, channel_id: int, config: StatusOverviewUpdateConfig,
                               force_recreate: bool = False, last_channel_activity: Optional[datetime] = None) -> bool:
        """
        Determine if message should be recreated based on Web UI settings, channel inactivity and mech state.

        Args:
            channel_id: Discord channel ID
            config: Channel update configuration
            force_recreate: Force recreation regardless of settings
            last_channel_activity: When this channel was last active (from calling code)

        Returns:
            bool: True if message should be recreated
        """
        try:
            # Force recreate always wins
            if force_recreate:
                return True

            # Check if recreate on inactivity is enabled
            if not config.recreate_messages_on_inactivity:
                return False

            # Check if mech state requires recreation
            from services.mech.mech_state_manager import get_mech_state_manager
            state_manager = get_mech_state_manager()

            if state_manager.should_force_recreate(str(channel_id)):
                self.logger.debug(f"Mech state requires recreation for channel {channel_id}")
                return True

            # Check channel inactivity timeout
            if last_channel_activity:
                time_since_activity = datetime.now(timezone.utc) - last_channel_activity
                inactivity_threshold = timedelta(minutes=config.inactivity_timeout_minutes)

                if time_since_activity >= inactivity_threshold:
                    self.logger.debug(f"Channel {channel_id} inactive for {time_since_activity}, threshold: {inactivity_threshold}")
                    return True

            return False

        except Exception as e:
            self.logger.error(f"Error checking recreate requirements: {e}")
            # Safe fallback: don't recreate on error
            return False

    def _calculate_next_check_time(self, last_update: Optional[datetime],
                                 config: StatusOverviewUpdateConfig) -> Optional[datetime]:
        """Calculate when the next update check should happen."""
        if not last_update:
            return None

        try:
            next_time = last_update + timedelta(minutes=config.update_interval_minutes)
            return next_time
        except Exception as e:
            self.logger.error(f"Error calculating next check time: {e}")
            return None

    def _get_channel_update_config(self, channel_id: int, global_config: Dict[str, Any]) -> StatusOverviewUpdateConfig:
        """
        Get channel-specific update configuration from Web UI settings.

        Uses caching to avoid repeated config parsing.
        """
        try:
            # Check cache
            current_time = time.time()
            if (channel_id in self._config_cache and
                current_time - self._cache_timestamp < self._cache_ttl):
                return self._config_cache[channel_id]

            # Parse channel permissions from config
            channel_permissions = global_config.get('channel_permissions', {})
            default_perms = global_config.get('default_channel_permissions', {})

            channel_config = channel_permissions.get(str(channel_id), default_perms)

            # Create config object
            config = StatusOverviewUpdateConfig(
                enable_auto_refresh=channel_config.get('enable_auto_refresh',
                                                     default_perms.get('enable_auto_refresh', True)),
                update_interval_minutes=channel_config.get('update_interval_minutes',
                                                          default_perms.get('update_interval_minutes', 10)),
                recreate_messages_on_inactivity=channel_config.get('recreate_messages_on_inactivity',
                                                                  default_perms.get('recreate_messages_on_inactivity', True)),
                inactivity_timeout_minutes=channel_config.get('inactivity_timeout_minutes',
                                                             default_perms.get('inactivity_timeout_minutes', 10))
            )

            # Update cache
            self._config_cache[channel_id] = config
            self._cache_timestamp = current_time

            return config

        except Exception as e:
            self.logger.error(f"Error parsing channel config: {e}")
            # Return safe defaults
            return StatusOverviewUpdateConfig()

    def get_channel_config_summary(self, channel_id: int, global_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get a summary of channel configuration for debugging/logging.

        Returns:
            Dict with channel configuration details
        """
        try:
            config = self._get_channel_update_config(channel_id, global_config)
            return {
                'channel_id': channel_id,
                'enable_auto_refresh': config.enable_auto_refresh,
                'update_interval_minutes': config.update_interval_minutes,
                'recreate_messages_on_inactivity': config.recreate_messages_on_inactivity,
                'inactivity_timeout_minutes': config.inactivity_timeout_minutes,
                'config_source': 'cached' if channel_id in self._config_cache else 'fresh'
            }
        except Exception as e:
            return {
                'channel_id': channel_id,
                'error': str(e),
                'fallback_config': True
            }


# Singleton instance
_status_overview_service = None

def get_status_overview_service() -> StatusOverviewService:
    """Get the singleton StatusOverviewService instance."""
    global _status_overview_service
    if _status_overview_service is None:
        _status_overview_service = StatusOverviewService()
    return _status_overview_service


# INTEGRATION HELPER FUNCTIONS
# These help with gradual migration from docker_control.py

def should_update_channel_overview(channel_id: int, global_config: Dict[str, Any],
                                 last_update_time: Optional[datetime] = None,
                                 reason: str = "periodic_check") -> Tuple[bool, str]:
    """
    INTEGRATION HELPER: Quick check if channel overview should be updated.

    This is a simple wrapper for existing code that needs a quick decision.

    Returns:
        Tuple[bool, str]: (should_update, reason)
    """
    try:
        service = get_status_overview_service()
        decision = service.make_update_decision(
            channel_id=channel_id,
            global_config=global_config,
            last_update_time=last_update_time,
            reason=reason,
            force_refresh=False,
            force_recreate=False
        )
        return decision.should_update, decision.reason
    except Exception as e:
        logger.error(f"Error in should_update_channel_overview: {e}")
        # Safe fallback: allow updates
        return True, f"error_fallback_{e}"


def log_channel_update_decision(channel_id: int, global_config: Dict[str, Any],
                               last_update_time: Optional[datetime] = None,
                               reason: str = "debug_check") -> None:
    """
    INTEGRATION HELPER: Log detailed update decision for debugging.

    This helps debug Web UI refresh/recreate configuration issues.
    """
    try:
        service = get_status_overview_service()

        # Get config summary
        config_summary = service.get_channel_config_summary(channel_id, global_config)

        # Get decision
        decision = service.make_update_decision(
            channel_id=channel_id,
            global_config=global_config,
            last_update_time=last_update_time,
            reason=reason
        )

        logger.info(f"STATUS_OVERVIEW_DECISION for channel {channel_id}:")
        logger.info(f"  Config: {config_summary}")
        logger.info(f"  Decision: should_update={decision.should_update}, should_recreate={decision.should_recreate}")
        logger.info(f"  Reason: {decision.reason}")
        if decision.skip_reason:
            logger.info(f"  Skip Reason: {decision.skip_reason}")
        if decision.next_check_time:
            logger.info(f"  Next Check: {decision.next_check_time}")

    except Exception as e:
        logger.error(f"Error logging update decision: {e}")