# Stage 0 — DDC Inventory

**As of:** 2026-09-16 · **Applies to:** commit `bfbda50` on `develop` · **No code was changed.**

This is the inventory from stage 0 of the quality programme. It describes what DDC does,
where a mistake cannot be undone, what the 3,962 tests actually prove — and above all,
**what was not checked**. The last section is the most important one.

Two principles govern the ranking:
**"Unnoticed beats rare"** — findings are ranked by whether the user notices, not by how
technically serious they sound. And: **a test that cannot fail is not a test.**

---

## 0. Method and verifiability

| Source of evidence | Scope | Reliability |
|---|---|---|
| AST census of the test suite | all 113 files, 3,962 test functions | **mechanical**, repeatable, no model judgement |
| Test run in the real runtime environment | 24 groups + 18 individually, throwaway container | **empirical** |
| Isolation experiment | 4 runs in both orders | **empirical** |
| Five reading passes (cogs, frontend, test semantics, runtime, irreversible spots) | see section 12 | reading findings, spot-checked |
| My own verification | ~20 claims looked up in the source | directly verified |

Findings marked **[verified]** I saw in the source myself. Findings marked **[read]** come from
a reading pass and were not individually cross-checked.

### Two observations about the method itself

**A pass is a sample, not an audit.** Two independent passes over the same
question ("where is something irreversible?") produced **clearly different lists**. The second found
`scheduler.py:1139` (writes `"[]"` over a missing task file), `member_count/service.py:174`,
`progress/runtime.py:112` (rewrites the configuration after a read error without a backup) and
the `subprocess` calls in `port_diagnostics.py` — the first found none of these. Conversely, the first had
findings the second did not mention. This matches the expectation from the programme: *pairwise
intersection close to zero*.

**The mechanical tool errs too — and that could be shown.** The first run reported 92 tests
with no check at all, among them seven in `tests/security/test_security_sast.py`. Cross-checking the
source showed: these tests check via `pytest.fail()` inside an `if`, not via `assert`.
After fixing the counter: 85. A second false alarm concerned "mock tautologies": of 12
reported, **3** remained after the fix, because a single hollow `assert` next to a real
check is harmless. The tool and the tool fix are in the appendix.

---

## 1. What DDC is, and what happens in the worst case

DDC controls Docker containers on an Unraid server from Discord and ships a
Flask web panel for this. One process, two halves: web UI in a daemon thread, bot in the main thread
(`run.py:113`). Around 129,000 lines of Python, ~63,000 of them test code. The container is attached to the
Docker socket and therefore effectively controls all containers on the host.

The four kinds of damage, sorted by "does the user notice?":

### A. Wrong information about money — silent

The donation ledger (`services/mech/progress_service.py`, an append-only event log) is the
record of **real** Ko-fi donations, which are entered by hand.

- **Any Discord user can credit arbitrary amounts.** `cogs/docker_control.py:4731`
  (`DonationBroadcastModal.callback`) has **no** check: no admin check, no channel check,
  no cooldown. The amount is only checked for format and sign (`:4757-4773`), then written to the ledger at
  `:4822`. **[read]**
- **If the booking fails, the thank-you message goes out anyway.** `:4885-4887` catches the error,
  sets `evolution_occurred = False` — and at `:4939` "X donated Y — thank you so much"
  is sent to every configured channel. **[verified]**
- **This path ignores the opt-out setting.** The broadcast at `:4939` iterates over *all*
  entries in `channel_permissions`. The parallel path in the notification task, by contrast, does
  check `channel_info.get('donation_broadcasts', True)` (`:5165`). Two paths, the same job,
  a rule in only one place. **[verified]**

### B. Data loss, irrecoverable

- `POST /api/donation/reset-power` truncates the event log to empty:
  `event_log.write_text("")` (`services/donation/unified/reset.py:96`). No backup, no
  dry run, no server-side confirmation — while the configuration save right next to it dutifully
  creates a `.bak`. **[verified]**
- **The test suite itself can destroy real data.** `MechResetService.__init__`
  (`services/mech/mech_reset_service.py:42-45`) resolves `config_dir="config"` against the project root
  and **ignores `DDC_CONFIG_DIR`**. `tests/unit/services/mech/test_mech_data_services.py:944`
  calls `quick_mech_reset()` and replaces *only* `reset_all_donations`; `reset_mech_state()`,
  `reset_evolution_mode()` and `cleanup_deprecated_files()` run live against the real
  `config/`. That nothing happened in our runs is solely because `ddc_test.sh`
  mounts an empty directory over `/app/config`. Anyone using `scripts/run_tests_unraid.sh` or
  `run_tests.sh` does not have this protection. **[verified]**

### C. Third-party access to the containers

Authorization on the Discord side is **bound to the channel, not to the user** — see section 4.

### D. Costs

No payment provider, no SMTP; Ko-fi/PayPal are plain links. Real external costs arise
only through the translation APIs (DeepL/Google/Microsoft). There: the bot path
(`services/translation/translation_service.py:474`, triggered by every matching Discord message)
has **no spending cap and no rate limit** — every message costs money. **[read]**

---

## 2. Where logic lives and where there is only wiring

