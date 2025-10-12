#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Mech Music Service                             #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""
Mech Music Service - Handles streaming of custom-composed mech music tracks.
Each mech level has its own epic soundtrack composed specifically for that evolution.
"""

import os
import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class MechMusicRequest:
    """Represents a mech music request."""
    level: int


@dataclass
class MechMusicInfoRequest:
    """Represents a request for all available mech music info."""
    pass


@dataclass
class MechMusicResult:
    """Represents the result of mech music operations."""
    success: bool
    file_path: Optional[str] = None
    url: Optional[str] = None  # YouTube URL for monetized streaming
    title: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    status_code: int = 200


class MechMusicService:
    """Service for managing and streaming custom mech music tracks."""

    def __init__(self):
        self.logger = logger
        self.music_dir = self._get_music_directory()
        self.music_cache = {}  # Cache for discovered music files

    def get_mech_music(self, request: MechMusicRequest) -> MechMusicResult:
        """
        Get the music file for a specific mech level.

        Args:
            request: MechMusicRequest with mech level

        Returns:
            MechMusicResult with file path and metadata
        """
        try:
            if not self._validate_level(request.level):
                return MechMusicResult(
                    success=False,
                    error=f"Invalid mech level: {request.level}. Must be 1-11.",
                    status_code=400
                )

            # Check if music directory exists
            if not os.path.exists(self.music_dir):
                return MechMusicResult(
                    success=False,
                    error="Mech music directory not found",
                    status_code=404
                )

            # Find music file for this level
            music_file, title = self._find_music_file(request.level)

            if not music_file:
                return MechMusicResult(
                    success=False,
                    error=f"No music found for Mech Level {request.level}",
                    status_code=404
                )

            # Verify file exists and is readable
            if not os.path.isfile(music_file):
                return MechMusicResult(
                    success=False,
                    error=f"Music file not accessible: {music_file}",
                    status_code=404
                )

            self.logger.info(f"Serving mech music for level {request.level}: {title}")

            return MechMusicResult(
                success=True,
                file_path=music_file,
                title=title
            )

        except Exception as e:
            self.logger.error(f"Error getting mech music for level {request.level}: {e}", exc_info=True)
            return MechMusicResult(
                success=False,
                error="Error accessing mech music",
                status_code=500
            )

    def get_mech_music_url(self, request: MechMusicRequest) -> MechMusicResult:
        """
        Get the YouTube URL for a specific mech level's music.

        This method provides YouTube URLs for monetization - supporting
        the creator's revenue while providing excellent user experience.

        Args:
            request: MechMusicRequest with mech level

        Returns:
            MechMusicResult with YouTube URL and metadata
        """
        try:
            if not self._validate_level(request.level):
                return MechMusicResult(
                    success=False,
                    error=f"Invalid mech level: {request.level}. Must be 1-11.",
                    status_code=400
                )

            # Level to YouTube URL mapping - supports creator monetization! 💰
            level_to_youtube = {
                1: {
                    "title": "End of a Mech",
                    "url": "https://youtu.be/rC4CinmbUp8?si=sNnL5c24wFAyUQ0T"
                },
                2: {
                    "title": "Through Rust and Fire",
                    "url": "https://youtu.be/76YnStvCG3I?si=gZAXj3DJojc8BKt8"
                },
                3: {
                    "title": "March of the Corewalker",
                    "url": "https://youtu.be/tyQ6xnOwXAE?si=hqT_JWkM484xxw7A"
                },
                4: {
                    "title": "The Hunger of Titanframes",
                    "url": "https://youtu.be/nNsRBtR7S5c?si=r9M-7WEGX3TbZMz_"
                },
                5: {
                    "title": "The Pulseforged Guardian",
                    "url": "https://youtu.be/GhlwegdJ2zU?si=pTukOUALzHjQR4-W"
                },
                6: {
                    "title": "The Abyss Engine",
                    "url": "https://youtu.be/nxw_eblYgc0?si=B9h18OkJuot8mgO6"
                },
                7: {
                    "title": "The Rift Strider",
                    "url": "https://youtu.be/EdLVwn26ur8?si=66HZOpodwdCgCzxS"
                },
                8: {
                    "title": "Radiance Unbroken",
                    "url": "https://youtu.be/FQx6M6MgHsM?si=hylbOTSENYM4NEfJ"
                },
                9: {
                    "title": "Idols of Steel",
                    "url": "https://youtu.be/6kmmMLLC_oM?si=JwxOApont49INzEZ"
                },
                10: {
                    "title": "Celestial Exarchs",
                    "url": "https://youtu.be/fKkmrxYeSX4?si=QBqD2fV17eaqoF9_"
                },
                11: {
                    "title": "Eternal Omega",
                    "url": "https://youtu.be/X9ssK4rHydU?si=m7LyI1HbDI-eEYHh"
                }
            }

            if request.level not in level_to_youtube:
                return MechMusicResult(
                    success=False,
                    error=f"No YouTube music available for Mech Level {request.level}",
                    status_code=404
                )

            track_info = level_to_youtube[request.level]
            youtube_url = track_info["url"]
            title = track_info["title"]

            # Check if this is a placeholder URL
            if "placeholder" in youtube_url:
                return MechMusicResult(
                    success=False,
                    error=f"YouTube URL not yet configured for {title}",
                    status_code=404
                )

            self.logger.info(f"Generated YouTube music URL for level {request.level}: {title} -> {youtube_url}")

            return MechMusicResult(
                success=True,
                url=youtube_url,
                title=title
            )

        except Exception as e:
            self.logger.error(f"Error generating YouTube music URL for level {request.level}: {e}", exc_info=True)
            return MechMusicResult(
                success=False,
                error="Error generating YouTube music URL",
                status_code=500
            )

    def get_all_music_info(self, request: MechMusicInfoRequest) -> MechMusicResult:
        """
        Get information about all available mech music tracks.

        Args:
            request: MechMusicInfoRequest

        Returns:
            MechMusicResult with all music track information
        """
        try:
            if not os.path.exists(self.music_dir):
                return MechMusicResult(
                    success=False,
                    error="Mech music directory not found",
                    status_code=404
                )

            # Discover all music files
            music_info = {}
            for level in range(1, 12):  # Mech levels 1-11
                music_file, title = self._find_music_file(level)
                if music_file and os.path.isfile(music_file):
                    music_info[level] = {
                        'title': title,
                        'available': True,
                        'file_size': self._get_file_size_mb(music_file)
                    }
                else:
                    music_info[level] = {
                        'title': f'Mech {level} Theme',
                        'available': False,
                        'file_size': 0
                    }

            available_count = sum(1 for info in music_info.values() if info['available'])

            return MechMusicResult(
                success=True,
                data={
                    'music_tracks': music_info,
                    'total_tracks': len(music_info),
                    'available_tracks': available_count,
                    'music_directory': self.music_dir
                }
            )

        except Exception as e:
            self.logger.error(f"Error getting all music info: {e}", exc_info=True)
            return MechMusicResult(
                success=False,
                error="Error accessing music information",
                status_code=500
            )

    # ========================================================================
    # Private Helper Methods
    # ========================================================================

    def _get_music_directory(self) -> str:
        """Get the path to the mech music directory."""
        # Get project root (3 levels up from services/web/)
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        return os.path.join(project_root, 'assets', 'mech_music')

    def _validate_level(self, level: int) -> bool:
        """Validate that the mech level is in the valid range."""
        return isinstance(level, int) and 1 <= level <= 11

    def _find_music_file(self, level: int) -> tuple[Optional[str], Optional[str]]:
        """
        Find the music file for a specific mech level.

        Returns:
            Tuple of (file_path, title) or (None, None) if not found
        """
        # Check cache first
        if level in self.music_cache:
            return self.music_cache[level]

        try:
            # Direct mapping of level to filename (after removing Mech{level} prefix)
            level_to_filename = {
                1: "End of a Mech.mp3",
                2: "Through Rust and Fire.mp3",
                3: "March of the Corewalker.mp3",
                4: "The Hunger of Titanframes.mp3",
                5: "The Pulseforged Guardian.mp3",
                6: "The Abyss Engine.mp3",
                7: "The Rift Strider.mp3",
                8: "Radiance Unbroken.mp3",
                9: "Idols of Steel.mp3",
                10: "Celestial Exarchs.mp3",
                11: "Eternal Omega.mp3"
            }

            if level in level_to_filename:
                filename = level_to_filename[level]
                music_file = os.path.join(self.music_dir, filename)

                # Check if file exists
                if os.path.isfile(music_file):
                    # Extract title from filename (remove .mp3 suffix)
                    title = filename.replace(".mp3", "")

                    # Cache the result
                    self.music_cache[level] = (music_file, title)

                    return music_file, title

            # No file found or level not in mapping
            self.music_cache[level] = (None, None)
            return None, None

        except Exception as e:
            self.logger.error(f"Error finding music file for level {level}: {e}")
            return None, None

    def _get_file_size_mb(self, file_path: str) -> float:
        """Get file size in MB."""
        try:
            size_bytes = os.path.getsize(file_path)
            return round(size_bytes / (1024 * 1024), 2)
        except Exception:
            return 0.0


# Singleton instance
_mech_music_service = None


def get_mech_music_service() -> MechMusicService:
    """Get the singleton MechMusicService instance."""
    global _mech_music_service
    if _mech_music_service is None:
        _mech_music_service = MechMusicService()
    return _mech_music_service