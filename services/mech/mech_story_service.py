#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Mech Story Service                             #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""
Mech Story Service - Handles multi-language mech evolution story content
"""

import os
import logging
from pathlib import Path
from typing import Dict, Optional, Any
from functools import lru_cache

logger = logging.getLogger(__name__)


class MechStoryService:
    """Service for managing mech evolution story content across multiple languages."""

    def __init__(self):
        self.story_dir = Path(__file__).parent
        self.language_files = {
            'en': 'mech_story.txt',
            'de': 'mech_story_de.txt',
            'fr': 'mech_story_fr.txt'
        }
        self._story_cache = {}

    def get_chapter_for_level(self, level: int, language: str = None) -> Optional[str]:
        """
        Get the story chapter for a specific mech level.

        Args:
            level: Mech level (1-11)
            language: Language code (en/de/fr), auto-detected if None

        Returns:
            Story chapter content or None if not found
        """
        if language is None:
            language = self._get_current_language()

        chapters = self.get_all_chapters(language)
        chapter_key = self._level_to_chapter_key(level)

        return chapters.get(chapter_key)

    def get_all_chapters(self, language: str = None) -> Dict[str, str]:
        """
        Get all story chapters for a language.

        Args:
            language: Language code (en/de/fr), auto-detected if None

        Returns:
            Dictionary of chapter_key -> chapter_content
        """
        if language is None:
            language = self._get_current_language()

        # Check cache first
        if language in self._story_cache:
            return self._story_cache[language]

        # Load and parse story content
        story_content = self._load_story_content(language)
        chapters = self._parse_story_chapters(story_content, language)

        # Cache the result
        self._story_cache[language] = chapters

        return chapters

    def reload_stories(self) -> None:
        """Clear cache and force reload of all story content."""
        self._story_cache.clear()
        logger.info("Mech story cache cleared - content will be reloaded on next access")

    def get_chapter_key_for_level(self, level: int) -> str:
        """Get the story chapter key for a specific mech level (public method)."""
        return self._level_to_chapter_key(level)

    def _load_story_content(self, language: str) -> str:
        """Load story content from file with fallback to English."""
        # Try to load the requested language
        story_file = self.story_dir / self.language_files.get(language, 'mech_story.txt')

        try:
            with open(story_file, 'r', encoding='utf-8') as f:
                content = f.read()
                logger.debug(f"Loaded mech story for language: {language}")
                return content
        except (FileNotFoundError, PermissionError, UnicodeDecodeError) as e:
            logger.warning(f"Failed to load mech story for {language}: {e}")

            # Fallback to English if not already trying English
            if language != 'en':
                try:
                    fallback_file = self.story_dir / self.language_files['en']
                    with open(fallback_file, 'r', encoding='utf-8') as f:
                        content = f.read()
                        logger.info(f"Using English fallback for language: {language}")
                        return content
                except Exception as fallback_error:
                    logger.error(f"Failed to load English fallback: {fallback_error}")

            # Ultimate fallback
            return "Error: Story content could not be loaded."

    def _parse_story_chapters(self, content: str, language: str) -> Dict[str, str]:
        """Parse story content into chapters, supporting EN/DE/FR headers."""
        chapters = {}
        sections = content.split('\n\n')
        current_chapter = None
        current_content = []

        # Language-specific header patterns
        header_patterns = {
            'prologue1': ['Prologue I:', 'Prolog I:'],
            'prologue2': ['Prologue II:', 'Prolog II:'],
            'chapter1': ['Chapter I:', 'Kapitel I:', 'Chapitre I'],
            'chapter2': ['Chapter II:', 'Kapitel II:', 'Chapitre II'],
            'chapter3': ['Chapter III:', 'Kapitel III:', 'Chapitre III'],
            'chapter4': ['Chapter IV:', 'Kapitel IV:', 'Chapitre IV'],
            'chapter5': ['Chapter V:', 'Kapitel V:', 'Chapitre V'],
            'chapter6': ['Chapter VI:', 'Kapitel VI:', 'Chapitre VI'],
            'chapter7': ['Chapter VII:', 'Kapitel VII:', 'Chapitre VII'],
            'chapter8': ['Chapter VIII:', 'Kapitel VIII:', 'Chapitre VIII'],
            'chapter9': ['Chapter IX:', 'Kapitel IX:', 'Chapitre IX'],
            'epilogue': ['Epilogue:', 'Epilog:', 'Épilogue:', '3p!l0gu3:']  # Include corrupted variant
        }

        for section in sections:
            section = section.strip()
            if not section:
                continue

            # Check if this section starts a new chapter
            new_chapter_key = None
            for chapter_key, patterns in header_patterns.items():
                if any(section.startswith(pattern) for pattern in patterns):
                    new_chapter_key = chapter_key
                    break

            if new_chapter_key:
                # Save previous chapter
                if current_chapter and current_content:
                    chapters[current_chapter] = '\n'.join(current_content)

                # Start new chapter
                current_chapter = new_chapter_key
                current_content = [section]
            else:
                # Continue current chapter
                if current_content:
                    current_content.append(section)

        # Save final chapter
        if current_chapter and current_content:
            chapters[current_chapter] = '\n'.join(current_content)

        logger.debug(f"Parsed {len(chapters)} chapters for language: {language}")
        return chapters

    def _level_to_chapter_key(self, level: int) -> str:
        """Map mech level to story chapter key."""
        level_mapping = {
            1: "prologue1",     # The Rustborn Husk
            2: "prologue2",     # The Battle-Scarred Survivor
            3: "chapter1",      # The Corewalker Standard
            4: "chapter2",      # The Titanframe
            5: "chapter3",      # The Pulseforged Guardian
            6: "chapter4",      # The Abyss Engine
            7: "chapter5",      # The Rift Strider
            8: "chapter6",      # The Radiant Bastion
            9: "chapter7",      # The Overlord Ascendant
            10: "chapter8",     # The Celestial Exarch
            11: "chapter9"      # OMEGA MECH (The Prayer)
        }

        return level_mapping.get(level, "prologue1")

    def _get_current_language(self) -> str:
        """Get current language from translation manager."""
        try:
            from cogs.translation_manager import translation_manager
            return translation_manager.get_current_language()
        except Exception as e:
            logger.warning(f"Could not get current language: {e}")
            return 'en'  # Default to English


# Singleton instance
_mech_story_service = None


def get_mech_story_service() -> MechStoryService:
    """Get the singleton MechStoryService instance."""
    global _mech_story_service
    if _mech_story_service is None:
        _mech_story_service = MechStoryService()
    return _mech_story_service