| Area | Lines | Classification |
|---|---|---|
| `services/` | ~60,800 | **The logic.** Configuration, scheduler, donations/mech, Docker, translation. |
| `cogs/` | ~15,500 | **Mixed — the core problem.** `docker_control.py` 5,216 lines/97 functions; `control_ui.py` 3,316; `status_info_integration.py` 2,633. **Authorization decisions live here, not in `services/`.** |
| `app/blueprints/` | ~3,200 | Mostly wiring (81 routes), but `main_routes.py` carries logic in the routes (among other things a bare daemon thread from `:806`). |
| `app/web/`, `app/bot/` | ~1,400 | Clean wiring in small files. The best-cut part of the project. |
| `utils/` | ~3,300 | Logic helpers (time, crypto, config cache, observability). |
| `scripts/` | 51 files | Operator tools, untested, write configuration mostly **non-atomically**. |

---

## 3. The test suite in numbers

**Empirically, in the real runtime environment** (throwaway container from the production image,
`scripts/ddc_test.sh`, 24 groups + 18 individually):

> **4,492 tests green. Zero failures. Two skipped.**

That is a real result and a good one. It says nothing, however, about what these tests
prove. For that, the census:

| Category | Count | Share |
|---|---:|---:|
| checks something | 3,563 | 89.3 % |
| **only hollow checks** (`is not None`, `isinstance`, `len`, `x == x`) | **265** | 6.6 % |
| **no check at all** | **85** | 2.1 % |
| only via `mock.assert_*` | 65 | 1.6 % |
| mock tautology | 3 | 0.1 % |
| skipped | 6 | 0.2 % |
| `pytest.raises(Exception)` — catches everything | 3 | 0.1 % |

**Hollow in total: 362 of 3,962 (9.1 %).** Of these, **134 are in `tests/unit/extended/` alone** — the
directory that describes itself in `test_app_utils_extended.py:10` as work on the coverage
figure. Only 10 of the 362 are in `tests/unit/audit_2026_09/`.

> **Correction, added 2026-09-16.** Until just now this said 356 of 3,990 (8.9 %) and "only 6".
> Those numbers were wrong, and how they came about belongs in this report: I ran the census,
> wrote the numbers from the screen into this document (21:41), then **repaired the counting tool
> twice more** — `pytest.fail()` was not recognised as a check (92→85), and a hollow
> `assert` next to a real one classified the whole test as a tautology (12→3) — and stored the final
> measurement at 21:46 without updating the document. So the old numbers were measured,
> but not by the tool as it finally stands. Only `test_audit.json` (21:46) is authoritative;
> its category sum adds up to exactly 3,962. The same kind of error — measure once, then
> quote, although what was measured has changed — happened to me a second time today.

**A genus of its own among the hollow tests: "must not raise" (2026-09-16).**
Of the 362 findings, 45 sit close to money, deletion or permissions; 7 of them are `no_verification`,
i.e. contain **not a single assertion**. Almost all are named `*_swallows_*`, `*_handles_bad_*`
or `*_is_caught`. Three have been read in full:
`test_handle_donation_event_swallows_bad_payload`, `test_log_security_action_swallows_runtime_error`,
`test_rotation_swallows_oserror`. Their entire body is: call the function, it must not raise.

They are **not** "tests that cannot fail" in the strict sense — if the code raises, there is
an error. But they pin down only that nothing blows up, and never whether the clean-up did the
**right** thing: whether the warning was really written, whether the state is intact afterwards.
In `test_rotation_swallows_oserror` the comment says "the helper logs the error and returns" —
the logging is not checked. A comment that claims more than its code.

*The instructive part goes against me:* I ranked these three by severity twice and was
**wrong both times**, because I inferred from the name instead of reading the code. First
I considered `_log_security_action` the most expensive ("the security trail silently stops recording") —
in fact it only catches `RuntimeError` and writes a warning (`security_service.py:326`).
Then I considered the log rotation the real case ("backups half moved") — in fact
the caller does not depend on it, no entries are lost, at most one backup can
be overwritten (`action_log_service.py:271`, `:280`).

**Result: none of the three code locations justifies an intervention.** The finding is the tests,
not the code — and it therefore belongs to stage 3 (report, delete nothing without consent),
not to stage 2. The ranking by "does the user notice" cannot be
derived from identifiers; I tried it twice in one day anyway.

The reasons behind the 265 hollow checks: 203× `is (not) None`, 46× only `isinstance()`, 19× only `len()`,
5× `x == x`, 3× only `callable()`, 2× only `hasattr()`, 1× constant.

### The category "only `mock.assert_*`" is a *strength*

The 65 tests in this category check `assert_not_called()`, `assert_awaited_once_with(...)`,
`defer` before the response. That is **checking the call site** — exactly what is most often missing.
Examples: `test_pkg_b_control_ui.py:126` (`interaction.response.defer.assert_awaited_once_with`),
`test_pkg_b_docker_control.py:72` (`bulk_fetch_container_status.assert_not_awaited`). **[verified]**

### Individual findings with line numbers

