# Changelog

All notable changes to DockerDiscordControl will be documented in this file.

---

## v2.4.0 - 2026-09-22

Audit release. Every subsystem was reviewed, then a second pass looked specifically at what
changes for **existing installations** on upgrade. 141 findings were fixed, with 564 new
regression tests across 32 test modules.

A second wave (reviews E12-E52) added another 44 fixes and 32 more test modules before release.
The suite is now **5,699 tests**, and every source file in the project carries written evidence
that it was read - 183 of 183, up from the 22 the first wave had covered.

### ⚠️ Upgrade notes

- **You will be logged out once.** The Flask secret key is now stored permanently
  (`config/.flask_secret_key`) instead of being regenerated on every start, and the session
  cookie was renamed to `ddc_session`. Log in again and reload open browser tabs — the first save
  from a stale tab fails with a "session expired" message.
- **Long-dead scheduled tasks are paused, not resurrected.** A missed run used to stop a recurring
  task forever while the Web UI still showed it as active. That is fixed, but reviving months-old
  tasks would fire surprise restarts, so overdue tasks are deactivated once on first start and
  marked in the Web UI with their last run. Thresholds: daily > 2 days, weekly > 14 days,
  monthly > 62 days, yearly > 400 days, cron > twice its interval (at least 1 hour), everything
  else > 2 days. Re-enabling a task computes a fresh next run.
- **The monthly donation message works again** and posts to the configured channels on the 2nd
  Sunday of the month.
- **Migrated v1 installations:** on first start the settings actually in effect are folded into
  `config.json` once (a backup is written first, legacy files are renamed to `*.folded-<ts>`).
  Without this, a password or bot token could have been lost.
- **Rotate your Discord bot token** if you care: older versions kept a decrypted copy in
  `config.json` (and `config.json.bak`). Fixed, and leftovers are cleaned up on the next save.
- **Downgrading to v2.3.1:** the mech keeps working (snapshot format unchanged, the interim decay
  field is migrated out on load). But on installations migrated from v1, the one-time fold makes
  `config.json` authoritative while v2.3.1 reads only the old split files — changed credentials or
  settings would silently fall back. The pre-fold state is in
  `config/backup_<timestamp>_settings_fold/`.

### Security

- The decrypted bot token is no longer written to `config.json`; a token that cannot be decrypted
  is repaired instead of dropped. Protected container-info passwords are no longer stored in
  plaintext either.
- CSRF is enforced for **all** blueprints — no route is exempt. Pages extending the base template
  attach the token automatically; rejected requests return a clear JSON reason. `/api/admin-users`
  was not covered before, so saving admin users always failed.
- The config save no longer accepts arbitrary posted fields (password hash, token, junk keys).
- Session cookie renamed to `ddc_session` with `SameSite=Lax`; the per-request global
  `SESSION_COOKIE_SECURE` switch was removed (it could lock out plain-HTTP LAN users).
- A short `DDC_ADMIN_PASSWORD` is accepted again — otherwise a fresh install silently stayed in
  first-time-setup mode where `admin/setup` had full access. New passwords require 12 characters;
  existing ones keep working.
- Auto-action regex patterns are validated properly, and each search runs in a separate process
  with a hard 0.5 s budget, so a catastrophic pattern can no longer freeze the bot.

### Discord bot

- Status/Info/Help buttons acknowledge the interaction immediately — no more "This interaction
  failed" (Unknown interaction / 10062).
- All Docker SDK calls run off the event loop; this caused repeated container timeouts and the
  flood of "SLOW batched processing" warnings.
- Auto-action rules with more than one container work again (they locked themselves out via the
  global cooldown), honour the "only if running" option, and post a notice when a rule is skipped.
- Stop All / Restart All respect each container's allowed actions and report what they skipped.
- Deleted or renamed containers show ❓ "not found" instead of staying "offline" forever.
- Status fetches run up to 6 in parallel; CPU% shows current load instead of an average since host
  boot. Overviews refresh at least every ~60 s even with a long cache duration.
- Fixed crashes in `/control` error paths, the status path for containers with hidden details, and
  overview building when the mech cache fails. Buttons on messages from the old version keep
  working.

### Scheduler & tasks

- Weekly tasks: the weekday was never written to `tasks.json`, so weekly tasks were dropped on the
  next load; `/schedule_weekly` also stored the wrong day (off by one). Abbreviations are accepted,
  numbers are 1–7 (Monday = 1).
- Cron tasks run at all — `croniter` was missing from the image, so they were created and then
  silently deactivated.
