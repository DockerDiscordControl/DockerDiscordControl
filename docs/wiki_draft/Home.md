# Welcome to the DockerDiscordControl Wiki

**DockerDiscordControl (DDC)** is a powerful Discord bot and Web UI that allows you to monitor and control your Docker containers directly from Discord. It gamifies the experience with an evolving "Mech" system that reacts to community support.

## Key Features

*   **Docker Control via Discord**: Start, stop, and restart containers using simple buttons or commands.
*   **Real-time Status**: Get live updates on container status with visual indicators.
*   **Web Dashboard**: A comprehensive web interface for advanced management, logs, and configuration.
*   **Auto-Action System (AAS)**: Intelligent automation that monitors Discord channels and automatically triggers container actions based on keywords, regex, or webhooks.
    *   **Automatic Updates**: Restart servers when update bots announce new versions.
    *   **Keyword & Regex Matching**: Flexible trigger conditions with fuzzy matching support.
    *   **Safety Features**: Cooldowns, protected containers, and atomic locking.
*   **Status Watchdog**: Dead Man's Switch monitoring that alerts you when DDC goes offline.
    *   **Simple Setup**: Just paste a monitoring URL from Healthchecks.io or Uptime Kuma.
    *   **Secure**: No tokens shared - only outbound HTTPS pings.
*   **Mech Evolution System**: A unique gamification layer where a virtual Mech evolves based on donations and community interaction.
    *   **Dynamic Speed**: The Mech's animation speed changes based on its "Power" level.
    *   **Visual Progression**: Watch the Mech grow from a scrappy Level 1 robot to a divine Level 11 entity.
*   **Security First**: Role-based access control, spam protection, and secure authentication.

## Documentation Sections

### [Architecture](Architecture.md)
Understand the technical design, service-oriented architecture, and data flow of DDC.

### [Configuration](Configuration.md)
Comprehensive guide to environment variables, configuration files, and default values.

### [Web UI Settings](WebUI_Settings.md)
Detailed explanation of all settings available in the Web Dashboard, including Spam Protection and Advanced Settings.

### [Auto-Action System](Auto_Action_System.md)
Complete guide to the automation layer: Keyword matching, regex triggers, cooldowns, and use cases for automatic server updates.

### [Status Watchdog](Status_Watchdog.md)
Dead Man's Switch monitoring: Get alerts when DDC goes offline. Setup guides for Healthchecks.io and Uptime Kuma.

### [Mech System](Mech_System.md)
Deep dive into the gamification mechanics: Evolution levels, Power decay, and Animation dynamics.

### [Security](Security.md)
Information about authentication, permissions, and security best practices.

---
*Last updated: November 26, 2025*