- **Six tests that mirror `run.py`.** `tests/unit/performance/test_bundle4_7_performance.py:388-437`
  rebuilds the thread calculation from `run.py:57-62` inside the test; the docstring at `:391` admits it
  ("We replicate the logic exactly"). **`run.py` could be deleted and all six would stay green.**
- **`test_services_gaps.py:3328`** — `state = svc.tick_decay(); assert state is not None`. The
  decay of the balance is the whole purpose of the function and is not checked.
- **`test_container_info_service.py:329`** — named `test_input_sanitization`, sends
  `<script>alert('xss')</script>` in and checks that *some* result object came back.
- **`test_utils_completion.py:638,644,650`** — `assert ok in (True, False)`. Pure tautology.
- **`test_utils_completion.py:670`** — `assert any(...) or True`.
- **`test_docker_pool_fetch.py:900`** — compares two exception instances that can never be
  equal; the test cannot fail.
- **`test_query_failure_demotion.py`** (12 places) — loops over `range(QUERY_FAILURE_DEMOTE_THRESHOLD)`
  without ever pinning down the threshold. Change it to 99 and everything stays green.
- **`test_r2_g4_status.py:248-275`** — builds entries at `STATUS_CACHE_MAX_RENDER_AGE_SECONDS ± 30`,
  but **no test pins the 60 seconds**. A change to 3600 goes unnoticed.

### 306 tests hang on a single configuration line

`pytest.ini:65` sets `asyncio_mode = auto`. **562 asynchronous test functions exist, 306 of them
carry no `@pytest.mark.asyncio`.** Without this line they would become never-awaited coroutines —
and a never-awaited coroutine makes the test **pass**, not fail. The loss would
therefore be invisible: 306 tests would keep reporting green without ever executing anything. **[verified]**

### Further additions

- **A missing bandit silently skips the security scan.**
  `tests/security/test_security_sast.py:57-70` catches `TimeoutExpired`, `FileNotFoundError` and
  unexpected return codes, each with `pytest.skip`. The guards are legitimate in themselves, and
  `returncode == 0` correctly means "nothing found" — but if the tool is not installed,
  the run reports "skipped" instead of "unchecked". **[verified]**
- **`tests/unit/extended/test_docker_infra_gaps.py:466` and `:591`** check for
  `status == "error_processing"` — and the comments next to them call exactly that a
  production bug. The test **freezes the bug as the expected behaviour**. **[read]**
- **Dead weight:** `tests/load/locustfile.py` targets `/login`, `/dashboard`, `/containers`,
  `/api/status` — **none of them is a registered route**; the file is never collected anyway.
  Of `tests/security/security_test_helpers.py` only `scan_for_patterns` is used; nine other
  functions are unused in the entire tree. **[read]**

### Order dependence: suspicion empirically refuted, structure remains risky

`tests/unit/services/scheduler/test_scheduler_service.py:26` deletes *every*
`docker*` entry from `sys.modules` on import and rebuilds the module. Two other files have therefore
built in workarounds and write down the reason (`test_docker_pool_fetch.py:58-63`).

**Experiment:** 45 tests alone · 9 alone · **54 together in both orders.**
No difference. The suspicion is **not reproducible** for this pair — the workarounds work.
The structural danger remains, the concrete accusation does not.

### What, by contrast, really has process-wide effect

- **`dataclasses.dataclass` is permanently replaced on import**, in six files
  (`test_blueprint_gaps.py:30-42` and identically in `test_main_automation_security_routes.py`,
  `test_services_gaps.py`, `test_coverage_push_v3.py`, `test_utils_gaps.py`,
  `test_app_utils_extended.py`). The replacement removes `slots=` and is **never reverted**; there is
  no version check, only a run-once guard. As soon as one of these files is collected,
  the eight production `slots=True` dataclasses are created **without
  slots** for the rest of the run. An irony on the side: the docstring of the same file warns at `:25`
  "NEVER manipulate `sys.modules` here". **[verified]**
- **`tests/conftest.py:168-173`** — the autouse fixture `cleanup_after_test` has an **empty
  body**. Several files rely on "automatic clean-up". There is none.
- **`tests/conftest.py:26-56`** sets `TESTING`, `DDC_LOG_LEVEL` and three temp directories
  process-wide on import, without a fixture and without clean-up. This redirection is the only thing
  keeping tests with real singletons away from the live installation — and `MechResetService` bypasses
  it (section 1.B).

### Skipped tests that nobody misses

- `tests/unit/utils/test_utils_completion.py:381` — **always** skips: OpenTelemetry is
  commented out in `requirements-test.txt:70-74`.
- Four tests with `skipif(geteuid() == 0)` (`test_pkg_c2_services.py:110`, `test_pkg_c2_config.py:218`,
  `test_r2_g3_startup.py:352`, `test_pkg_f_utils.py:136`) silently disappear as soon as the suite runs as
  root. That `ddc_test.sh` starts with `-u ddc` is what keeps them alive.
- `test_bundle5_8_infra.py` uses `importorskip("flask_wtf")` four times without a reason — if
  Flask-WTF is missing, exactly the four CSRF tests disappear, i.e. under precisely the condition under which
  CSRF fails project-wide.
- The module skip in `tests/unit/extended/test_bot_startup.py:59` (74 tests) applies **only under
  Python 3.10**; the runtime is 3.14. **Harmless — suspicion withdrawn.** **[verified]**