- A slightly late task still runs once; anything older is rescheduled instead of being stuck.
- Daily, weekly and yearly runs keep their local time across daylight-saving transitions.
- Scheduled stop/restart wait for the container's configured StopTimeout and are never sent twice.
- Many tasks due in the same minute all run. Yearly tasks no longer skip the current year; Feb 29
  is preserved in leap years.
- Tasks created from Discord use the configured timezone and are checked against the container's
  allowed actions; tasks created in the Web UI always run.

### Web UI

- "Change password" actually changes the password (it previously did nothing and stored the new
  password in plaintext).
- Enter in a text field no longer submits the config form to a 405 page and loses edits.
- Heartbeat (Status Watchdog) settings are saved — every save used to switch them off.
- The mech difficulty slider loads its current state; saving no longer reports "Failed".
- Donations keep their cents; delete/restore uses a stable id instead of a list index; $0 returns
  a clear error instead of a 500.
- The last channel can finally be deleted.
- Server errors, expired sessions and failed deletes show the real message instead of a generic
  one.
- 118 previously untranslated bot and UI strings are available in all 40 languages, and 3 outdated
  texts were corrected. All 40 language files carry the same key set and the same placeholders.

### Mech & donations

- Power decay is settled on every change: a donation adds to the power you see instead of first
  paying off invisible decay debt. A mech at $0 shows as offline and is eligible for the one-time
  startup gift.
- Deleting or restoring a donation no longer shifts the displayed power or total.
- Level goals use the current member count and are not re-priced by a rebuild.
- A corrupt snapshot or a truncated line in the event log no longer blocks donations or silently
  resets the mech to level 1.
- Animation speed follows the real level.

### Deployment & startup

- New dependencies in the image: `croniter`, `psutil`.
- Docker `HEALTHCHECK` in the image. It ignores `HTTP(S)_PROXY`, so a container with a proxy
  configured no longer reports itself unhealthy (which could make autoheal restart it in a loop).
- `DDC_WEB_PORT` (default 9374) sets the Web UI port; a busy port is retried and reported clearly
  instead of crash-looping.
- An invalid bot token keeps the Web UI reachable and DDC restarts itself as soon as a new token
  is saved. Missing privileged intents are retried automatically (90 s, backing off to 15 min).
- An unwritable `logs` directory falls back to console logging instead of a restart loop.
- The entrypoint only fixes files the app user genuinely cannot use, instead of rewriting
  ownership of everything.
- An invalid `TZ` falls back to UTC with a warning instead of crashing.
- `docker stop` takes ~2 s instead of hitting the 10 s kill timeout.
- **Removed:** `scripts/start.sh` no longer offers the "Python (direct)" run mode — it referenced a
  gunicorn config that does not exist and started bot and web server as separate processes.
  Without Docker it now exits with a pointer to `scripts/rebuild.sh` / the Docker image.

### Follow-up fixes (the items the audit had deferred)

- **Auto-action cooldown is now explicit.** A rule's "Cooldown (Minutes)" always applied *per
  container*, while the code recorded a per-rule timestamp that nothing ever read. The rule
  dialog now has a scope selector: **Per container (default)** keeps the behaviour of every
  earlier release, **Per rule (all containers)** makes one trigger block the whole rule. Rules
  saved by older versions have no scope stored and keep the previous behaviour.
- **`tasks.json` is no longer rewritten on every cycle.** When invalid tasks were dropped, the
  cleanup was written back without checking whether the write succeeded. On a read-only or
  wrongly-owned config mount that repeated on every load. The result is now checked, the failure
  is logged once, and the same failing rewrite is not retried until the set of invalid tasks
  changes.
- **The scheduler no longer blocks the event loop when reading tasks.** `tasks.json` often lives
  on a network or SMB mount; it is now read in a worker thread.
- **Task lookups hand out a copy.** `find_task_by_id()` returned the cached object, so edits made
  in the Web UI leaked into the cache before (and regardless of whether) saving succeeded.
  Container task lists are returned as their own list for the same reason.
- **No absolute developer paths left in the code.** Three services fell back to
  `/Volumes/appdata/dockerdiscordcontrol/...` outside Docker — a path that existed on exactly one
  machine, and for log lookups it was even searched during normal operation. All three now derive
  the project root from their own location, so a checkout anywhere works.
- **Test coverage for the Discord layer.** Five cog modules were untested or barely tested,
  including both message listeners and the password guard for protected container info. They now
  sit between 60% and 93% (`translation_monitor` 91%, `control_helpers` 93%, `auto_action_monitor`
  88%, `autocomplete_handlers` 62%, `enhanced_info_modal_simple` 60%). Overall coverage is
  **71.3%** over 28880 statements with 4388 tests; `docker_control.py` and `control_ui.py` remain
  the weak spot at about 19%.

### Second wave (reviews E12-E52)

