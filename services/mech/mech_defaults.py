#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                      #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""Where a mech data file comes from: the operator's copy, else the shipped one.

The mech data (decay.json, evolution.json, speed_translations.json, the story
files) used to exist only under ``config/mech/`` - which the image does not
ship and git ignores (``config/*``). A fresh installation therefore ran on
hard-wired fallbacks: no story chapters at all, and every level - including
the immortal level 11 - decaying at 100 cents a day.

The files now ship read-only in ``services/mech/defaults/``. A file under
``<config dir>/mech/`` still wins, so an operator's own copy keeps working;
nothing is ever copied into, or overwritten in, the config directory.
"""

from pathlib import Path

DEFAULTS_DIR = Path(__file__).resolve().parent / "defaults"


def resolve_mech_file(relative: str) -> Path:
    """``<config dir>/mech/<relative>`` if it exists, else the shipped default."""
    from utils.config_paths import get_config_dir
    own_copy = get_config_dir() / "mech" / relative
    if own_copy.exists():
        return own_copy
    return DEFAULTS_DIR / relative