---

## 4. The authorization map

On the Discord side there is no user-based authorization — what is checked is the *channel*, via
`_channel_has_permission` (`cogs/control_helpers.py:95`).

> **Confirmed by the operator (2026-09-16): this is intended.** A control channel grants control to all
> members of that channel; whoever is in the control channel *is* an admin. Access
> control therefore lies with Discord (who may see the channel), not with DDC. This belongs
> in the SPEC as a deliberate decision, otherwise the next refactoring will "fix" it.
>
> **The global admin list is intended too — and its purpose is the *status* channel.** Confirmed by the
> operator (2026-09-16): `/addadmin` exists mainly so that admins may do things where
> channel membership alone permits nothing. That the right outlives the membership is
> accepted. The list is checked in exactly four places:
> `docker_control.py:2034` (appointing admins from a status channel), `control_ui.py:995-998`
> (bypasses the channel check for container info), `control_ui.py:1769` (AdminButton) and
> `admin_overview.py:190,264` (Stop-All / Restart-All).
>
> **Newly open:** `/donate` and its modal have **no channel check at all**
> (`docker_control.py:2137-2162` — only `defer`, the donations-disabled check, spam protection). Crediting
> the donation ledger is therefore **not** limited to control channels but possible
> anywhere the bot offers slash commands. That is a question of its own, independent of the channel model.

| Location | Effect | Check |
|---|---|---|
| `cogs/control_ui.py:263` `ActionButton` | **container start/stop/restart** | cooldown, channel permission `control` (`:304`), `allowed_actions` (`:310`). **No user check.** **[verified]** |
| `cogs/docker_control.py:1931` `/control` | opens the admin panel | channel permission only. **No admin check.** |
| `cogs/docker_control.py:2014` `/addadmin` | adds an admin (`:5053`) | in the control channel a literal `pass` with the comment "any user in control channel can add admins" (`:2026-2029`). **[verified]** |
| `cogs/docker_control.py:4731` donation modal | ledger + broadcast | **nothing at all** |
| `cogs/status_info_integration.py:2567` | **deletes a scheduled task** (`:2585`) | **nothing at all** — while the same operation in `control_ui.py:1236` checks the channel permission `schedule` (`:1269`). **[verified]** |
| `cogs/control_ui.py:1932` `AdminContainerDropdown` | builds a control panel and hard-sets `channel_has_control_permission=True` (`:2014`) | **no renewed admin check** |
| `cogs/auto_action_monitor.py:66` | passes **every message in every channel** to the rule engine | only what the rule itself restricts |
| `cogs/scheduler_commands.py:166-181` | creates a scheduled task | only checks whether the *container* allows the action — not who is scheduling |

Aggravating: **the channel permission is bypassed four times by a text comparison on the embed title**
(`"Admin Control" in embed_title`, `control_ui.py:298-301, 424-429, 1019-1022, 1071-1075`) — an
authorization-relevant heuristic on a display string. And there are **two different
definitions** of "control channel": `_channel_has_permission(..., 'control')` everywhere, but
`control_ui.py:1572` checks `allow_start or allow_stop` instead — keys the first
function never reads. The two can contradict each other.

Only **one** component checks real admin rights: `control_ui.py:1749` `AdminButton` (`:1769`).

**On the web side** the picture is clearly better: 81 routes, CSRF project-wide without exception,
rate limiting. Reachable without login are only `POST /setup` (correctly refuses if a
hash already exists; its own 5/min cap), `POST /api/donation/click` (writes an
attacker-controlled `X-Forwarded-For` to the log), `GET /api/donation/status` (explicitly
exempt from rate limiting, `app/auth.py:146`) and five read-only mech endpoints. **[verified]**

---

## 5. Irreversible spots

**Touching containers** — pleasingly narrow: only `start`/`stop`/`restart`, two implementations
(`docker_action_service.py:168`, `docker_utils.py:629`). **No `kill`, no `remove`, no `prune`.**
That is a real property that deserves to be recorded before someone loosens it.

For the scheduler: re-checking the allowed action runs **only for tasks created in
Discord** (`scheduler.py:1796`). Web UI tasks run unchecked. The reasoning is in the code
(`:1665-1671`) and is understandable; the consequence is written nowhere. **[verified]**

**Deleting/overwriting data:** donation reset (above), mech reset
(`mech_reset_service.py:176` — the only spot that is **not atomic**), clearing the action log
(`action_log_routes.py:95` — of all things deletes the record of who did the other
irreversible things), password change (`config_service.py:563-579` — if the
decryption fails beforehand, the bot token is permanently unreadable), Flask key
(`app/web/config.py:108` — invalidates all sessions). Also writing non-atomically:
`server_order.py:45`, `member_count/service.py:174`, `progress_service.py:264`,
`container_status_service.py:153`.

**Outward:** deleting Discord messages (not recoverable; `channel_cleanup_service.py:318`,
with a safety cap of 50), ~411 send/edit sites, donation broadcasts, heartbeat GET to a
freely configurable URL (HTTPS enforced, `docker_control.py:3596`), translation APIs with an
SSRF allowlist, opengsq queries to arbitrary game servers.

