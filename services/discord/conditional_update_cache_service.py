#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Conditional Update Cache Service

Manages conditional updates for Discord messages to avoid unnecessary API calls.
Tracks last sent content and skips updates when content hasn't changed.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, Any, Tuple, Optional

from utils.logging_utils import get_module_logger

logger = get_module_logger('conditional_update_cache')


class ConditionalUpdateCacheService:
    """
    Service for managing conditional Discord message updates.

    Responsibilities:
    - Track last sent content per channel:display_name
    - Compare new content with cached content
    - Maintain update statistics (skipped vs sent)
    - Automatic cache cleanup to prevent memory growth
    """

    def __init__(self):
        """Initialize conditional update cache service."""
        self._last_sent_content: Dict[str, Dict[str, Any]] = {}
        self._update_stats = {
            'skipped': 0,
            'sent': 0,
            'last_reset': datetime.now(timezone.utc)
        }
        logger.info("ConditionalUpdateCacheService initialized")

    def has_content_changed(self, cache_key: str, current_content: Dict[str, Any]) -> bool:
        """
        Check if content has changed compared to last sent content.

        Args:
            cache_key: Unique key for this content (typically "channel_id:display_name")
            current_content: Dictionary of current content to compare

        Returns:
            True if content changed or first time, False if unchanged
        """
        last_content = self._last_sent_content.get(cache_key)

        if last_content is None:
            # First time seeing this key - content has "changed"
            return True

        # Compare content
        has_changed = last_content != current_content

        if not has_changed:
            self._update_stats['skipped'] += 1

            # Log performance stats every 50 skipped updates
            if self._update_stats['skipped'] % 50 == 0:
                total_operations = self._update_stats['skipped'] + self._update_stats['sent']
                skip_percentage = (self._update_stats['skipped'] / total_operations * 100) if total_operations > 0 else 0
                logger.info(f"UPDATE_STATS: Skipped {self._update_stats['skipped']} / "
                          f"Sent {self._update_stats['sent']} ({skip_percentage:.1f}% saved)")

        return has_changed

    def update_content(self, cache_key: str, content: Dict[str, Any]) -> None:
        """
        Update cached content after successful send.

        Args:
            cache_key: Unique key for this content
            content: Dictionary of content that was sent
        """
        self._last_sent_content[cache_key] = content
        self._update_stats['sent'] += 1

        # Automatic cleanup every 100 operations
        total_ops = self._update_stats['skipped'] + self._update_stats['sent']
        if total_ops % 100 == 0 and len(self._last_sent_content) > 50:
            self._cleanup_cache()

    def _cleanup_cache(self, keep_entries: int = 25) -> None:
        """
        Clean up cache to prevent memory growth.

        Args:
            keep_entries: Number of most recent entries to keep
        """
        if len(self._last_sent_content) <= keep_entries:
            return

        # Keep only the most recent entries
        sorted_items = list(self._last_sent_content.items())[-keep_entries:]
        self._last_sent_content = dict(sorted_items)
        logger.debug(f"Cleaned conditional update cache: kept {len(self._last_sent_content)} entries")

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get current update statistics.

        Returns:
            Dictionary with skipped, sent, total, and skip percentage
        """
        total = self._update_stats['skipped'] + self._update_stats['sent']
        skip_percentage = (self._update_stats['skipped'] / total * 100) if total > 0 else 0

        return {
            'skipped': self._update_stats['skipped'],
            'sent': self._update_stats['sent'],
            'total': total,
            'skip_percentage': skip_percentage,
            'cache_size': len(self._last_sent_content),
            'last_reset': self._update_stats['last_reset']
        }

    def reset_statistics(self) -> None:
        """Reset update statistics."""
        self._update_stats = {
            'skipped': 0,
            'sent': 0,
            'last_reset': datetime.now(timezone.utc)
        }
        logger.info("Reset update statistics")

    def clear_cache(self) -> None:
        """Clear all cached content."""
        self._last_sent_content.clear()
        logger.info("Cleared conditional update cache")

    def get_cache_size(self) -> int:
        """Get current cache size."""
        return len(self._last_sent_content)

    def get_cached_content(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """
        Get cached content for a specific key.

        Args:
            cache_key: Unique key to look up

        Returns:
            Cached content dictionary or None if not found
        """
        return self._last_sent_content.get(cache_key)


# Singleton instance
_conditional_cache_service_instance: ConditionalUpdateCacheService | None = None


def get_conditional_cache_service() -> ConditionalUpdateCacheService:
    """
    Get the singleton ConditionalUpdateCacheService instance.

    Returns:
        ConditionalUpdateCacheService instance
    """
    global _conditional_cache_service_instance
    if _conditional_cache_service_instance is None:
        _conditional_cache_service_instance = ConditionalUpdateCacheService()
    return _conditional_cache_service_instance
