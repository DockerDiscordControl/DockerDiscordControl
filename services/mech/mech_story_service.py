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

    def __init__(self, story_dir: str = None):
        if story_dir:
            self.story_dir = Path(story_dir)
        else:
            # Robust absolute path relative to project root
            self.story_dir = Path(__file__).parents[2] / "config" / "mech" / "stories"
            
        self.language_files = {
            'en': 'en.txt',
            'de': 'de.txt',
            'fr': 'fr.txt'
        }
        self._story_cache = {}
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.info(f"MechStoryService initialized with story dir: {self.story_dir}")

    def get_story_chapter(self, level: int, language: str = 'en') -> Optional[str]:
        """
        Get the story chapter for a specific mech level.

        Args:
            level: Mech level (1-11)
            language: Language code ('en', 'de', 'fr')

        Returns:
            Story text or None if not found
        """
        chapter_key = self._get_chapter_key_for_level(level)
        if not chapter_key:
            return None

        story_content = self._get_story_content(language)
        return story_content.get(chapter_key)

    def clear_cache(self):
        """Clear the story cache to force reload from disk."""
        self._story_cache = {}
        self.logger.info("Mech story cache cleared - content will be reloaded on next access")

    def get_chapter_key(self, level: int) -> Optional[str]:
        """Get the story chapter key for a specific mech level (public method)."""
        return self._get_chapter_key_for_level(level)

    def _get_story_content(self, language: str) -> Dict[str, str]:
        """Load and parse story content for a language (cached)."""
        if language in self._story_cache:
            return self._story_cache[language]

        story_file = self.story_dir / self.language_files.get(language, 'en.txt')
        content = {}

        try:
            if story_file.exists():
                with open(story_file, 'r', encoding='utf-8') as f:
                    raw_text = f.read()
                    content = self._parse_story_file(raw_text)
                self.logger.debug(f"Loaded mech story for language: {language}")
            else:
                self.logger.warning(f"Story file not found: {story_file}")
        except Exception as e:
            self.logger.warning(f"Failed to load mech story for {language}: {e}")

        self._story_cache[language] = content
        return content

    def _parse_story_file(self, content: str) -> Dict[str, str]:
        """Parse story file content into chapters."""
        chapters = {}
        # Split by double newlines to separate sections roughly
        sections = content.split('\n\n')
        current_chapter = None
        current_content = []

        # Language-independent header patterns (should work for EN/DE/FR files)
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
            'epilogue': ['Epilogue:', 'Epilog:', 'Épilogue:', '3p!l0gu3:']
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

        return chapters

    def _get_chapter_key_for_level(self, level: int) -> str:
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


# Singleton instance
_mech_story_service = None


def get_mech_story_service() -> MechStoryService:
    """Get the singleton MechStoryService instance."""
    global _mech_story_service
    if _mech_story_service is None:
        _mech_story_service = MechStoryService()
    return _mech_story_service