---

## 6. Where something silently disappears

This is the stock for stage 2.

- **25 bare `except:`** in `cogs/docker_control.py` (17) and `cogs/status_info_integration.py` (8);
  **33 in the entire project** (plus 7 in `services/`, 1 in `utils/`, 0 in `app/`).
  *Correction 2026-09-16:* This said 18. The number was never counted. While correcting it I
  first gave it as 26, miscounting my own freshly generated list — what counts
  is the count, not the estimate.
  *Sorted by effect, not by file* (all 25 reviewed on 2026-09-16):
  **23 are breadth, not behaviour.** They sit around Discord interactions (`followup`, `edit`,
  `delete`) and end in `pass` or `return`; the comments all say the same thing —
  "Interaction already expired". That is intended design: Discord interactions expire after three
  seconds, nothing can be salvaged there. The only thing wrong is that `except:` also catches `KeyboardInterrupt`
  and `SystemExit`. Cheap to fix, no behavioural risk.
  **2 are substantive** — and under the rule "unnoticed beats rare" both explicitly move
  **down**, because they are visible:
  `docker_control.py:2198` wraps not only the send but also `view.message = …` and
  `asyncio.create_task(…)`, i.e. lines **after** the successful send. If one of them raises
  (`create_task` raises `RuntimeError` without a running loop), the donation message is already
  out and the fallback path sends a **second** one after it; the bare `except:` also catches
  `CancelledError`, i.e. during shutdown as well. `:2252` has the same shape, but a more narrowly
  scoped `try` — there the fallback fails too, and the error shows up visibly in the log.
  Two of them delete Discord messages (`docker_control.py:4966`, `:4976`) — an
  irreversible operation inside a catch-all. **[read]**
- **`docker_control.py:3289-3290`** — `except: donations_disabled = False`. **Fails open.**
  In addition, `_handle_donate_interaction` exists **twice** (`:2204` and `:3268`); the second
  overrides the first. The dead version checked the key via `is_donations_disabled()`
  (with validation), the live one only checks at `:3288` whether anything is set at all. **[verified]**
- **`docker_control.py:331-334`** — on a ConfigService error, the configuration from process start
  is silently passed on, including stale channel permissions and admin list.
- **`docker_control.py:1490-1492`** — `finally: self.initial_messages_sent = True`. Even a
  completely failed startup run sets the done flag.
- **`control_ui.py:281-283`** — if the spam protection fails, the action is **executed
  anyway**, just without a cooldown entry.
- **`control_ui.py:604-608`** — the entire Docker action inside a catch-all: the user sees
  "Pending", then "Processing…" and never learns that start/stop failed.
- **`status_info_integration.py:616-644`** — validation and Docker errors are **returned as
  log text** and shown in the log embed; an error cannot be distinguished from
  content.
- **`status_info_integration.py:2461-2480`** — `should_show_info_in_status_channel` computes
  `has_control` and then unconditionally returns `True`. The check is dead.
- **`control_ui.py:932-941`** — `_channel_has_info_permission` **always** returns `True`.
- **The click lock largely does not work:** `getattr(self, f'_last_click_{user_id}', 0)`
  stores on the *button instance* (`control_ui.py:1416, 2093, 2292, 2390, 2520`), and these
  objects are recreated on every render.
- **`event_manager.py:78`** catches **only `RuntimeError`**. Any other exception from a handler
  aborts `emit_event` and **all handlers registered after it no longer run**. Dispatch
  is synchronous on the caller's thread, without locks, without ordering protection — and
  `mech_status_cache_service.py:365` emits another event from within a handler. **[verified]**

---

## 7. The same rule in two places

27 cases were named; the most consequential:

1. **Donation broadcast twice** (`docker_control.py:4889-4946` and `:5131-5181`) — only the second
   respects `donation_broadcasts`.
2. **Task delete button twice** — `control_ui.py:1236` (checks `schedule`) and
   `status_info_integration.py:2567` (checks nothing).
3. **Two contradicting freshness rules:** `STATUS_CACHE_MAX_RENDER_AGE_SECONDS = 60`
   (`docker_control.py:72`) versus `DDC_DOCKER_MAX_CACHE_AGE = 300` (`:2476`, `:2865`, `:3057`).
   A 90-second-old entry is "old enough to reload" but "fresh enough to display".
4. **Server order implemented in four ways**; **mech speed three times**;
   **expiry of the pending marker (120 s) three times** (`:2510`, `:2899`, `:3091`).
5. `_validate_custom_address` is **identical** in `control_ui.py:1173` and `status_info_integration.py:1016`;
   so is `_get_container_logs` in `status_info_integration.py:608` and `:777`.

As a counterexample: the player-count formatting *is* centralised
(`services/discord/embed_helper_service.py:21,34`) and is used in three places. So it can be done.

---

## 8. Runtime, delivery, CI

- **The image has no `USER`.** The process starts as **root** and only drops privileges to `ddc` in the
  entrypoint via `su-exec` (`scripts/entrypoint.sh:624`). `PUID=0` is allowed and
  only produces a warning. **[verified]**
