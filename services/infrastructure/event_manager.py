#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Event Manager                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""
Event Manager - SERVICE FIRST compliant event system for decoupled service communication.
Enables services to communicate without direct service-to-service calls.
"""

import logging
from typing import Dict, List, Callable, Any
from dataclasses import dataclass
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@dataclass
class EventData:
    """Base event data structure."""
    event_type: str
    timestamp: datetime
    source_service: str
    data: Dict[str, Any]


class EventManager:
    """
    SERVICE FIRST Event Manager - enables decoupled service communication.

    Services can emit events and listen to events without direct imports.
    This maintains Service First principles by avoiding service-to-service calls.
    """

    def __init__(self):
        self.logger = logger.getChild(self.__class__.__name__)
        self._listeners: Dict[str, List[Callable]] = {}
        self._event_history: List[EventData] = []
        self._max_history = 100  # Keep last 100 events for debugging

        self.logger.info("Service First Event Manager initialized")

    def register_listener(self, event_type: str, callback: Callable[[EventData], None]):
        """Register a callback function to listen for specific event types."""
        if event_type not in self._listeners:
            self._listeners[event_type] = []

        self._listeners[event_type].append(callback)
        self.logger.debug(f"Registered listener for event type: {event_type}")

    def emit_event(self, event_type: str, source_service: str, data: Dict[str, Any] = None):
        """Emit an event to all registered listeners."""
        if data is None:
            data = {}

        event_data = EventData(
            event_type=event_type,
            timestamp=datetime.now(timezone.utc),
            source_service=source_service,
            data=data
        )

        # Store in history for debugging
        self._event_history.append(event_data)
        if len(self._event_history) > self._max_history:
            self._event_history.pop(0)

        # Notify all listeners
        if event_type in self._listeners:
            for callback in self._listeners[event_type]:
                try:
                    callback(event_data)
                except (RuntimeError) as e:
                    self.logger.error(f"Error in event listener for {event_type}: {e}", exc_info=True)

        self.logger.debug(f"Event emitted: {event_type} from {source_service}")

    def get_event_stats(self) -> Dict[str, Any]:
        """Get event system statistics for monitoring."""
        return {
            'registered_listeners': {
                event_type: len(listeners)
                for event_type, listeners in self._listeners.items()
            },
            'event_history_count': len(self._event_history),
            'recent_events': [
                {
                    'type': event.event_type,
                    'source': event.source_service,
                    'timestamp': event.timestamp.isoformat()
                }
                for event in self._event_history[-10:]  # Last 10 events
            ]
        }


# Singleton instance
_event_manager = None


def get_event_manager() -> EventManager:
    """Get or create the singleton Event Manager instance."""
    global _event_manager
    if _event_manager is None:
        _event_manager = EventManager()
    return _event_manager