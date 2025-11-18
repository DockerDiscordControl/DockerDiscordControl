# Changelog

All notable changes to DockerDiscordControl will be documented in this file.

## v2.0.0 - 2025-11-18

### Major Release - Complete Rewrite

Production-ready release with multi-language support, performance improvements, and security enhancements.

#### Multi-Language Support
- Full Discord UI translation in German, French, and English
- Complete language coverage for all buttons, messages, and interactions
- Dynamic language switching via Web UI settings
- 100% translation coverage across entire bot interface

#### Mech Evolution System
- 11-stage Mech Evolution with animated WebP graphics
- Continuous power decay system for fair donation tracking
- Premium key system for power users
- Visual feedback with stage-specific animations

#### Performance Improvements
- 16x faster Docker status cache (500ms to 31ms)
- 7x faster container processing through async optimization
- Smart queue system with fair request processing
- Ultra-compact image (less than 200MB RAM usage)

#### Modern UI/UX
- Beautiful Discord embeds with consistent styling
- Advanced spam protection with configurable cooldowns
- Enhanced container information system
- Real-time monitoring and status updates

#### Security & Infrastructure
- Alpine Linux 3.22.1 base (94% fewer vulnerabilities)
- Production-ready security hardening
- Enhanced token encryption and validation
- Flask 3.1.1 and Werkzeug 3.1.3 (all CVEs resolved)

#### Critical Fixes
- Port mapping consistency (9374) for Unraid deployment
- Interaction timeout issues with defer() pattern
- Container control reliability improvements
- Web UI configuration persistence

#### Security Fixes (2025-11-18)
Eight CodeQL security alerts resolved affecting 35+ locations:
- DOM-based XSS vulnerability - alert messages in Web UI (High severity)
- DOM-based XSS vulnerability - container info modal (High severity)
- Information exposure through exceptions - 18 API endpoints (Medium severity)
- Information exposure through exceptions - Mech reset endpoint (Medium severity)
- Information exposure through exceptions - Mech status endpoint (Medium severity)
- Information exposure through exceptions - 12 additional endpoints (Medium severity)
- Incomplete URL substring sanitization - validation check (Medium severity)
- Incomplete URL substring sanitization - replace method (Medium severity)

#### Production Release Changes
- Removed development infrastructure from main branch
- Main branch is now production-only
- Development continues in v2.0 branch
- 132 development files archived

---

## Version History

Previous versions (v1.x) were development releases. Version 2.0.0 is the first production-ready release.

For detailed development history and older versions, see the v2.0 development branch.