- **The Docker socket is documented contradictorily:** `docker-compose.yml:14` says `:ro`, the
  Unraid template `Mode="rw"`, `docs/UNRAID.md` "READ/WRITE required", `scripts/rebuild.sh:127`
  (the actual delivery path) mounts rw. Note: `:ro` on a Unix socket is
  not a protection boundary for the Docker API anyway — `docs/SECURITY_WIKI.md:137` overstates this.
- **CI has no test gate.** Nowhere in `.github/` is there `--cov-fail-under`.
  `tests.yml:80` and `:127` end in `|| true`, `:131` and `:190` set `continue-on-error: true`.
  **`docker-publish.yml` runs no tests at all** — images are published without any test
  check. `pytest.ini:47-50` prescribes that full runs "should" append `--cov-fail-under=50`;
  nothing does. **[verified]**
- **Only `scripts/ddc_test.sh` is safe.** Throwaway container, empty temp directories over
  `config/` and `logs/`, memory/PID/CPU limits, timeout, `-u ddc`. **All other runners
  touch production:** `run_tests_docker.sh` and `test_in_docker.sh` run `docker exec` into
  the **running production container** and install pip packages there;
  `install_pytest_docker.sh:47` falls back to `--user root` in the process; `run_tests_unraid.sh` runs
  directly on the host against the real `./config`; `test_container_save.sh` does `git pull` +
  `rebuild.sh`. **[read]**
- **`scripts/` writes configuration non-atomically throughout**, without a backup. In particular:
  `scripts/test_order_change.py` carries a **hard-coded Mac path**
  (`/Volumes/appdata/dockerdiscordcontrol/config/containers`) and writes real data there
  (`:45-48`). `encrypt_mech_images.py:96` deletes original graphics before the dependent write
  at `:251` is known to have succeeded. **[verified for `test_order_change.py`]**

---

## 9. The frontend

34 own files (5 JS + 28 templates + 1 third-party library), all read.

- **Five destructive endpoints have not a single caller in the frontend:**
  `POST /api/donation/reset-power`, `POST /api/mech/reset`, `POST /api/donation/add-power`,
  `POST /clear-action-log`, `POST /clear_logs`. They can only be reached by direct HTTP.
- **The interface reports a success that does not exist.** The red "Clear" button calls
  `window.clearLogs` (`_scripts.html:1836-1862`): it asks for confirmation, clears **only the DOM** and shows
  "`${logType} logs cleared successfully`". **No** request is ever sent. The comment at
  `:1844` admits it — "can be updated when backend endpoint is available". The endpoint exists.
  That is "a success is guessed" in its purest form. **[verified]**
- **Admin rights change without confirmation** (`config-ui.js:707`/`:728`): one click revokes
  a user's admin role, saving makes it permanent.
- **The difficulty level saves while sliding** (`_advanced_settings_modal.html:749`,
  `:785-803`) — without a save step, without confirmation.
- **`GET /api/migration-help`** writes the **decrypted bot token** into the DOM
  (`security_service.py:175`). That is **intended** and behind login — the purpose is the move
  to an environment variable. Belongs in the deliberate decisions, with a risk note. **[verified]**
- **CSRF is solved cleanly** (`_base.html:44-103` overrides `window.fetch`), with one gap:
  `tasks/form.html` as a standalone page does not inherit `_base.html`, therefore sends no token and
  is rejected by the server.
- `app/static/js/main.js` is a **fragment without a function start** and is not loaded by any
  template.

---

## 10. Deliberate decisions

There are more of these than expected, and many are well justified — the pleasant surprise of this
inventory. In stage 1 they belong in the SPEC, otherwise the next refactoring will scrap them.

- **`SESSION_COOKIE_SECURE` stays `False`** (`app/web/config.py:36`): "most installs are plain HTTP
  on the LAN". `SameSite=Lax` instead of `Strict` (`:39`), so that a link from Discord does not break the
  session in the other tab.
- **The login cache** (`app/auth.py:23-42`): 85.6 ms per request measured; only *already
  verified* credentials are stored, the key contains the password hash so that a
  password change makes all entries unreachable immediately. Carefully thought through and written down.
- **CSRF must not fail quietly** (`app/web/csrf.py:112`).
- **A single `NotFound` does not hide a container permanently**
  (`container_status_service.py:504`) — during an Unraid auto-update it is removed and
  recreated.
- **Donations are never hard-deleted**, but via a compensation event
  (`progress_service.py:1525`), with a lock against the stale double click
  (`donation_management_service.py:299`). The best-built spot in the project — and of all things
  the reset next to it lacks this care.
- **Stop/restart are never sent a second time after a timeout** (`scheduler.py:1812`).
- **An empty token field means "keep", never "delete"** (`config_form_parser_service.py:439`).
- **Game-query verdicts** are written individually via read-modify-write
  (`game_query_support_service.py:226,246`); a slowly starting server gets a fresh
  15-minute window (`:177`).
- **Time zone in the logger deliberately not via `utils.time_utils`** (`logging_utils.py:165`), because that
  function writes.
