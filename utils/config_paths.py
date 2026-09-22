#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                      #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""Where the configuration directory is - one rule instead of several dozen.

``DDC_CONFIG_DIR`` is documented for users (README, docs/CONFIGURATION.md) as
the override for the config directory. Six places honoured it, each with its
own copy of the rule; about thirty others derived ``<project>/config`` on their
own. Setting the variable therefore split the configuration: the web panel
read containers from the new directory while the bot kept reading the old one.
In test runs (tests/conftest.py sets the variable) the same split let services
create and write files under the real config/ - only the empty mount in
scripts/ddc_test.sh prevented the damage. See SPEC.md Z2.

The variable is read on every call, not at import time, so a change made
before a service is constructed takes effect.
"""

import os
from pathlib import Path
from typing import Mapping, Optional

_PROJECT_ROOT = Path(__file__).resolve().parents[1]


def get_config_dir(environ: Optional[Mapping[str, str]] = None) -> Path:
    """``DDC_CONFIG_DIR`` if set and non-empty, else ``<project>/config``.

    Inside the container the project root is ``/app``, so the default is
    ``/app/config`` - exactly what the individual derivations produced.

    ``environ`` defaults to ``os.environ``; app/web/config.build_config passes the
    mapping it was given, so it keeps reading from that and not from the process.
    """
    # One expression, not a helper variable: tests/spec/test_settings_take_effect_everywhere.py
    # finds direct environment reads by the shape of the call, and this is now
    # THE direct read of DDC_CONFIG_DIR.
    override = ((os.environ if environ is None else environ).get("DDC_CONFIG_DIR") or "").strip()
    if override:
        return Path(override)
    return _PROJECT_ROOT / "config"