Two mechanical scans were written and run over all 183 source files, rather than over the 22 the
first wave had reached. Both were worked to the end.

**In Discord**

- **A button or modal that fails now answers you.** py-cord's default handler for a view or modal
  error prints to stderr and never replies, so a failed press left the interaction spinning
  forever. All 25 views and 5 modals were rebased on a common class that logs and answers.
- **A slash command that fails now answers you too.** The error handler was registered for
  `on_command_error`, which is py-cord's **prefix**-command event - and DDC has no prefix
  commands. Slash command errors go to `application_command_error`, where the default prints to
  stderr. The cure had been installed on an event that never fires.
- **One bad cycle no longer ends a background loop.** py-cord retries a task loop only for a
  short list of network errors; anything else ends it permanently and the default handler is a
  bare `print()`. A single unexpected error stopped status updates until the next restart.
- **Start, stop and restart come back with a result** when Docker is unreachable, instead of
  raising. Nine call sites read the answer as "did it work" - the buttons, the admin overview's
  bulk actions, and the scheduled tasks at four in the morning.
- **A broken mech no longer hides the whole container list.**
- **A donor is never left looking at "Processing...".**
- **Every message DDC shows reaches the locale catalogues** - about 1,900 entries across the 40
  languages, for 89 user-facing texts that were English-only, including button labels and
  dropdown placeholders. A ratchet test now fails on the next untranslated string.
- **The container dropdowns page** past Discord's hard 25-option limit. An install with thirty
  containers could not reach five of them from Discord at all.

**In the web panel**

- **The log tabs answer with text instead of Flask's HTML error page** when Docker is unreachable
  and the log files are missing - which is the moment you open a log tab to find out why.
- **A changed protected-info password takes effect at once.**
- **A failed admin read can no longer erase the admins.**
- **What one channel decides no longer decides it for the others.**
- **A Discord message costs 0 config file reads instead of 2.** The translation monitor listens
  to every message and re-read `channel_translations.json` twice to work out the message was none
  of its business. Measured after deploying: 0.066 ms and 0 file opens per message, from 0.20 ms
  and 2 reads.
- **`_()` costs 0.2 us instead of 18.1 us.** It deep-copied the entire 361-key configuration to
  find out which language to use - once per label, per container, per line.
- **Importing one service no longer imports all of them.**

**Under the floor**

Findings with no symptom yet, each pinned so the first caller is not the one who finds out: the
Docker client pool, the container status service and `get_docker_stats`/`get_docker_info` all
raised where their own return types exist to carry a failure as a value. A stop timeout that went
missing without a word could have dropped a game server to a ten-second shutdown mid-save. Four
pieces of dead state that claimed to count loop health, and three dead log helpers of which one
would have reinstated an already-fixed defect if anyone had reconnected it.

**The tests themselves**

All 4,956 test functions were classified by what their assertions can constrain. Exactly one could
not fail - `assert True` under a test named after the clamping it was meant to check, guarding a
range that had already been wrong once. Five more checked less than their names claimed, including
a security test for path traversal whose only assertion was the return type; deleting the
validation outright left it green.

Then the guards were attacked from the other side: each fix was reverse-applied and the suite
re-run. 26 of 30 could be reverted cleanly, and all 26 turned a guard red. None survived.

Both tools are in the repository - `scripts/review/audit_assertion_strength.py` and
`scripts/review/revert_each_fix.sh` - because a result that cannot be reproduced is not one.

### Behaviour changes to be aware of

| Change | Effect |
|---|---|
| Stop All / Restart All | skip containers whose allowed actions exclude the action |
| Auto-actions "only if running" | now enforced: stopped containers are skipped, with a notice |
| Scheduled tasks from Discord | checked against allowed actions at run time |
| Old, long-dead tasks | paused once on upgrade (see upgrade notes) |
| Monthly donation message | starts posting again |
| Mech | decay debt cleared, startup gift may trigger, animation speed changes |
| CPU% in status | now current load, not an average since boot |
| New passwords | minimum 12 characters |

---

## v2.3.1 - 2026-08-08

### Security

- Bumped **cryptography** from `48.x` to **`>=50.0.0`** to resolve **CVE-2026-69247** (GHSA-g6cj-pr64-35w5): a Bleichenbacher timing/error oracle exposed during PKCS#7 `EnvelopedData` decryption (High severity). The previous `<49.0.0` upper bound was widened to `<52.0.0` in line with the requirements policy so future CVE fixes are not blocked.
- Dependency-only patch — no functional changes. Rebuilt and re-released across all platform images.

---

## v2.3.0 - 2026-07-01

### Live game-server player counts