- **The control channel *is* the admin boundary** (confirmed by the operator, 2026-09-16). Whoever may write in a
  control channel may control. Access control lies with Discord, not with DDC.
  The comment in `docker_control.py:2028` ("Control channels are already restricted to admins by
  design") therefore correctly describes the intent — it just was not recorded anywhere before.
- **Without justification:** spam protection on the toggle button "intentionally removed" (`control_ui.py:655`).

---

## 11. The most serious findings, by "does the user notice?"

| # | Finding | Why at the top |
|---|---|---|
| 1 | Test suite can destroy the real `config/` (`mech_reset_service.py:42-45` + `test_mech_data_services.py:944`) | data loss while testing; only the mount in `ddc_test.sh` prevents it |
| 2 | Any Discord user books arbitrary amounts into the ledger (`docker_control.py:4731`) | wrong information about real money, completely silent |
| 3 | Failed booking → thank-you message goes out anyway (`:4885-4887` → `:4939`) | "a success is guessed", publicly |
| 4 | UI reports deleted logs without asking the server (`_scripts.html:1836-1862`) | the user believes data is gone |
| 5 | ~~Container control is bound to the channel, not to the user~~ | **Withdrawn 2026-09-16** — confirmed by the operator as intended, see section 4. Belongs in the SPEC, not in the bug list. |
| 6 | `/addadmin` creates a right that outlives the channel (`:2026-2029` → `admins.json`) | no contradiction to the channel model, but `control_ui.py:998` uses it to bypass the channel check. **Design question for the operator, see question 1.** |
| 7 | Donation reset truncates the event log without a backup (`reset.py:96`) | **confirmed: real data loss** — according to the operator the ledger is the only truth of the local instance |
| 8 | CI publishes images without any test check (`docker-publish.yml`) | the test run has no consequences |
| 9 | `dataclasses.dataclass` replaced process-wide (6 test files) | the tests do not check the classes that are shipped |
| 10 | Task deletion unchecked (`status_info_integration.py:2567`) | the same rule, forgotten in one place |

---

## 12. What was NOT checked

This section is the most important one, and it is deliberately uncomfortable.

**Not executed, only read:**
- The cross-check from stage 3 — *revert a fix and see whether the test turns red* — was done for
  **not a single** test. Stage 0 forbids code changes. **All statements about
  "would fail" are read from the check text, not measured.**
- The isolation experiment covered **one** pair of files. 111 other files were not checked individually
  against the group run.

**Not looked at at all:**
- `app/static/vendor/bootstrap/js/bootstrap.bundle.min.js` (minified, third-party code).
- The workflows `dependency-checks.yml` and `dockerhub-readme-sync.yml`.
- Seven diagnostic scripts were classified as write-free only by grep, not read.
- `config/` itself — not readable over SMB (mode 700); on the host only checked for file names.

**Only partially looked at:**
- `services/` was **not read systematically** — 60,800 lines, the largest logic block of the
  project. Findings from it come from targeted searches, not from a pass.
- `cogs/scheduler_commands.py`, `cogs/admin_overview.py`, `cogs/enhanced_info_modal_simple.py`
  were not read completely (the three large cogs, by contrast, were).
- Of ~411 Discord send/edit sites, only the deletions and donation paths were fully
  covered.

**Methodologically open:**
- The tool found the category "mock tautology" only where a literal was set directly as
  `return_value`. Tautologies via variables or fixtures remain undetected.
- **The measuring instrument itself had a gap — found because a prediction did not hold.**
  In the full run of 2026-09-16 (`b0hu3ug8w`), `tests/unit/services/mech` left an
  **empty** entry: `rc=0`, but no summary line. My evaluation summed the
  missing line as **zero tests**; 4,506 green silently became 4,059, and nothing raised an alarm.
  It was noticed only because the number had been announced **before** the run and the deviation
  was 444 instead of the expected 3. Without this prediction it would have slipped through.
  *Checked what caused it — not the runner:* `scripts/ddc_test.sh` passes through pytest's
  return code (`:90`, `:97`, `:101`), and two probes prove it: a path that does not exist
  yields `rc=4`, a filter that matches nothing yields `rc=5`. **The tool cannot report success
  without having tested** — the green results of this session stand. The gap was in my
  evaluation loop, which could not distinguish "no output" from "no tests".
  *Fixed* in the session's watchdog run wrapper (not part of the repository): `rc=0` without a result line now counts as a **missing measurement**
  and is logged together with the raw output, instead of silently counting as zero.
  *Open and no longer resolvable:* The raw output of that pass is gone. Whether the
  transmission or the capture lost the line at the time cannot be determined after the fact.
- That 4,506 individual tests are green in a full run says nothing about the 362 hollow
  test functions — and nothing about whether the remaining 3,600 check the *right* things.
  *Correction 2026-09-16:* This said 4,492, 356 and 3,563. The 3,563 was moreover a
  category error: a run counts test **executions** including parametrisation, the census
  counts test **functions** in the source. Subtracting one number from the other yields nothing.

---

## 13. Questions for the operator

These are not technical and must not be decided by the developer.

1. ~~Are control channels restricted to admins?~~ **Answered 2026-09-16:** Yes — a control channel
   makes all its members admins; that is the intended model. **Follow-up question, still open:**
   Should the right granted via `/addadmin` *outlive* the channel (today it does, including the
   bypass of the channel check in `control_ui.py:998`), or should authorization follow exclusively from
   current channel membership? — **Answered 2026-09-16: it should stay that way.** `/addadmin`
   is aimed primarily at the status channel. **New open question in its place:** `/donate` has no
   channel check at all, so the donation ledger is writable from anywhere (section 4).
2. ~~Is the ledger the only record of the donations?~~ **Answered 2026-09-16:** Yes, for
   the local instance it is the only truth. Finding 7 is therefore real data loss.
3. **Five web addresses do something, but no button in the panel calls them** (section 9). They are
   reachable only if someone makes the request by hand (logged in, e.g. via `curl`) — or
   if a script hits them by accident. Two of them are the most destructive operations of the
   program altogether:

   | Address | Effect |
   |---|---|
   | `POST /api/donation/reset-power` | **deletes the entire donation ledger** |
   | `POST /api/mech/reset` | resets the mech to level 1 (also deleting the ledger) |
   | `POST /api/donation/add-power` | credits a donation |
   | `POST /clear-action-log` | clears the action log |
   | `POST /clear_logs` | does nothing (the dummy from section 9) |

   **Decided 2026-09-16: remove.** Scope and timing will be set at the transition to stage 2;
   the command-line path (`scripts/reset_mech.py`) remains untouched.
4. ~~May an invited user in the control channel stop containers?~~ **Answered 2026-09-16:**
   Yes — every user in the control channel may do everything.

---

## 14. First correction — six endpoints without callers removed (2026-09-16)

At the operator's decision, carried out **before** stage 1. Not yet committed.

**Removed**, because no button and no JavaScript ever called them, yet some of them could
wipe the donation ledger:

| Endpoint | File |
|---|---|
| `POST /api/donation/reset-power` | `app/blueprints/main_routes.py` |
| `POST /api/mech/reset` | `app/blueprints/main_routes.py` |
| `POST /api/donation/add-power` | `app/blueprints/main_routes.py` |
| `POST /api/donation/consume-power` | `app/blueprints/main_routes.py` |
| `POST /clear-action-log` | `app/blueprints/action_log_routes.py` |
| `POST /clear_logs` | `app/blueprints/log_routes.py` |

Removed along with them: the dummy `ContainerLogService.clear_logs` together with `ClearLogRequest`, the
"Clear" button and its **false success message** (`_scripts.html`, `window.clearLogs` reported
"logs cleared successfully" without ever asking the server), the dead `clearActionLogBtn` and the
dead `consumePower` function in `config.html`.

**Re-measured, not claimed:**
- Routes: `main_routes.py` 38 → 34, `log_routes.py` 8 → 7, `action_log_routes.py` 3 → 2.
- No removed symbol survives anywhere (AST check + untruncated full-text search).
- Suite: **4,464 green, 0 failures**, no group with an error code (previously 4,492).
- The difference of 28 corresponds exactly to the deliberately removed test functions — no test
  disappeared unnoticed.
- 918 lines removed, 3 added, 12 files.

**Deliberately NOT touched** (follow-up findings for stage 2, otherwise a reviewable change grows into
an unreviewable one):
- `show_clear_logs_button` (`configuration_page_service.py:539`) — configuration key without
  effect; removing it touches the schema and five tests.
- `ConsumePowerLogFilter` (`app/web/logging.py:34,58`) — filters log noise of a route that no longer
  exists.
- `_get_cached_mech_state` (`main_routes.py:27`) — has its own tests, but since this cut
  **no caller anymore** in production.
- Two outdated comments (`_scripts.html:567`, `test_other_routes.py:1379`).
- The import `log_user_action` in `action_log_routes.py` stays unused: a test fixture
  (`test_other_routes.py:1380`) sets it via `monkeypatch`; a "clean-up" would have broken it.

### What went wrong in the process, and why it belongs here

I first determined the list of affected tests with a search truncated to `head -40`
— and acted on it. Three test blocks were missing from it (`test_blueprint_gaps.py` did not
appear at all). The untruncated search afterwards found two more. **The same mistake twice in one
day: what was not on the list was not checked** — once with the 18 forgotten
test files, once here. That is exactly the finding for which stage 4 plans the contract test over the
split, and the best available evidence that it is needed.

---

## Appendix: tools and repeatability

**AST census:** `audit_tests.py` (currently in the session's working directory, not in the repository).
Classifies every test function mechanically. Counted as checks are `assert`, `pytest.raises`,
`mock.assert_*`, `pytest.fail()`/`self.fail()`, `raise AssertionError` and helper functions whose
name starts with `assert`/`verify`/`expect`/`check_`. A test counts as hollow only if **all**
of its checks are hollow.

**Suite run:** `DDC_TEST_HOST=unraid scripts/ddc_test.sh <group>` — one group per call
(several groups make `tests/unit/services/` shadow the real package, see the comment in the script).
Run: 24 groups + 18 individual files.

**Caution, experienced first-hand:** My first group list **missed 18 test files** — the four
directly in `tests/unit/services/` and the 14 in `tests/`. They were on no list and would have
remained unchecked. Exactly the effect that stage 4 is meant to prevent with the contract test over the
split. This experience is the best evidence that this contract test is needed.
