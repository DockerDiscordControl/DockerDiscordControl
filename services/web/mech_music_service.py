#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Mech Music Service                             #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""
Mech Music Service - Provides YouTube URLs for custom-composed mech music tracks.
Each mech level has its own epic soundtrack with monetized YouTube streaming.
"""

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
    url: Optional[str] = None  # YouTube URL for monetized streaming
    title: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    status_code: int = 200


class MechMusicService:
    """Service for providing YouTube URLs to custom mech music tracks."""

    def __init__(self):
        self.logger = logger

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
        Get information about all available mech music tracks from YouTube.

        Args:
            request: MechMusicInfoRequest

        Returns:
            MechMusicResult with all YouTube music track information
        """
        try:
            # YouTube track information - all tracks are available via YouTube
            music_info = {}
            for level in range(1, 12):  # Mech levels 1-11
                music_result = self.get_mech_music_url(MechMusicRequest(level=level))
                if music_result.success:
                    music_info[str(level)] = {
                        'title': music_result.title,
                        'url': music_result.url,
                        'available': True,
                        'platform': 'YouTube'
                    }
                else:
                    music_info[str(level)] = {
                        'title': f'Mech {level} Theme',
                        'url': None,
                        'available': False,
                        'platform': 'YouTube'
                    }

            available_count = sum(1 for info in music_info.values() if info['available'])

            return MechMusicResult(
                success=True,
                data={
                    'music_tracks': music_info,
                    'total_tracks': len(music_info),
                    'available_tracks': available_count,
                    'platform': 'YouTube',
                    'monetized': True  # Support creator revenue! 💰
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

    def _validate_level(self, level: int) -> bool:
        """Validate that the mech level is in the valid range."""
        return isinstance(level, int) and 1 <= level <= 11


# Singleton instance
_mech_music_service = None


def get_mech_music_service() -> MechMusicService:
    """Get the singleton MechMusicService instance."""
    global _mech_music_service
    if _mech_music_service is None:
        _mech_music_service = MechMusicService()
    return _mech_music_service