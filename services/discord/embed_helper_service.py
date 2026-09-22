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

from cogs.translation_manager import _, translation_manager
from utils.logging_utils import get_module_logger

logger = get_module_logger('embed_helper_service')


# Discord refuses an embed whose description is longer than this, so a list
# that grows with the installation has to be cut BEFORE it is sent - an
# overview that is refused never appears at all.
DESCRIPTION_LIMIT = 4096


def fit_lines(lines, *, separator: str = "\n", prefix: str = "", suffix: str = "",
              more=None, limit: int = DESCRIPTION_LIMIT) -> str:
    """As many of ``lines`` as fit into ``limit``, and how many were left out.

    ``more(n)`` builds the last line for the n lines not shown (translated by
    the caller); its own length is reserved before the cut is made, so the
    result including prefix and suffix is never longer than the limit. With no
    line left out the text is exactly what a plain join would give.
    """
    lines = list(lines)
    room = limit - len(prefix) - len(suffix)
    whole = separator.join(lines)
    if len(whole) <= room or more is None:
        return prefix + whole[:room] + suffix if len(whole) > room else prefix + whole + suffix
    shown = []
    used = 0
    for index, line in enumerate(lines):
        note = more(len(lines) - index)
        addition = len(line) + (len(separator) if shown else 0)
        # Room for this line AND for the note about everything after it
        if used + addition + len(separator) + len(note) > room:
            break
        shown.append(line)
        used += addition
    note = more(len(lines) - len(shown))
    if shown:
        return prefix + separator.join(shown) + separator + note + suffix
    return prefix + note[:room] + suffix


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
            # translate(text, lang), not _(text). The module-level _ asks
            # translation_manager.get_current_language() - the ambient bot
            # language - so `lang` decided the cache KEY and nothing else. The
            # two sides even disagree about the default: status_handlers reads
            # config.get('language', 'de') while get_current_language() reads
            # config.get('language', 'en') and answers 'en' whenever
            # load_config raises. On an installation with no `language` key the
            # English strings were cached under "translations_de" and stayed
            # there (review D15). translate() has the same fallback chain.
            translate = translation_manager.translate
            self._cached_translations[cache_key] = {
                'online_text': translate("**Online**", lang),
                'offline_text': translate("**Offline**", lang),
                'cpu_text': translate("CPU", lang),
                'ram_text': translate("RAM", lang),
                'uptime_text': translate("Uptime", lang),
                'detail_denied_text': translate("Detailed status not allowed.", lang),
                'last_update_text': translate("Last update", lang),
                'players_text': translate("Players", lang)
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
