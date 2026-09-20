# Stage 4 review - pass 1, stage C (2026-09-20 / 21)

The remaining seventeen sections, the ones the user does not see: the
configuration services (12), the Docker client pool and its helpers (15, 16),
the infrastructure services (19, 20), the mech (21, 22, 23), the scheduling
helpers (25), translation (27), the web save and status services (28, 29, 30),
the Docker status path (33), the web helpers and diagnostics (34), logging and
time (35) and the utility modules (36). One pass each, reviewer model
**Sonnet**, the code was written and fixed by Opus. Same package as stages A
and B (`scripts/review/build_package.py`): the section's source with real line
numbers, `SPEC.md`, the section's check plan and `REVIEW_TASK.md`.

**One pass is a sample, not a review** - the same caveat as stages A and B. 86
findings were reported across the seventeen sections.

## What became of the 86

| Section | Finding | Status | Reported as |
|---|---|---|---|
| 12 | F1 | fixed — C3 (`40c8ea5`) | On a v1.1.x -> v2.0 upgrade, migrate_legacy_v1_config_if_needed() extracts bot_config.json/docker_config.json/web_config.json/channels_config.json fro |
| 12 | F2 | fixed — C28 (`e57a468`) | During the automatic startup migration, migrate_channels_to_files() runs first (line 107) and writes real files into channels_dir. If the next step, m |
| 12 | F3 | fixed — C53 (`7c3bb55`) | A config-form save sets donation_disable_key to a non-empty value that fails validate_donation_key(). _process_donation_key() (lines 335-349) then doe |
| 12 | F4 | fixed — C54 (`5943cf5`) | has_real_modular_structure() (lines 166-169) decides 'real modular' purely by counting channels_dir.glob('*.json') and containers_dir.glob('*.json').  |
| 12 | F5 | fixed — C55 (`0e6c5eb`) | perform_real_modular_migration() and the migrate_* helpers it calls catch and re-raise (OSError, IOError, PermissionError, json.JSONDecodeError, TypeE |
| 15 | F1 | fixed — C33b (`9fbf746`) | The `DockerClientService` singleton is constructed at a moment with no running asyncio event loop (e.g. from the sync module-level `get_docker_client_ |
| 15 | F2 | fixed — C33 (`bb6afe2`) | Docker becomes briefly unreachable through both the configured socket path and `docker.from_env()` while the background queue processor is servicing a |
| 15 | F3 | fixed — C32 (`989a3f4`) | A request fails for a reason other than a queue timeout - e.g. `_create_new_client_async()` raises and is caught by the outer `except (..., OSError)`  |
| 15 | F4 | fixed — C32 (`989a3f4`) | The first request(s) after startup are normally served by the fast path (pool not yet full), each still incrementing the shared `self._queue_stats['to |
| 16 | F1 | fixed — C4 (`be080b4`) | USE_CONNECTION_POOL is False (docker_client_pool failed to import at module load), or the pool's own get_docker_client_async(...) call raises ImportEr |
| 16 | F2 | fixed — C59 (`d940647`) | Operator sets DDC_FAST_STATS_TIMEOUT (or DDC_FAST_INFO_TIMEOUT) below 30 in Advanced Settings, expecting Docker stats/info calls to time out fast. _lo |
| 16 | F3 | fixed — C56 (`2a40063`) | Every call to get_containers_data() (e.g. periodic status refresh) runs 'await asyncio.to_thread(client.api.containers, all=True, Lstat=True)'. docker |
| 16 | F4 | fixed — C58 (`d004627`) | In test_docker_performance(), if a container's info/stats calls raise only docker.errors.DockerException or RuntimeError on every iteration (never a p |
| 16 | F5 | fixed — C60 (`1e6e094`) | If the task running fetch_with_retries() is cancelled while inside _emergency_full_fetch (e.g. bot shutdown, or the caller's own outer cancellation -  |
| 19 | F1 | fixed — C1 (`77dbfd5`) | container.stats(stream=False) (or the CPU/memory calculation on it) raises KeyError/AttributeError/ValueError/TypeError for a running container -> _qu |
| 19 | F2 | fixed — C62 (`40b7688`) | get_cooldown_for_command tries commands.Cooldown(1, float(cooldown_seconds), BucketType.user) and, on TypeError, falls back to commands.Cooldown(1, fl |
| 19 | F3 | fixed — C61 (`ebbf490`) | before_invoke_check() returns a closure check_cooldown(ctx) that computes command_key = f'{command_name}:{user_id}' (line 40) and then, regardless of  |
| 19 | F4 | fixed — C63 (`955ec9d`) | The class docstring promises 'Per-container TTL cache plus in-flight de-duplication', and __init__ declares self._in_flight: Dict[str, asyncio.Future] |
| 20 | F1 | fixed — C29 (`51bd00f`) | The bot probes container X (going through `_set` -> `_atomic_update`) at close to the same moment the web process handles a manual re-test for a diffe |
| 20 | F2 | fixed — C64 (`0248e5d`) | If `channels_config.json`'s `spam_protection.global_settings.max_commands_per_minute` (or `max_buttons_per_minute`) holds a non-numeric string - e.g.  |
| 20 | F3 | fixed — C66 (`ec45681`) | `GameQuerySupportService.__init__` accepts a custom `path` so a caller (e.g. a test, or a differently-configured process) can point an instance at a f |
| 20 | F4 | fixed — C65 (`bf184b8`) | `mark_notification_shown()` reads `status["notifications_shown"]` with direct indexing (not `.get`). `get_update_status()` only returns a dict with th |
| 21 | F1 | fixed — C22 (`0801f9e`) | Call clear_cache() (e.g. after dropping new PNGs in to force regeneration, per its own docstring/log line 'new walk animations will be generated'). It |
| 21 | F2 | fixed — C13 (`40d9ef1`) | In _get_animation_internal (line ~1035), when the base cache file is missing and pre_generate_animation() cannot (re)create it - the documented case i |
| 21 | F3 | fixed — C67 (`f7d071d`) | Set DDC_ANIM_DISK_LIMIT_MB to a non-numeric value (e.g. 'abc'). int(...) raises ValueError, which is caught at line 128-129 and silently replaced with |
| 22 | F1 | fixed — C24 (`fe3acb5`) | If prog_service.get_state() (or get_progress_service()/get_evolution_level_info()) raises ImportError/AttributeError/ValueError/TypeError/KeyError ins |
| 22 | F2 | fixed — C11 (`ec1d07f`) | cache_key = f'comprehensive_{request.include_decimals}_{request.language}' (line 252) does not include request.include_projections or request.projecti |
| 22 | F3 | fixed — C69 (`c416acb`) | set_difficulty_multiplier's comment (lines 140-141) says 'Base cost for Level 2 is $20, so multiplier range is 0.25-2.5' to justify clamping the multi |
| 22 | F4 | fixed — C68 (`36b1281`) | _calculate_progress_data (lines 677-707) computes the evolution progress bar as core_data['total_donated'] (a lifetime cumulative figure from mech_ser |
| 23 | F1 | fixed — C5 (`10f115f`) | Restart the process (or re-obtain the singleton via get_mech_state_manager(), :147-152) while mech_state.json already holds real data for several chan |
| 23 | F2 | fixed — C19 (`1d5ac49`) | Any call to get_cached_status() that misses the cache or passes force_refresh=True (e.g. every 30s from the background loop, :304-312) ends up in _fet |
| 23 | F3 | fixed — C25 (`79b1b03`) | reset_evolution_mode() (:221-251) still writes evolution_mode.json with a plain 'open(self.evolution_mode_file, "w", ...)' (:241) followed by json.dum |
| 23 | F4 | fixed — C25 (`79b1b03`) | ensure_layout() (:58-73) creates a fresh progress config.json with a plain 'paths.config_file.write_text(...)' (:68 or :71) - not through utils/atomic |
| 23 | F5 | fixed — C71 (`aef91c1`) | _load_cache() (:30-54) returns a hardcoded {'member_count': 50, 'timestamp': '2025-09-12T13:56:30', ...} both when monthly_member_cache.json is simply |
| 23 | F6 | fixed — C72 (`16e5830`) | _get_chapter_key_for_level() (:167-183) maps any level via level_mapping.get(level, 'prologue1') (:181), so it never returns a falsy key - not for lev |
| 23 | F7 | fixed — C70 (`3b5ad9e`) | stop_background_loop() (:321-328) only cancels self._loop_task if it is set (:325-327), but nothing in this file ever assigns self._loop_task - it is  |
| 23 | F8 | fixed — C73 (`9273c46`) | add_donation_async() (:252-288) reads current_state = self.progress_service.get_state() (:263) and computes will_level_up from it (:267-269), and only |
| 25 | F1 | fixed — C74 (`9004f50`) | The scheduled donation_message task fires (mech power at/near 0, or the monthly appeal). It reads `config['channel_permissions']` and sends the embed  |
| 25 | F2 | fixed — C2 (`6765e9e`) | check_schedule_permissions(ctx, container_name, action) is called to decide whether a /schedule command may proceed. Its body never reads `ctx` (the p |
| 25 | F3 | moot — C2 removed the helper | In create_and_save_task, after add_task(task) has already returned True (the task is saved), the code calls `pytz.timezone(timezone_str)` with the tim |
| 25 | F4 | moot — C2 removed the helper | handle_schedule_command_error always calls `await ctx.respond(...)` unconditionally. If the command already sent an initial response (e.g. a defer or  |
| 25 | F5 | fixed — C75 (`4e38b75`) | get_speed_level_for_state(evolution_level, power_amount, power_max) calls _get_level_power_range(evolution_level) whenever power_max is None/<=0 or ev |
| 27 | F1 | fixed — C6 (`bff017f`) | A due task's `execute_task(task)` call (line 459) raises an exception (e.g. a transient Docker/API error) instead of completing. `self._executed_runs[ |
| 27 | F2 | fixed — C27 (`f7fc53c`) | Reading the existing `.translation_key` file fails (e.g. a permission mismatch between the user that created it and the user the app currently runs as |
| 27 | F3 | fixed — C52 (`9149455`) | add_pair() validates pair_data with validate_pair_data() (line 450, which only requires the name to be non-empty after `.strip()`) before sanitizing i |
| 28 | F1 | fixed — C12 (`dc4a80f`) | A message with two or more image attachments (e.g. two .jpg files) is posted in a source channel of an enabled, working pair. `_post_translation()` (c |
| 28 | F2 | fixed — C48 (`be4b3eb`) | `_save_configuration_files()` fails (e.g. an IOError while writing a container JSON file). `save_configuration()` (annotated to return `ConfigurationS |
| 28 | F3 | **refuted** — C48 | `process_config_form()` reports a validation/processing failure. `save_configuration()` returns `ConfigurationSaveResult(success=False, message=messag |
| 28 | F4 | fixed — C48 (`be4b3eb`) | A user changes `language` or `timezone` in the web panel. Steps 1-6 of `save_configuration()` already succeed - the main config, container configs and |
| 28 | F5 | fixed — C51 (`d96be20`) | `active_container_names` is built from `processed_data['servers']` via `server.get('docker_name') or server.get('container_name')` (lines 305-307), wh |
| 28 | F6 | fixed — C50 (`99b09d8`) | A channel pair is configured and enabled, but no translation API key is resolvable (no env var, no encrypted key, no plaintext fallback). `process_mes |
| 28 | F7 | **refuted** — C49 | An embed's text is short (e.g. 25 characters) and happens to appear verbatim inside the message content. `_build_translation_text()` drops it as a dup |
| 29 | F1 | fixed — C26 (`71c3628`) | process_web_ui_donation() returns success=True (the donation is already booked through the idempotency-protected path in unified_donation_service - se |
| 29 | F2 | fixed — C23 (`509be96`) | A request for action logs (either format) when `services.infrastructure.action_logger` cannot be imported, or raises OSError while reading its log fil |
| 29 | F3 | fixed — C18 (`9dc3140`) | Any exception inside `_get_container_logs_sync` other than docker's own NotFound/APIError - e.g. the Docker socket being unreachable or permission-den |
| 29 | F4 | fixed — C47 (`2c9cfae`) | With a `timezone` config value that is not a real IANA zone name, `pytz.timezone(timezone_str)` at line 170 raises `pytz.exceptions.UnknownTimeZoneErr |
| 29 | F5 | fixed — C46 (`0ccaee0`) | `_build_status_data_from_cache` (line 203-207) reads `cache_result.bars.mech_progress_current` etc. without a None/attribute guard, and both it (excep |
| 30 | F1 | fixed — C17 (`7046997`) | If the `docker` package fails to import (line 21-24 already codes for this: `docker = None`), and any of AttributeError/KeyError/RuntimeError/TypeErro |
| 30 | F2 | fixed — C17 (`7046997`) | If the `discord` package fails to import (line 20-23 already codes for this: `discord = None`), and `_create_progress_bar` (line 248) or `_get_infinit |
| 30 | F3 | fixed — C45 (`ccdbd34`) | In `encrypt_token`, `security_manager.encrypt_existing_plaintext_token()` (line 114) can already have succeeded when the follow-up `_log_security_acti |
| 33 | F1 | fixed — C31 (`4bf0d66`) | A Web UI 'save containers' submission where at least one previously-known container is no longer in the selected/active list (so it goes through the ' |
| 33 | F2 | fixed — C44 (`6dad15e`) | The `/donate` or `/donatebroadcast` command hits its cooldown (raises `commands.CommandOnCooldown`). `on_command_error` checks `str(ctx.command) in [" |
| 33 | F3 | fixed — C42 (`1753718`) | The stored translation API key is encrypted (`starts with 'gAAAAA'`) but fails to decrypt (e.g. the encryption key changed, or the stored value is cor |
| 33 | F4 | fixed — C43 (`abaeaa9`) | A Web UI save where the operator unchecks every action checkbox for a container (submits an empty `allowed_actions` list) -> the code silently replace |
| 34 | F1 | fixed — C7 (`ac92cca`) | Something raises while iterating containers inside `update_docker_cache`'s `for container in containers_limited:` loop (line 294) after `docker_cache[ |
| 34 | F2 | fixed — C41 (`1df5503`) | If `update_docker_cache()` (called at line 427 inside `background_refresh_worker`) raises an exception type outside {ImportError, AttributeError, Runt |
| 34 | F3 | fixed — C41 (`1df5503`) | `mech_decay_worker`'s inner try only catches `(ImportError, AttributeError, RuntimeError)` (line 694) around `mech_service.get_state()` (line 674) - u |
| 34 | F4 | fixed — C8 (`e561df4`) | A malformed or truncated JSON file under the containers config directory (e.g. one interrupted mid-write) makes `json.load(f)` at line 67 raise `json. |
| 34 | F5 | fixed — C16 (`5234323`) | `get_diagnostic_report()` sets `report['timestamp'] = logger.name` (line 363) - a fixed string such as `'app.utils.port_diagnostics'`, not a timestamp |
| 34 | F6 | fixed — C16 (`5234323`) | `check_port_binding()` matches a Docker port mapping to the expected web port with `str(internal_port).startswith(str(self.EXPECTED_WEB_PORT))` (line  |
| 35 | F1 | fixed — C21 (`2f2d576`) | admin_service.save_admin_data() (or admin_service.get_admin_data()) raises something other than RuntimeError while writing/reading admins.json - e.g.  |
| 35 | F2 | fixed — C20 (`87293f0`) | load_config() raises any exception (e.g. config.json is corrupted or unreadable) while a template is being rendered. _request_scoped_config() - called |
| 35 | F3 | fixed — C14 (`2f7ac2d`) | decrypt_key() is called with an encrypted_key that is not valid base64 (base64.b64decode raises binascii.Error, a ValueError subclass), or whose XOR r |
| 35 | F4 | fixed — C30 (`f38bec7`) | sanitize_log_message(msg) is meant to scrub secrets from a log line. Its first pattern only matches `label[:=]value` (token=, password:, key=, secret= |
| 35 | F5 | fixed — C15 (`a6fa04b`) | truncate_string(text, max_length) is called with max_length smaller than len(suffix) (default suffix is "...", 3 chars), e.g. truncate_string('hello w |
| 35 | F6 | fixed — C39 (`b2abefa`) | deep_merge_dicts(dict1, dict2) is documented as deep-merging, but only recurses for keys present as dicts on both sides. `result = dict1.copy()` is a  |
| 35 | F7 | fixed — C40 (`b1b1b9a`) | import_uvloop() first calls safe_import('uvloop'), which on success caches ('uvloop'-module, True) in the module-level _import_cache. If the immediate |
| 36 | F1 | fixed — C9 (`e9c1be6`) | A logger's handler is created once, at whatever level was in effect at that moment (setup_logger:229 console_handler.setLevel(level), :253 file_handle |
| 36 | F2 | fixed — C10 (`41322b7`) | get_setting(key, default, value_type=bool) with a panel or environment value that is not one of 'true'/'1'/'yes'/'on' (e.g. a typo like 'flase', or 'e |
| 36 | F3 | fixed — C35 (`93fa200`) | When the config service is briefly unreachable (exception during config lookup), two independent 'fallback timezone' code paths disagree: utils/loggin |
| 36 | F4 | fixed — C38 (`2d8cf77`) | get_timezone_offset('Europe/Berlin') returns '+0100' (pytz + strftime('%z'), no colon) on the normal path, but get_timezone_offset('not-a-real-zone')  |
| 36 | F5 | fixed — C34 (`2e9c092`) | StructuredLogger.process() does `extra = kwargs.get('extra', {}); extra.update(self.extra)` - the adapter's fixed context is applied LAST, so it silen |
| 36 | F6 | fixed — C36 (`c606651`) | PerformanceMetrics.__init__ sets `self.metrics_dir = Path("data/metrics")`, a path relative to the process's current working directory rather than a f |
| 36 | F7 | fixed — C36 (`c606651`) | PerformanceMetrics is a process-wide singleton whose `current_operations` dict is written by start()/end() with no lock. If two threads call start('do |
| 36 | F8 | fixed — C36 (`c606651`) | cleanup_old_metrics() reads the metrics file line by line into a temp file, then does `temp_file.replace(self.metrics_file)`. _write_metric() appends  |
| 36 | F9 | fixed — C37 (`cc7e8ff`) | with tracing.trace('donation.process') as span: raise ValueError('bad amount') - the except clause at :465-469 only catches RuntimeError, so a ValueEr |
**82 fixed, 2 refuted, 2 made moot, 0 still open.** Each fix is one commit
with its own waiting test, an announced mutation probe and a test run whose
numbers were announced beforehand; the commit message says where a prediction
was wrong. Up to review C67 that meant a full run of all 43 groups per
finding. From C67 on it means the affected groups per finding and a full run
whenever a change crosses module boundaries or closes a section - the
operator asked whether running 5,000 tests after a one-line change made
sense, and it did not. Every commit says which of the two it did.

The suite grew from 4,895 to **5,214** passing tests over the 76 commits.

## The two that did not survive re-measurement

- **28 F3** - step 3 of `save_configuration` puts its failure reason in
  `.message` while the other paths use `.error`. The route reads
  `save_result.error or save_result.message or 'Failed to save
  configuration.'`, so the reason reaches the operator either way and no test
  can show a difference. Recorded rather than changed (C48). What remains is
  a trap rather than a defect: a future caller reading only `.error` would
  lose the reason for the most common failure of the lot.

- **28 F7** - `_build_translation_text` was said to drop an embed without the
  coverage check its comment promises. The comment is wrong, the behaviour is
  not: `et_lower in content_lower` requires the whole embed text to be inside
  the message, and there is no input where the condition throws away
  something that is not already there. The comment was corrected and
  characterisation tests added so the two cannot drift apart again (C49).

## The two that had already gone

**25 F3** and **25 F4** name `create_and_save_task` and
`handle_schedule_command_error` in `services/scheduling/schedule_helpers.py`.
Review C2 had removed both as dead code before stage C reached section 25 -
their only caller was `cogs/scheduler_commands.py`, the slash commands
removed in review B17.

## Classes closed rather than single sites

Three findings turned out to be instances of a shape that sat in many places,
and each is now held shut by a scan in `tests/spec/`:

- **C17** (30 F1, F2) - an `except` clause that names an attribute of a
  module which may be `None` after a defensive import. Building the tuple
  raises `AttributeError` at the moment the handler was meant to rescue the
  situation (`test_no_except_clause_needs_a_missing_module.py`).
- **C25** - a durable file written with `open(..., "w")`, which truncates
  before the new content exists (`test_durable_files_are_written_atomically.py`).
- **C60** (16 F5) - `asyncio.CancelledError` named in a tuple with ordinary
  errors, so a cancellation is swallowed like a failure. Fifteen places
  (`test_a_cancellation_is_not_an_error.py`).

## Found while reading, not in the report

- **C57** - both error handlers in `test_docker_performance` built their
  result entry by calling `get_container_timeouts()` again - the very call
  that can put the loop into those handlers. The tool died on the container
  it was asked to diagnose.
- **C56** - besides the reported `Lstat=True`, `get_containers_data` read
  `c_data['State']` once as a string and once as a dict, so every running
  container came back as `error_processing`. An existing test described that
  correctly in its own comment and asserted it as the expected result.
- **C61**, **C71** - two modules shaped like the thing they are named after
  and wired to nothing: a `before_invoke` hook that always said yes, and a
  member-count cache that handed out a fixed 50 with a fabricated timestamp.

## What this does not say

"Touched" is not "reviewed". The 37 sections cover 60,984 lines and every one
of them has been read once by one model. A second pass over the sections that
carry secrets, permissions or money is still open, as is the split of
`DockerControlCog`.
