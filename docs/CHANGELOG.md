# Changelog

All notable changes to DockerDiscordControl will be documented in this file.

---

## v2.2.2 - 2026-04-26

### Hardening, Performance & Test-Suite Sanitization

#### 🔒 Security Hardening

**Authentication & Sessions:**
- NEW: `/logout` endpoint clears session and forces Basic-Auth re-prompt
- NEW: Session idle-timeout (default 30 min, override via `DDC_SESSION_IDLE_TIMEOUT`)
- NEW: Setup-phase rate-limit (5 req/min) protects the bootstrap window
- NEW: 12-char password policy with complexity (only enforced on `/setup` — existing passwords unaffected)
- CHANGED: `SESSION_COOKIE_SAMESITE` from `Lax` to `Strict`
- CHANGED: `SESSION_REFRESH_EACH_REQUEST` from `True` to `False`

**API & Validation:**
- NEW: SSRF whitelist on Translation API: only `api.deepl.com`, `api-free.deepl.com`, `translation.googleapis.com`, `api.cognitive.microsofttranslator.com` accepted
- NEW: CSRF foundation via Flask-WTF (all blueprints exempted by default — infrastructure ready)
- NEW: `Flask-WTF>=1.2.1,<3.0.0` dependency
- FIXED: `eval()` in translation extraction script replaced with safe `ast.literal_eval()`

**Container & Build:**
- NEW: Alpine base image pinned to multi-arch digest `sha256:25109184c71bd…`
- NEW: `pids: 256` resource limit (fork-bomb protection)
- CHANGED: `requirements-test.txt` `docker` pinned to `==7.1.0` (prod-aligned)
- CHANGED: 17 dependencies gained upper-bound version constraints

#### ⚡ Performance & RAM

- NEW: Locale lazy-loading — initial RAM footprint ~5 MB → ~120 KB
- NEW: Animation disk cache LRU eviction at 200 MB (`DDC_ANIM_DISK_LIMIT_MB`)
- NEW: Waitress thread pool sized by CPU count (`DDC_WAITRESS_THREADS`, range 2..16)
- NEW: Request-scoped config caching (`flask.g._ddc_request_config`)
- NEW: 8 dataclasses migrated to `slots=True` for memory efficiency
- CHANGED: `TEMPLATES_AUTO_RELOAD` defaults to `False` in production (override via `FLASK_ENV=development`)

#### 🧹 Architecture / Bug Fixes

- CHANGED: gevent monkey-patching is now **opt-in** via `DDC_ENABLE_GEVENT=1` — fixes scheduler-vs-asyncio conflicts on default waitress runtime
- FIXED: Scheduler service hosted/standalone modes auto-detected — eliminates "Cannot start scheduler service in existing event loop" warning at boot
- FIXED: `import docker.errors` explicit (was silent `AttributeError` on docker daemon errors)
- FIXED: `pytz.UnknownTimeZoneError` properly caught with UTC fallback in scheduler runtime
- FIXED: `_debug_mode_lock` upgraded `Lock` → `RLock` (re-entry safety after gevent removal)
- NEW: `DDC_CONFIG_DIR`, `DDC_PROGRESS_DATA_DIR`, `DDC_METRICS_DIR` env vars for custom layouts and tests

#### 📋 Logging & Storage

- NEW: Bounded log growth: `discord.log` (10 MB × 5), `bot_error.log` (5 MB × 3), `user_actions.log` (5 MB × 3)
- NEW: Debug-Mode-Toggle UI shows container-restart-required hint (i18n key `web.logs.debug_level_restart_hint`)
- CHANGED: 31 misleading `[DEBUG INIT]` / `[SETUP DEBUG]` log lines in `cogs/docker_control.py` reduced from `INFO` to `DEBUG` level — `discord.log` no longer noisy at boot

#### ✅ Testing & Quality

- 518 tests pass single-pass in container (was 184 with 48 failing pre-audit)
- NEW: 5 dedicated test directories — `security/`, `performance/`, `storage/`, `infrastructure/`, `i18n/`
- NEW: 320+ tests covering all v2.2.2 changes
- NEW: 4 production bugs uncovered and fixed via test sanitization
- Test coverage gate: **27%** (will ratchet up over time)

#### 🧹 Cleanup

- 6 root-level proposal/plan markdown files moved to `docs/archive/{proposals,completed}/`
- Empty placeholder `tests/unit/services/docker/__init__.py` removed (was shadowing real `docker` PyPI package)
- Obsolete `commit_fix.sh` development helper removed
- `.gitignore` extended with `cached_animations/*.cache`, `cached_animations/*.webp`, `cached_displays/*.png|webp` patterns

#### ⚠️ Breaking Changes (Edge Cases)

| Change | Affected Users | Mitigation |
|---|---|---|
| **SSRF whitelist on Translation API** | Self-hosted DeepL / LibreTranslate users | Use one of the four whitelisted hostnames |
| **`SESSION_COOKIE_SAMESITE=Strict`** | Cross-site iframe usage (Organizr, Heimdall etc. with different domains) | Same eTLD+1 setup or open Web UI in a direct tab |
| **30-minute idle timeout** | Long-idle browser tabs | Override: `DDC_SESSION_IDLE_TIMEOUT=<seconds>` (floor 60) |
| **gevent now opt-in** | Legacy gunicorn dev scripts (`scripts/start.sh`) | Set `DDC_ENABLE_GEVENT=1` if needed; standard waitress runtime works without it |

#### 🆕 New Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `DDC_ENABLE_GEVENT` | unset (off) | Re-enable gevent monkey-patching |
| `DDC_SESSION_IDLE_TIMEOUT` | `1800` | Session idle timeout (seconds, floor 60) |
| `DDC_WAITRESS_THREADS` | auto | Web UI thread pool size (2..16) |
| `DDC_ANIM_DISK_LIMIT_MB` | `200` | Animation disk cache cap (0 disables) |
| `DDC_CONFIG_DIR` | `/app/config` | Override config directory |
| `DDC_PROGRESS_DATA_DIR` | (auto) | Override mech progress data directory |
| `DDC_METRICS_DIR` | (auto) | Override performance metrics directory |

#### 🔄 Upgrade Notes

Standard upgrade is a simple container restart — no manual migration needed:
1. Pull the new image (Community App auto-update or `docker compose pull`)
2. Restart the container
3. Existing config (`config/config.json` + `config/containers/*.json`) loads as before
4. Existing 6+ char passwords still work for login (12-char rule applies only to `/setup`)
5. Review the Breaking Changes table above if you use self-hosted translation, embedded iframes, or rely on long-idle sessions

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
