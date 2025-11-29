# Changelog

All notable changes to DockerDiscordControl will be documented in this file.

---

## v2.1.2 - 2025-11-28

### Unraid/NAS Permission Fix + Mobile UI

#### 🔧 Permission Handling (Hardened)

**PUID/PGID Support:**
- NEW: PUID/PGID environment variables for custom user/group mapping
- NEW: Automatic permission fixing at container startup
- FIXED: Container failed to start on Unraid due to volume permission issues
- IMPROVED: Clear error messages with NAS-specific guidance

**Supported NAS Systems:**
| System | PUID | PGID |
|--------|------|------|
| Unraid | 99 | 100 |
| Synology | 1026 | 100 |
| TrueNAS | 568 | 568 |
| QNAP | 1000 | 1000 |

**Entrypoint Hardening:**
- Input validation for PUID/PGID (numeric, 1-65534)
- Handles UID/GID conflicts with existing system users
- Reuses existing groups if GID matches
- Graceful fallbacks for edge cases
- NFS `root_squash` handling

#### 🎮 New Discord Command

- **`/addadmin`** - Add admin users directly from Discord
  - Opens modal to enter Discord User ID
  - In Control channels: Any user can add admins
  - In Status channels: Only existing admins can add new admins
  - Full German and French translations

#### 📱 Mobile UI Improvements

- Web UI now fully responsive on mobile devices
- Mech display stacks vertically on small screens
- Channel tables scroll horizontally on mobile
- Log buttons wrap properly on narrow screens
- Donation buttons stack with spacing on mobile

---

## v2.1.1 - 2025-11-27

### Hot-Reload & Bug Fixes

#### 🔥 Hot-Reload Configuration

Most settings now take effect immediately without container restart:

**Hot-Reload Supported:**
- Container selection, order, display names, actions
- Channel permissions and admin users list
- Web UI password, language, and timezone
- Spam protection settings

**Requires Restart:**
- Bot Token changes
- Guild ID changes

#### 🔒 Security & Permissions

- IMPROVED: Strict channel separation
  - `/ss` only works in status channels
  - `/control` only works in control channels
- FIXED: Missing permission check for `/control` command

#### 🐛 Bug Fixes

- FIXED: Channel config files saved with name instead of Discord ID
- FIXED: UpdateNotifier wrong method name (`mark_notification_shown`)
- FIXED: ConfigService missing `_get_default_channels_config` attribute
- IMPROVED: Recreation logic with better bot message detection
- IMPROVED: Safety checks for `bot.user` and `application_id`

---

## v2.1.0 - 2025-11-26

### Auto-Action System & Status Watchdog

#### 🤖 Auto-Action System (AAS)

Intelligent container automation that monitors Discord channels and triggers actions:

**Features:**
- 🎮 Game Server Auto-Updates - Restart when update bots announce new versions
- 🔗 Universal Webhook Control - Trigger from CI/CD, monitoring, GitHub Actions
- 📝 Flexible Triggers - Keywords (with fuzzy search) or regex patterns
- 🛡️ Built-in Safety - Cooldowns, protected containers, atomic locking
- 🔒 Zero Attack Surface - Outbound only, no exposed APIs

**Technical Implementation:**
- State file migration with automatic key correction
- Atomic check-and-set for cooldowns (`acquire_execution_lock`)
- 500ms regex timeout protection (ReDoS prevention)
- Comprehensive input validation (Snowflake IDs, regex patterns, ranges)
- Form data preservation in Web UI

#### 🔔 Status Watchdog

Dead Man's Switch monitoring:
- Get alerts when DDC goes offline
- Simple setup with Healthchecks.io or Uptime Kuma
- Only outbound HTTPS pings - no tokens shared
- Compatible with 20+ monitoring services

#### 🏗️ Architecture Improvements

- Single-process architecture (removed supervisord & gunicorn)
- 65% RAM reduction - from ~200MB to 60-70MB typical usage
- Unified logging system with consistent formatting
- Service-first architecture with single point of truth
- Cleaner codebase with reduced complexity

---

## v2.0.0 - 2025-11-18

### Major Release - Complete Rewrite

Production-ready release with multi-language support, performance improvements, and security enhancements.

#### 🎮 EVERYTHING via Discord

- Live Logs Viewer - Monitor container output in real-time
- Task System - Create, view, delete tasks (Once, Daily, Weekly, Monthly, Yearly)
- Container Info System - Custom info and password-protected info
- Public IP Display - Automatic WAN IP detection with custom port support
- Full container management (start, stop, restart, bulk operations)

#### 🌍 Multi-Language Support

- Full Discord UI translation in German, French, and English
- Complete language coverage for all buttons, messages, and interactions
- Dynamic language switching via Web UI settings
- 100% translation coverage across entire bot interface

#### 🤖 Mech Evolution System

- 11-stage Mech Evolution with animated WebP graphics
- Continuous power decay system for fair donation tracking
- Premium key system for power users
- Visual feedback with stage-specific animations

#### ⚡ Performance Improvements

- 16x faster Docker status cache (500ms → 31ms)
- 7x faster container processing through async optimization
- Smart queue system with fair request processing
- Ultra-compact image (less than 200MB RAM usage)

#### 🔒 Security & Infrastructure

- Alpine Linux 3.22.2 base (94% fewer vulnerabilities)
- Production-ready security hardening
- Enhanced token encryption and validation
- Flask 3.1.1 and Werkzeug 3.1.3 (all CVEs resolved)

#### 🔐 Security Fixes

Eight CodeQL security alerts resolved:
- DOM-based XSS vulnerabilities in Web UI (High)
- Information exposure through exceptions (Medium)
- Incomplete URL substring sanitization (Medium)

---

## Version History

Previous versions (v1.x) were development releases. Version 2.0.0 is the first production-ready release.

For detailed development history, see the repository commit history.
