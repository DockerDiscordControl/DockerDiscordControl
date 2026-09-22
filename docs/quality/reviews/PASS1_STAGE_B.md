# Stage 4 review - pass 1, stage B (2026-09-20)

Nine sections, the ones the user touches every day: the two big cogs
(03-06 `control_ui.py` and `docker_control.py`), the info modals (07), the
status handlers (08), the task UI (09, 10) and the automation and channel
configuration services (11). One pass each, reviewer model **Sonnet**, the
code was written and fixed by Opus. Same package as stage A
(`scripts/review/build_package.py`): the section's source with real line
numbers, `SPEC.md`, the section's check plan and `REVIEW_TASK.md`.

**One pass is a sample, not a review** - the same caveat as stage A. 242 of
the section's names were judged, 40 findings reported.

## What became of the 40

| Section | Finding | Severity / certainty | Status | Reported as |
|---|---|---|---|---|
| 03 | F1 | high / unsure | fixed — B27 (`db871d5`) | AdminContainerDropdown.callback does no permission check of its own: it hardcodes channel_has_control_permission=True (line 2093, 'Admin always has co |
| 03 | F2 | high / sure | fixed — B4 (`c3c785f`) | In MechHistoryButton.callback, 'await interaction.response.defer(ephemeral=True)' (line 2685) sits inside 'if spam_service.is_enabled():' (line 2672)  |
| 04 | F1 | high / unsure | fixed — B11 (`03df97f`) | If heartbeat.enabled=true in config and heartbeat.ping_url is stored as null/None (key present, value None - e.g |
| 04 | F2 | low / sure | fixed — B15 (`c59dd42`) | In periodic_message_edit_loop, `all_container_names = set()` is initialized at line 703 but nothing between there and the check at line 819 (`if all_c |
| 04 | F3 | low / unsure | fixed — B39 (`acd2ce1`) | _setup_background_loops wraps every other startup task (status_task, edit_task, inactivity_task, cache_task, and heartbeat_task when enabled) with `se |
| 04 | F4 | low / unsure | fixed — B16 (`e91e632`) | send_initial_status_after_delay_and_ready(self, delay_seconds) duplicates the nested send_initial_after_delay() already scheduled inside _setup_backgr |
| 05 | F1 | high / sure | fixed — B8 (`48bdfb1`) | Right after bot startup, or whenever a container's cached status entry is missing or has expired (older than DDC_DOCKER_MAX_CACHE_AGE, default 300s),  |
| 05 | F2 | medium / unsure | fixed — B13 (`d13c751`) | DockerControlCog._handle_donate_interaction is defined twice in the same class: once at line 2215-2273, again at line 3277-3348 |
| 05 | F3 | low / unsure | fixed — B38 (`f39d0c2`) | Every other slash command defined in this section (control at 1947, help_command at 2091, ping_command at 2141, donate_command at 2172, info_command a |
| 05 | F4 | low / unsure | fixed — B23 (`c6cdda1`) | In _create_overview_embed_expanded, routine and always-present values (the mech progress bar's current/max numbers and their types) are logged with lo |
| 06 | F1 | high / sure | **refuted** | In DonationBroadcastModal.callback, an admin submits the broadcast modal with a valid amount (e.g |
| 06 | F2 | medium / sure | fixed — B14 (`fc721cc`) | An admin submits the broadcast modal with a valid amount; process_discord_donation returns success=False (e.g |
| 06 | F3 | medium / sure | fixed — B31 (`68586b0`) | The DockerControlCog extension is unloaded and reloaded (cog_unload() then setup() again, which is exactly the scenario cog_unload's docstring targets |
| 06 | F4 | low / sure | fixed — B36 (`a7abfd6`) | An admin runs the /donate broadcast flow with 'Share publicly' checked while at least one configured channel has donation_broadcasts=False (an intenti |
| 06 | F5 | medium / unsure | **refuted** | control_command checks _channel_has_permission(ctx.channel.id, 'control', self.config) against self.config, the snapshot captured once in setup() (:51 |
| 06 | F6 | high / unsure | **refuted** | During inactivity_check_loop, for any tracked channel that has reached its inactivity timeout and has at least one message in its last 3 messages (the |
| 06 | F7 | high / unsure | fixed — B18 (`5ab3f40`) | The operator disables donations (is_donations_disabled() returns True) |
| 07 | F1 | high / sure | fixed — B6 (`b3a85e5`) | Admin A opens the plain 'Edit Info' modal (SimplifiedContainerInfoModal) for a container that already has protected_enabled/protected_content/protecte |
| 07 | F2 | medium / unsure | fixed — B19 (`c0bdc0b`) | self.info_service.get_container_info(...) or save_container_info(...) inside ProtectedInfoModal.callback raises IOError/OSError/PermissionError (e.g |
| 07 | F3 | high / sure | fixed — B7 (`94354ac`) | Any user with 'control' channel permission opens the plain 'Edit Info' modal (SimplifiedContainerInfoModal.__init__, line 58) or the 'Protected Info'  |
| 07 | F4 | low / unsure | fixed — B12 (`ddd2f9d`) | PasswordValidationModal.callback compares the submitted password to stored_password with a plain `!=` and applies no attempt limit, delay or lockout |
| 08 | F1 | high / sure | fixed — B9 (`5a46437`) | A pending start/stop/restart action (`self.pending_actions`) takes longer than PENDING_TIMEOUT_SECONDS (120s) |
| 08 | F2 | medium / unsure | fixed — B37 (`4c51a42`) | `bulk_fetch_container_status` only treats a container as 'not found' when `info is None` (line 206: `if info is None and get_container_status_service( |
| 08 | F3 | medium / unsure | fixed — B20 (`5e8a568`) | In `get_status`, stats are read as `cpu_percent = stats_dict.get('cpu_percent', 0.0)` and `memory_mb = stats_dict.get('memory_usage_mb', 0.0)` (lines  |
| 08 | F4 | medium / sure | fixed — B30 (`9c04192`) | `bulk_update_status_cache`'s outer try/except explicitly lists `asyncio.CancelledError` among the caught exceptions (`except (RuntimeError, asyncio.Ca |
| 08 | F5 | medium / sure | fixed — B25 (`8013baf`) | The comment right above this loop (line 182: '# Process all results into status tuples - ALWAYS WITH COMPLETE DATA') and the function's own docstring  |
| 09 | F1 | medium / sure | fixed — B21 (`8ba9cf1`) | A user picks cycle 'monthly', 'yearly' or 'once' in the task-creation flow (AddTaskButton -> TaskCreationView -> ActionDropdown -> SimpleMonthdayDropd |
| 09 | F2 | critical / unsure | fixed — B3 (`0fa1989`) | A channel holds the 'control' permission when a user presses the info button, so StatusInfoButton.callback (line 858) builds a ContainerInfoAdminView  |
| 10 | F1 | critical / sure | fixed — B1 (`3bb7040`) | auto_actions.json becomes unreadable for one call (JSONDecodeError or IOError - e.g |
| 10 | F2 | medium / unsure | fixed — B22 (`de881fd`) | User creates a 'yearly' task via the container's quick-create button: picking a predefined date from YeardayDropdown sets self.view.selected_day to a  |
| 10 | F3 | low / unsure | **refuted** | A locale file maps some key to a deliberately empty string, e.g |
| 10 | F4 | low / sure | fixed — B29 (`862a916`) | tempfile.mkstemp() itself fails (line 495 - e.g |
| 10 | F5 | low / unsure | fixed — B33 (`efb78aa`) | trigger.keywords contains a non-string element whose str() representation exceeds MAX_KEYWORD_LENGTH (100 chars, e.g |
| 11 | F1 | high / sure | fixed — B10 (`39ac4c4`) | A rule with cooldown_scope='rule' targets two or more containers |
| 11 | F2 | low / sure | fixed — B29 (`862a916`) | _save_state() assigns 'fd, temp_path = tempfile.mkstemp(...)' inside the try block (line 106) |
| 11 | F3 | medium / unsure | fixed — B35 (`5218801`) | get_cached_token(), set_cached_token() and clear_token_cache() read/write self._token_cache and self._token_cache_hash without taking self._cache_lock |
| 11 | F4 | critical / sure | fixed — B2 (`d922c3d`) | _parse_channel_type() (used by parse_channel_permissions_from_form) stops scanning for more channel rows as soon as it hits an empty '{prefix}_channel |
| 11 | F5 | high / sure | fixed — B5 (`c8a3b55`) | process_config_form() calls ConfigFormParserService._save_channel_permissions(channel_permissions) and never looks at its result |
| 11 | F6 | medium / unsure | fixed — B32 (`53c156b`) | In get_all_channels(), when a legacy file with a non-ID filename (e.g |
| 11 | F7 | medium / sure | fixed — B24 (`a32e7da`) | save_channel() writes the per-channel file, then unconditionally calls self._update_main_config(channel_id, config) (line 247) and returns True regard |
**36 fixed, 4 refuted, 0 still open.** Each fix is
one commit with its own waiting test, an announced mutation probe and a full
run of all 43 groups; the commit message carries the numbers that were
announced beforehand and says where a prediction was wrong.

Four findings did not survive re-measurement, and each refutation rests on a
measurement rather than an argument:

- **10 F3** - of 65,040 entries across the 41 catalogues not one is an empty
  string, so nothing uses "" to suppress a label. An empty value here would be
  a translation gap, and falling back to English is the better answer than an
  invisible one (B34).

- **06 F1** - `new_state.Power` does not raise: `new_state` is a `MechState`,
  which carries `Power` as an alias of `power_level`, while the neighbouring
  lowercase reads are on the service RESULT objects. The fragility is real all
  the same - the donation is booked before those lines run - so the alias is
  pinned by `tests/spec/test_the_donation_path_reads_fields_that_exist.py`.

- **06 F5** - self.config is a property that reads the live config on every access - control_command never judges by a stale permission (measured, B18).
- **06 F6** - channel.history().flatten() exists in py-cord 2.6.1 - measured in the running container, not argued (B18).

## Found while reading, not in the report

- **B17** - `cogs/scheduler_commands.py` (795 lines) and
  `cogs/autocomplete_handlers.py` (408 lines): two modules the bot never
  loads. The slash commands they hold were replaced by the ⏰ buttons long
  ago, as `docker_control.py` says in its own words.
- **B22** - nine dropdowns, views and buttons that nothing ever builds,
  among them the "DD.MM" date handling that 10 F2 reported as a crash. It
  cannot crash: it cannot run.

Both are now held shut by scans in `tests/spec/`
(`test_every_cog_module_is_reachable.py`,
`test_every_ui_class_is_ever_built.py`).