- NEW: Per-container **live player counts** for game servers, shown compactly behind the server name in the Discord status overview (`Name  3/8`) and in the per-container control box (`│ Players: 3/8`), queried via the `opengsq` library.
- NEW: **4 query protocols** — Source/A2S (most Steam survival/shooter games), Minecraft, Satisfactory (app token), Palworld (REST admin password). Token protocols require a per-server credential entered in the container's Info dialog.
- NEW: **Automatic support detection** — probes each online container across all published ports (transport-aware ordering, Steam-query range preferred), auto-detects Source vs Minecraft, and gates the per-server "Players" toggle to servers that actually answer. A 15-minute probe window (reset across downtime), permanent verdicts that survive restart, and a manual **"Test now"** re-check (3 tries, 60s apart) for slow-booting servers.
- NEW: **Guided setup** — the container name/image suggests the protocol, and token protocols make the Info button glow until a credential is entered (only while the player option is enabled).
- ADDED: `opengsq>=3.6.2` dependency (its only dependency, `aiohttp`, is already shipped).
- GUARANTEE: querying is fully non-blocking and best-effort — per-query timeouts, an overall enrichment budget, fire-and-forget support probing, and per-key atomic verdict persistence (no cross-process clobbering); a dead or slow game server never affects the Discord status loop.
- TESTS: **+102 unit tests** (query service, support lifecycle, config, enrichment). Hardened across three independent multi-agent code reviews.
- I18N: all new web-UI strings translated into all **40** supported languages.

---

## v2.2.4 - 2026-06-30

### Alpine 3.24 / Python 3.14 base bump

- CHANGED: Base image **Alpine 3.23.3 → 3.24**, which moves the runtime from **Python 3.12 → 3.14**.
- FIXED: SQLite advisories **CVE-2026-11822** / **CVE-2026-11824** (FTS5 memory corruption) — `sqlite-libs` 3.51.2-r0 → 3.53.2-r0 via the new base.
- CHANGED: `gevent` pinned **25.5.1 → 25.9.1** (25.5.1 has no cp314 wheel; 25.9.1 ships Python 3.14 wheels).
- VALIDATED: Full soak test against a live Discord server before release — the bot connects, fetches containers, and posts overviews with zero runtime errors on Python 3.14; all v2.2.3 fixes (by-ID overview delete, per-channel lock, persistence) work unchanged.

> **Not fixed (no upstream patch exists):** Alpine `busybox` **CVE-2025-60876** (Medium) is still marked "possibly vulnerable" in every Alpine branch (incl. edge). The Dockerfile already runs `apk upgrade`, so a future rebuild will pull the fix automatically once Alpine ships it.

---

## v2.2.3 - 2026-06-29

### Overview/Status message reliability & dependency security

#### 🐛 Duplicate overview messages

- FIXED: Long-lived overview/admin-overview messages (edited in place) were skipped by the
  age-limited channel cleanup once older than 30 days, so a regeneration could post a fresh
  overview on top of the stale one. The tracked overview is now deleted by its known ID first.
- FIXED: Concurrent posters (inactivity regeneration, event recreate, recovery, `/ss`,
  `/control`, initial send, channel hot-reload/teardown) could race and each post a message.
  Every delete+post path is now serialized by a per-channel `asyncio.Lock` with re-validation,
  so two paths can never produce a duplicate.
- NEW: Overview message IDs are persisted to `config/mech_state.json` and restored on startup,
  so a restart can delete the previous overview by ID instead of orphaning it. `save_state` is
  now atomic (temp file + `os.replace`), protecting all persisted state (mech expand/glvl) from
  corruption on a partial write.

#### ✨ Recreate overview below the bot's own messages

- FIXED: The "move overview to the bottom after activity" feature only triggered for foreign
  messages. The bot's own notifications (e.g. restart/update-watcher triggers) buried the
  overview permanently. The inactivity loop now distinguishes the bot's *managed* overview
  (already at the bottom) from a *stray* bot message and re-posts the overview beneath it —
  without ever treating the managed overview as foreign or disturbing in-place editing.
- NEW: Regeneration is skipped while a user is mid-interaction (e.g. expanding the mech).

#### 🔒 Dependencies

- FIXED: `cryptography` bumped to `>=48.0.1` (GHSA-537c-gmf6-5ccf — vulnerable OpenSSL bundled
  in the wheels for all versions `< 48.0.1`).

#### ⚠️ Upgrade note

On the **first restart after deploying this version**, `config/mech_state.json` does not yet
contain the new `channel_overview_message_ids` key, so a pre-existing overview older than 30
days may survive that first regeneration once. It is removed automatically on the next cycle
(self-healing); thereafter the persisted ID prevents duplicates across restarts.

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
