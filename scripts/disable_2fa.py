#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Break-glass: switch the web panel's second factor off from the host.

For a lost phone AND lost recovery codes (docs/V3_ARCHITECTURE_PLAN.md §5.3).
Run on the Docker host - whoever can do that owns the host and is outside the
security boundary by design (§5.2):

    docker exec -it -u ddc <container> python3 scripts/disable_2fa.py

The state file is moved aside, not deleted: renaming it back restores 2FA
with the same secret and the remaining recovery codes.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.web.two_factor_service import default_path  # noqa: E402


def main() -> int:
    path = default_path()
    if not path.exists():
        print(f"Two-factor authentication is already off ({path} does not exist).")
        return 0
    aside = path.with_name(f"{path.name}.removed-{time.strftime('%Y%m%d-%H%M%S')}")
    path.rename(aside)
    print(f"Two-factor authentication is now OFF. The old state is kept as {aside}")
    print("Log in with the panel password and set it up again under Security -> 2FA.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
