# DDC Dependency Management

Complete guide to dependency management, service hierarchy, and import guidelines for DockerDiscordControl.

## Table of Contents

- [Overview](#overview)
- [Service Hierarchy](#service-hierarchy)
- [Dependency Rules](#dependency-rules)
- [Checking for Circular Imports](#checking-for-circular-imports)
- [Generating Dependency Graphs](#generating-dependency-graphs)
- [Import Guidelines](#import-guidelines)
- [CI/CD Dependency Checks](#cicd-dependency-checks)

## Overview

DDC follows a **layered service-oriented architecture** with clear dependency rules:

```
┌─────────────────────────────────────┐
│          App Layer (Bot/Web)        │
│  - Discord Bot (app.bot)            │
│  - Web UI (app.web_ui)              │
└─────────────────────────────────────┘
               ↓
┌─────────────────────────────────────┐
│       Business Logic Services       │
│  - ConfigService                    │
│  - DockerService                    │
│  - MechService                      │
│  - DonationService                  │
└─────────────────────────────────────┘
               ↓
┌─────────────────────────────────────┐
│         Utility Layer               │
│  - Logging (utils.logging_utils)    │
│  - Performance (utils.performance)   │
│  - Exceptions (services.exceptions) │
└─────────────────────────────────────┘
```

## Service Hierarchy

### Foundation Services (No Dependencies)

**ConfigService** (`services.config`):
- Purpose: Configuration management
- Dependencies: None
- Used by: All other services

**Exceptions** (`services.exceptions`):
- Purpose: Custom exception hierarchy
- Dependencies: None
- Used by: All services

### Core Services (Depend on Foundation)

**DockerService** (`services.docker_service`):
- Purpose: Docker container management
- Dependencies: ConfigService
- Used by: App layer, MechService

**DonationService** (`services.donation`):
- Purpose: Ko-fi integration and power management
- Dependencies: ConfigService
- Used by: MechService, App layer

### High-Level Services

**MechService** (`services.mech`):
- Purpose: Mech evolution and state management
- Dependencies: ConfigService, DonationService
- Used by: App layer

### App Layer

**Bot** (`app.bot`):
- Purpose: Discord bot interface
- Dependencies: All services
- Used by: None (top layer)

**Web UI** (`app.web_ui`):
- Purpose: Web configuration interface
- Dependencies: All services
- Used by: None (top layer)

## Dependency Rules

### ✅ Allowed Patterns

1. **App layer → Services**: App can import any service
   ```python
   from services.config.config_service import get_config_service
   from services.docker_service.docker_utils import get_container_status_async
   ```

2. **Service → Lower Service**: Services can import services in lower layers
   ```python
   # MechService can import DonationService
   from services.donation.donation_service import get_donation_service
   ```

3. **Service → Utils**: Any service can import utils
   ```python
   from utils.logging_utils import get_logger
   from utils.performance_metrics import get_performance_metrics
   ```

4. **Service → Exceptions**: Any layer can import exceptions
   ```python
   from services.exceptions import ConfigServiceError, DockerServiceError
   ```

### ❌ Prohibited Patterns

1. **Circular Imports**: No circular dependencies allowed
   ```python
   # WRONG: ServiceA imports ServiceB, ServiceB imports ServiceA
   # services/a.py
   from services.b import ServiceB  # WRONG if ServiceB imports ServiceA
   ```

2. **Service → App**: Services cannot import app layer
   ```python
   # WRONG: Service importing from app
   from app.bot import bot_instance  # WRONG
   ```

3. **Utils → Services**: Utils should not depend on services
   ```python
   # WRONG: Util importing service
   from services.config.config_service import get_config_service  # WRONG
   ```

4. **Backward Dependencies**: Lower layers cannot import higher layers
   ```python
   # WRONG: ConfigService importing MechService
   from services.mech.mech_service import get_mech_service  # WRONG
   ```

## Checking for Circular Imports

### Tool: check_circular_imports.py

**Location**: `tools/check_circular_imports.py`

**Usage**:

```bash
# Basic check
python3 tools/check_circular_imports.py

# Verbose output
python3 tools/check_circular_imports.py --verbose

# Fail build if circular imports found
python3 tools/check_circular_imports.py --fail-on-circular

# Check specific paths
python3 tools/check_circular_imports.py --paths services app
```

**Output Example**:

```
🔍 Analyzing Python imports for circular dependencies...
Paths: services, app, utils

Found 125 modules
Total dependencies: 342

✅ No circular dependencies found!

Top 10 most imported modules:
  services.config.config_service: 45 imports
  services.exceptions: 38 imports
  utils.logging_utils: 32 imports
  services.docker_service.docker_utils: 28 imports
```

**If Circular Dependencies Found**:

```
❌ Found 2 circular dependencies:

1. services.mech.mech_service → services.donation.donation_service → services.mech.mech_service
2. app.bot.commands → app.bot.events → app.bot.commands
```

### Fixing Circular Imports

**Strategy 1: Extract Common Dependency**
```python
# Before (circular):
# services/a.py imports services/b.py
# services/b.py imports services/a.py

# After: Extract shared code to services/common.py
# services/a.py imports services/common.py
# services/b.py imports services/common.py
```

**Strategy 2: Lazy Imports**
```python
# Import inside function instead of at module level
def my_function():
    from services.other_service import get_other_service
    service = get_other_service()
```

**Strategy 3: Dependency Injection**
```python
# Pass dependencies as parameters instead of importing
class ServiceA:
    def __init__(self, service_b):
        self.service_b = service_b
```

## Generating Dependency Graphs

### Tool: generate_dependency_graph.py

**Location**: `tools/generate_dependency_graph.py`

**Requirements**:
```bash
# Install Python package
pip install graphviz

# Install Graphviz binary
# Linux: sudo apt-get install graphviz
# Mac: brew install graphviz
```

**Usage**:

```bash
# Generate service-level graph
python3 tools/generate_dependency_graph.py \
  --output docs/dependency_graph_service \
  --format png \
  --level service

# Generate package-level graph
python3 tools/generate_dependency_graph.py \
  --level package \
  --format svg

# Generate hierarchical view
python3 tools/generate_dependency_graph.py \
  --hierarchical \
  --format pdf

# Generate textual service hierarchy
python3 tools/generate_dependency_graph.py --generate-text
```

**Options**:
- `--output`: Output file path (default: docs/dependency_graph)
- `--format`: Output format (png, svg, pdf)
- `--level`: Aggregation level (module, service, package)
- `--hierarchical`: Create hierarchical graph with subgraphs
- `--generate-text`: Generate SERVICE_HIERARCHY.md

## Import Guidelines

### Good Import Practices

**1. Use Singleton Getters**:
```python
# ✅ Good: Use singleton getter
from services.config.config_service import get_config_service
config_service = get_config_service()

# ❌ Bad: Direct instantiation
from services.config.config_service import ConfigService
config_service = ConfigService()  # May create multiple instances
```

**2. Import Only What You Need**:
```python
# ✅ Good: Specific import
from services.config.config_service import get_config_service

# ❌ Bad: Wildcard import
from services.config.config_service import *
```

**3. Group Imports by Type**:
```python
# Standard library
import os
import sys
from pathlib import Path

# Third-party
import discord
from flask import Flask

# Local imports
from services.config.config_service import get_config_service
from utils.logging_utils import get_logger
```

**4. Use Relative Imports Within Packages**:
```python
# Inside services/config/config_service.py
from .config_cache_service import ConfigCacheService
from .config_loader_service import ConfigLoaderService
```

### Bad Import Practices

**1. Circular Imports**:
```python
# ❌ Bad: Creates circular dependency
# services/a.py
from services.b import ServiceB

# services/b.py
from services.a import ServiceA
```

**2. Importing from Higher Layers**:
```python
# ❌ Bad: Service importing from app
# services/mech/mech_service.py
from app.bot import bot_instance
```

**3. Import Side Effects**:
```python
# ❌ Bad: Import has side effects
# utils/config.py
CONFIG = load_config()  # Runs at import time

# ✅ Good: Lazy initialization
def get_config():
    global _CONFIG
    if _CONFIG is None:
        _CONFIG = load_config()
    return _CONFIG
```

## CI/CD Dependency Checks

**Workflow**: `.github/workflows/dependency-checks.yml`

### Jobs

#### 1. Check Circular Imports

**Runs**: `tools/check_circular_imports.py --fail-on-circular`

**Fails if**: Circular dependencies detected

#### 2. Generate Dependency Graphs

**Creates**:
- Service-level dependency graph
- Package-level dependency graph
- Hierarchical view

**Uploads**: Graphs as artifacts (90-day retention)

#### 3. Analyze Dependencies

**Shows**: Most imported modules (top 10)

#### 4. Dependency Summary

**Status**: Aggregates all job results

### Triggers

- Push to `main`, `v2.0`, `develop`
- Pull requests to `main`, `v2.0`
- Manual workflow dispatch

### PR Comments

Workflow automatically comments on PRs with:
- Circular import check results
- Link to dependency graphs
- Analysis summary

## Service Communication Patterns

### Pattern 1: Direct Method Calls

**When**: Synchronous operations

```python
from services.config.config_service import get_config_service

config_service = get_config_service()
config = config_service.get_config()
```

### Pattern 2: Async Patterns

**When**: Concurrent operations

```python
from services.docker_service.docker_utils import get_container_status_async

async def check_status():
    status = await get_container_status_async('nginx')
```

### Pattern 3: Event-Based

**When**: Loose coupling needed

```python
from services.infrastructure.event_manager import get_event_manager

event_manager = get_event_manager()
event_manager.emit('config_changed', config)
```

## Troubleshooting

### "ImportError: cannot import name"

**Cause**: Circular import

**Solution**:
```bash
# Check for circular imports
python3 tools/check_circular_imports.py --verbose

# Fix circular dependencies using strategies above
```

### "Module has no attribute"

**Cause**: Import order issue

**Solution**:
```python
# Move import to function level
def my_function():
    from services.other import get_other
    return get_other()
```

### "Dependency graph generation fails"

**Cause**: Graphviz not installed

**Solution**:
```bash
# Linux
sudo apt-get install graphviz

# Mac
brew install graphviz

# Then install Python package
pip install graphviz
```

## Best Practices Summary

1. ✅ **Follow layered architecture**: App → Services → Utils
2. ✅ **Use singleton getters**: `get_*_service()`
3. ✅ **No circular imports**: Check regularly
4. ✅ **Import only what you need**: Specific imports
5. ✅ **Group imports**: Standard, third-party, local
6. ✅ **Use relative imports**: Within packages
7. ❌ **No backward dependencies**: Lower layers don't import higher
8. ❌ **No app imports in services**: Services are reusable
9. ❌ **No utils → services**: Keep utils independent

## See Also

- [SERVICES.md](SERVICES.md) - Service architecture
- [CODE_QUALITY.md](CODE_QUALITY.md) - Code quality standards
- [CONTRIBUTING.md](CONTRIBUTING.md) - Contribution guidelines
