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

import json
from pathlib import Path
from typing import Any, Optional

DEFAULTS_DIR = Path(__file__).resolve().parent / "defaults"


def resolve_mech_file(relative: str) -> Path:
    """``<config dir>/mech/<relative>`` if it exists, else the shipped default."""
    from utils.config_paths import get_config_dir
    own_copy = get_config_dir() / "mech" / relative
    if own_copy.exists():
        return own_copy
    return DEFAULTS_DIR / relative


def shipped_mech_json(relative: str) -> Optional[Any]:
    """The shipped default's content, or None when it cannot be read.

    For a caller whose own copy failed to parse: the shipped table is a far
    better fallback than a flat constant (stage 4 review before v3.1.0, 24).
    """
    try:
        return json.loads((DEFAULTS_DIR / relative).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
