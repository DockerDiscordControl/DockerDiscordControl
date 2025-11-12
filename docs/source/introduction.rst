Introduction
============

Welcome to the DockerDiscordControl (DDC) API documentation!

What is DDC?
------------

DockerDiscordControl is a Discord bot that provides a powerful interface for managing
Docker containers directly from Discord. It combines container management with gamification
features to create an engaging experience for server administrators.

Key Features
------------

🐳 **Docker Integration**
    Start, stop, restart, and monitor Docker containers via Discord commands.
    Full async queue system for optimal performance.

📊 **Status Monitoring**
    Real-time container status updates with auto-refresh capabilities.
    Custom status channels with configurable update intervals.

🔒 **Secure Access**
    * Role-based permissions per channel
    * Encrypted token storage with PBKDF2
    * Per-container action permissions
    * Web UI authentication

⚙️ **Highly Configurable**
    * Modular configuration system
    * Individual container configuration files
    * Channel-specific permissions
    * Easy migration from legacy configs

🎨 **Mech Evolution System**
    * Gamified mech character that evolves with donations
    * Dynamic power calculation with continuous decay
    * Animated mech states
    * Ko-fi integration for power accumulation

💰 **Donation Integration**
    * Ko-fi API integration
    * Real-time donation tracking
    * Power system with $1 = 1 power
    * Donation history and statistics

Architecture
------------

DDC follows a **service-oriented architecture** with clear separation of concerns:

.. code-block:: text

    DockerDiscordControl
    │
    ├── Services Layer
    │   ├── Configuration Services (6 services)
    │   │   ├── ConfigService (main orchestrator)
    │   │   ├── ConfigLoaderService (loading)
    │   │   ├── ConfigMigrationService (migration)
    │   │   ├── ConfigValidationService (validation)
    │   │   ├── ConfigCacheService (caching)
    │   │   └── ConfigFormParserService (web forms)
    │   │
    │   ├── Docker Services
    │   │   ├── DockerAsyncQueueService (queue management)
    │   │   └── ContainerService (operations)
    │   │
    │   ├── Donation Services
    │   │   ├── DonationService (Ko-fi integration)
    │   │   └── PowerCalculationService (power decay)
    │   │
    │   ├── Mech Services
    │   │   ├── MechService (state management)
    │   │   └── MechAnimationService (WebP generation)
    │   │
    │   └── Web Services
    │       ├── WebUIService (Flask app)
    │       ├── AuthenticationService (login/sessions)
    │       └── ConfigurationSaveService (config persistence)
    │
    ├── Discord Bot Layer
    │   ├── Command Handlers (slash commands)
    │   ├── Event Handlers (on_ready, etc.)
    │   └── Message Management (status updates)
    │
    ├── Web UI Layer
    │   ├── Routes (Flask blueprints)
    │   ├── Templates (Jinja2)
    │   └── Static Assets (CSS, JS)
    │
    └── Infrastructure Layer
        ├── Exception Handling (50+ custom exceptions)
        ├── Logging (timezone-aware, filtered)
        └── Utilities (helpers, validators)

Design Principles
-----------------

Single Responsibility Principle (SRP)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Each service has one clear responsibility:

* **ConfigService**: Configuration orchestration only
* **ConfigLoaderService**: Loading configuration only
* **ConfigCacheService**: Caching only
* **ConfigMigrationService**: Migration only

This keeps services under 500 lines and highly maintainable.

Request/Result Pattern
~~~~~~~~~~~~~~~~~~~~~~

All services use typed request/result objects:

.. code-block:: python

    @dataclass(frozen=True)
    class GetConfigRequest:
        force_reload: bool = False

    @dataclass(frozen=True)
    class GetConfigResult:
        success: bool
        config: Optional[Dict[str, Any]] = None
        error_message: Optional[str] = None

Custom Exception Hierarchy
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Domain-specific exceptions with structured error data:

.. code-block:: python

    class DDCBaseException(Exception):
        def __init__(self, message: str, error_code: str, details: dict):
            self.message = message
            self.error_code = error_code
            self.details = details

See :doc:`ERROR_HANDLING` for complete exception hierarchy.

Singleton Pattern
~~~~~~~~~~~~~~~~~

Services are singletons accessed via factory functions:

.. code-block:: python

    from services.config.config_service import get_config_service

    # Always returns the same instance
    service = get_config_service()

Use Cases
---------

Game Server Management
~~~~~~~~~~~~~~~~~~~~~~

Manage game servers (Minecraft, Valheim, etc.) via Discord:

1. Players request server start via Discord command
2. Bot starts Docker container
3. Bot posts server status with connection info
4. Auto-refresh keeps status updated
5. Bot stops server when inactive

Homelab Administration
~~~~~~~~~~~~~~~~~~~~~~

Control homelab services from Discord:

* Start/stop services (Plex, Nextcloud, etc.)
* Check container status
* View container logs
* Restart failed containers

Development Workflows
~~~~~~~~~~~~~~~~~~~~~

Manage development environments:

* Start/stop databases
* Launch test environments
* Monitor build containers
* Quick access to dev tools

Technical Specifications
------------------------

Languages & Frameworks
~~~~~~~~~~~~~~~~~~~~~~

* **Python 3.9+**: Main language
* **discord.py (PyCord)**: Discord bot framework
* **Flask**: Web UI framework
* **Gevent**: Async/threading compatibility
* **Pillow**: Image processing for animations

Storage
~~~~~~~

* **JSON files**: Configuration storage
* **File-based caching**: Config cache with mtime checking
* **SQLite** (future): Planned for donation history

Security
~~~~~~~~

* **Fernet encryption**: AES-128 CBC for tokens
* **PBKDF2 key derivation**: 260,000 iterations
* **Werkzeug password hashing**: Secure password storage
* **Role-based permissions**: Per-channel access control
* **Docker socket security**: Limited to configured containers

Performance
~~~~~~~~~~~

* **Async Docker queue**: Max 3 concurrent connections
* **Request queue**: Fair processing (FIFO)
* **Config caching**: Reduces disk I/O
* **Token caching**: Encrypted in-memory cache
* **Power decay optimization**: Client-side calculation + server sync

Getting Started
---------------

Ready to start? Check out the :doc:`quickstart` guide!

For complete API reference, see :doc:`services/index`.

For usage examples, see :doc:`examples`.
