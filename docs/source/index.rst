DockerDiscordControl API Documentation
=====================================

**DockerDiscordControl** (DDC) is a Discord bot for managing Docker containers through Discord commands.
This documentation covers the complete API for all services, utilities, and components.

.. toctree::
   :maxdepth: 2
   :caption: Contents:

   introduction
   quickstart
   services/index
   api/index
   examples
   contributing

Introduction
============

DockerDiscordControl provides a Discord-based interface for Docker container management.
Key features include:

* 🐳 **Docker Integration**: Start, stop, restart containers via Discord
* 📊 **Status Monitoring**: Real-time container status updates
* 🔒 **Secure Access**: Role-based permissions and encrypted tokens
* ⚙️ **Highly Configurable**: Modular configuration system
* 🎨 **Mech Evolution**: Gamification with evolving mech character
* 💰 **Donation System**: Ko-fi integration with power accumulation

Quick Start
===========

Installation
------------

.. code-block:: bash

   # Clone repository
   git clone https://github.com/DockerDiscordControl/DockerDiscordControl.git
   cd DockerDiscordControl

   # Install dependencies
   pip install -r requirements.txt

   # Configure
   cp config/config.example.json config/config.json
   # Edit config.json with your settings

   # Run
   python -m app.bot

Basic Usage
-----------

.. code-block:: python

   from services.config.config_service import get_config_service

   # Get configuration service
   config_service = get_config_service()

   # Load configuration
   config = config_service.get_config()
   print(f"Guild ID: {config['guild_id']}")

   # Encrypt a token
   encrypted = config_service.encrypt_token(
       plaintext_token="my-discord-token",
       password_hash="hashed-password"
   )

Architecture Overview
=====================

DDC follows a **service-oriented architecture** with the following key components:

Configuration Services
----------------------

* :class:`~services.config.config_service.ConfigService` - Central configuration management
* :class:`~services.config.config_loader_service.ConfigLoaderService` - Configuration loading
* :class:`~services.config.config_migration_service.ConfigMigrationService` - Config migration
* :class:`~services.config.config_validation_service.ConfigValidationService` - Validation
* :class:`~services.config.config_cache_service.ConfigCacheService` - Caching

Docker Services
---------------

* ``DockerService`` - Docker daemon interaction
* ``DockerAsyncQueueService`` - Async queue for Docker operations
* ``ContainerService`` - Container-specific operations

Donation Services
-----------------

* ``DonationService`` - Ko-fi donation integration
* ``PowerCalculationService`` - Power accumulation and decay

Mech Services
-------------

* ``MechService`` - Mech evolution and state management
* ``MechAnimationService`` - Animation generation

Web Services
------------

* ``WebUIService`` - Flask-based web interface
* ``AuthenticationService`` - User authentication
* ``ConfigurationSaveService`` - Configuration persistence

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
