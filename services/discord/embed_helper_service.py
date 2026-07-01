#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Embed Helper Service

Provides cached translations and box elements for Discord embed generation.
Improves performance by caching frequently used strings and formatting.
"""

from __future__ import annotations

import logging
from typing import Dict

from cogs.translation_manager import _
from utils.logging_utils import get_module_logger

logger = get_module_logger('embed_helper_service')


def format_player_inline(players_online, max_players) -> str:
    """Compact live player count for the space-limited community overview list.

    Returns " {n}/{m}" (single-space separator, no emoji/label, e.g. " 3/8"), or " {n}"
    when max is unknown, or "" when there is no player data. Kept minimal because the
    overview is a monospace box with names already truncated to ~20 chars.
    """
    if players_online is None:
        return ""
    max_part = f"/{max_players}" if max_players is not None else ""
    return f" {players_online}{max_part}"


def format_player_line(players_online, max_players, players_text: str = "Players") -> str:
    """Build the game-server player-count box line for a status embed.

    Returns "│ {players_text}: {n}/{m}\n" (or "│ ...: {n}\n" when max is unknown),
    or "" when there is no player data. Used by BOTH embed renderers (the background
    status loop in cogs/status_handlers.py and the Expand/Collapse toggle path in
    cogs/control_ui.py) so the line is identical and never flickers between them.
    """
    if players_online is None:
        return ""
    max_part = f"/{max_players}" if max_players is not None else ""
    return f"│ {players_text}: {players_online}{max_part}\n"


class EmbedHelperService:
    """
    Service for caching embed-related helper data.

    Responsibilities:
    - Cache translated strings per language
    - Cache box formatting elements per display name
    - Provide fast access to frequently used embed components
    """

    def __init__(self):
        """Initialize embed helper service."""
        self._cached_translations: Dict[str, Dict[str, str]] = {}
        self._cached_box_elements: Dict[str, Dict[str, str]] = {}
        logger.info("EmbedHelperService initialized")

    def get_translations(self, lang: str) -> Dict[str, str]:
        """
        Get cached translations for a specific language.

        Args:
            lang: Language code (e.g., 'en', 'de')

        Returns:
            Dictionary of translated strings
        """
        cache_key = f"translations_{lang}"

        if cache_key not in self._cached_translations:
            self._cached_translations[cache_key] = {
                'online_text': _("**Online**"),
                'offline_text': _("**Offline**"),
                'cpu_text': _("CPU"),
                'ram_text': _("RAM"),
                'uptime_text': _("Uptime"),
                'detail_denied_text': _("Detailed status not allowed."),
                'last_update_text': _("Last update"),
                'players_text': _("Players")
            }
            logger.debug(f"Cached translations for language: {lang}")

        return self._cached_translations[cache_key]

    def get_box_elements(self, display_name: str, box_width: int = 28) -> Dict[str, str]:
        """
        Get cached box formatting elements for Discord embeds.

        Args:
            display_name: Name to display in the box header
            box_width: Width of the box in characters

        Returns:
            Dictionary with 'header_line' and 'footer_line' strings
        """
        cache_key = f"box_{display_name}_{box_width}"

        if cache_key not in self._cached_box_elements:
            header_text = f"── {display_name} "
            max_name_len = box_width - 4
            if len(header_text) > max_name_len:
                header_text = header_text[:max_name_len-1] + "… "
            padding_width = max(1, box_width - 1 - len(header_text))

            self._cached_box_elements[cache_key] = {
                'header_line': f"┌{header_text}{'─' * padding_width}",
                'footer_line': f"└{'─' * (box_width - 1)}"
            }
            logger.debug(f"Cached box elements for: {display_name}")

        return self._cached_box_elements[cache_key]

    def clear_translation_cache(self) -> None:
        """Clear cached translations (for testing/language changes)."""
        self._cached_translations.clear()
        logger.debug("Cleared translation cache")

    def clear_box_cache(self) -> None:
        """Clear cached box elements (for testing)."""
        self._cached_box_elements.clear()
        logger.debug("Cleared box element cache")

    def clear_all_caches(self) -> None:
        """Clear all caches."""
        self.clear_translation_cache()
        self.clear_box_cache()
        logger.info("Cleared all embed helper caches")

    def get_cache_stats(self) -> Dict[str, int]:
        """
        Get cache statistics.

        Returns:
            Dictionary with cache sizes
        """
        return {
            'translations_cached': len(self._cached_translations),
            'box_elements_cached': len(self._cached_box_elements),
            'total_cached_items': len(self._cached_translations) + len(self._cached_box_elements)
        }


# Singleton instance
_embed_helper_service_instance: EmbedHelperService | None = None


def get_embed_helper_service() -> EmbedHelperService:
    """
    Get the singleton EmbedHelperService instance.

    Returns:
        EmbedHelperService instance
    """
    global _embed_helper_service_instance
    if _embed_helper_service_instance is None:
        _embed_helper_service_instance = EmbedHelperService()
    return _embed_helper_service_instance
