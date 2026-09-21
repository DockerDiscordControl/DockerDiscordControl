# -*- coding: utf-8 -*-
"""
Services Package - Clean service architecture for DDC

This package contains professional business logic services organized by domain:
- infrastructure: Core infrastructure services (logging, container info, spam protection)
- config: Unified configuration service (replaces old config_loader/manager)
- docker_service: Docker container management utilities
- donation: Donation system and disable key management
- mech: Donation mech animation and state services
- scheduling: Task scheduler and helper services

All services follow clean architecture patterns:
- Immutable dataclasses for type safety
- ServiceResult wrappers for consistent error handling
- Singleton pattern for resource management
- Atomic operations for data integrity
"""

import sys
import os

# Add the parent directory to Python path to ensure proper imports
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# NOTHING IS IMPORTED HERE ON PURPOSE (review E31).
#
# This used to re-export five service factories - container info, action log,
# spam protection, config and mech - which meant that importing ANYTHING under
# `services` first imported all five.
#
# Measured in the running container: `import services` cost 1199 ms and pulled
# in 23 modules. Measured in the source tree: nothing used the re-exports. Not
# one `from services import ...`, not one `services.get_config_service(...)`,
# not one bare `import services`. Every caller imports the module it wants.
#
# So it bought nothing and cost two things: 1.2 seconds of every start, and a
# coupling where an ImportError anywhere in those five made
# `services.config.config_service` unimportable too. A mech problem becoming a
# configuration problem is the same sentence as reviews E8 and E12, one layer
# down. It is also why tests/unit/app_modules/test_utils_and_bot.py has to
# replace this whole package with stubs in order to test anything.
#
# Import the service you need directly:
#
#     from services.config.config_service import get_config_service
#
# The sys.path setup above stays. It is load-bearing and is a different thing.
