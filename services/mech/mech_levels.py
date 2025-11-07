#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Mech Levels Configuration                      #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""
Mech Levels - Level names and metadata
"""

MECH_LEVEL_NAMES = {
    1: "The Rustborn Husk",
    2: "The Battle-Scarred Survivor",
    3: "The Corewalker Standard",
    4: "The Titanframe",
    5: "The Pulseforged Guardian",
    6: "The Abyss Engine",
    7: "The Rift Strider",
    8: "The Radiant Bastion",
    9: "The Overlord Ascendant",
    10: "The Celestial Exarch",
    11: "OMEGA MECH",
}


def get_level_name(level: int) -> str:
    """Get name for a specific level"""
    return MECH_LEVEL_NAMES.get(level, f"Level {level}")
