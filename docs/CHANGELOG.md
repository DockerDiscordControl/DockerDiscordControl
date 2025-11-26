# Changelog

All notable changes to DockerDiscordControl will be documented in this file.

## v2.5.2 - 2025-11-26

### Auto-Action System (AAS) - Critical Fixes & Hardening

#### 🔴 Critical Bug Fixes + Additional Hardening

**State File Migration** (`auto_action_state_service.py`)
- Fixed key mismatch: `global_cooldown_last_triggered` → `global_last_triggered`
- Added automatic migration logic for existing installations
- Added missing `container_cooldowns` key to state file structure
- Cooldowns now properly persist across service restarts

**Async Route Handler Fix** (`automation_routes.py`)
- Fixed async/sync mismatch in Flask route `/api/automation/test`
- Converted to synchronous handler with proper asyncio.run() wrapper
- Added 30-second timeout for safety
- Prevents potential blocking of Flask event loop

**Race Condition Prevention** (`auto_action_state_service.py`)
- NEW: `acquire_execution_lock()` - Atomic check-and-set for cooldowns
- NEW: `release_execution_lock()` - Cleanup on execution failure
- Prevents duplicate rule execution from rapid concurrent messages
- Updated `automation_service.py` to use atomic locking

#### 🟠 Security Hardening

**Comprehensive Input Validation** (`auto_action_config_service.py`)
- Discord Snowflake ID validation (17-19 digits)
- ReDoS prevention for regex patterns (detects catastrophic backtracking)
- Priority range validation (1-100)
- Cooldown range validation (1-10080 minutes)
- Delay range validation (0-3600 seconds)
- Keyword count limit (max 50)
- HTML/XSS sanitization for rule names
- Action type validation (RESTART, STOP, START, RECREATE, NOTIFY)

**Protected Container Warnings**
- Validation now warns when rules target protected containers (ddc, portainer)
- Warnings stored in rule metadata for visibility
- Runtime protection remains unchanged (blocks execution)

**Regex Timeout Protection** (`automation_service.py`)
- Added 500ms timeout to regex execution via `asyncio.wait_for()`
- Prevents ReDoS attacks from hanging the message processing
- Graceful fallback: logs warning and continues to keyword matching (if available)
- Regex-only rules return clear "Regex timeout" message on failure

**Improved Error Handling** (`auto_action_state_service.py`)
- Added explicit SKIPPED result handling in `record_trigger()`
- Added debug logging for cooldown releases on failed executions
- Clearer distinction between SUCCESS, FAILED, and SKIPPED states

**Better Error Messages** (`automation_service.py`)
- Regex-only rules now return "Regex pattern did not match" instead of "No keywords"
- "No trigger conditions configured" instead of generic "No keywords" message
- Truncated regex pattern in error messages (max 50 chars) for readability

#### 🔧 Frontend Improvements

**Form Data Preservation** (`auto_actions.js`)
- Fixed bug: `allowed_usernames` no longer lost on rule edit/save
- Preserved `enabled` state when editing existing rules
- Added `currentRuleData` variable to track full rule state

#### 📝 Technical Details

**Files Modified:**
- `services/automation/auto_action_state_service.py` - Migration, atomic locking
- `services/automation/auto_action_config_service.py` - Validation functions
- `services/automation/automation_service.py` - Use atomic locking
- `app/blueprints/automation_routes.py` - Sync route handler
- `app/static/js/auto_actions.js` - Form data preservation
- `config/auto_actions_state.json` - Corrected key names

**Validation Constants Added:**
```python
MAX_RULE_NAME_LENGTH = 100
MAX_KEYWORDS = 50
MAX_KEYWORD_LENGTH = 100
MIN_PRIORITY = 1, MAX_PRIORITY = 100
MIN_COOLDOWN_MINUTES = 1, MAX_COOLDOWN_MINUTES = 10080
MIN_DELAY_SECONDS = 0, MAX_DELAY_SECONDS = 3600
```

---

## v2.5.1 - 2025-11-26

### Unified Logging & Cleanup

- Enhanced logging across all services with unified logging_utils
- Removed obsolete mech config files (evolution_config.json, speed_translations.json)
- Removed hardcoded story files (now loaded dynamically via service)
- Improved token security and web helper functions
- Standardized logging patterns across infrastructure services

---

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
