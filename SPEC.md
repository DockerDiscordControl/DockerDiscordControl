# SPEC — what DDC guarantees

**As of:** 2026-09-19 · **Status: confirmed.**

The operator confirmed all ten guarantees **point by point on 2026-09-19**, unchanged. Before that
the list stood only as *presented*: the operator had decided individual questions (Z4: browser
token; Z5: old admin panels lose their effect immediately; Z10: full gate, group by group), not
the list. The same day decided the two open side questions: the scheduler exception under Z5 is
intended (B12), and Z7 applies to the application code, not to `scripts/` (B13).

Without a yardstick, a review is only opinion. This file records what DDC promises — so that a
behaviour can be *refuted* instead of argued about as a matter of taste.

A guarantee states in one sentence what must **never** happen or must **always** hold; it can be
refuted, and it means something to the user — not only to the developer.

The basis is the inventory in [`docs/quality/STAGE0_INVENTORY.md`](docs/quality/STAGE0_INVENTORY.md).
The **Today** column is deliberately uncomfortable: several of these guarantees are currently broken.

---

## Guarantees

### Z1 — The donation ledger is never lost without a backup.
No operation empties or overwrites the event log without first creating a restorable copy — not
even when the operator triggers the operation themselves.

*Broken if:* after a reset, no file exists any more from which the previous state can be
restored.
*Why it matters:* the ledger is the only record of the real donations of this instance.
**Today: fixed (2026-09-16).** Previously `reset.py:96` wrote `""` into the log with no
replacement. Now `_backup_before_reset()`, before deleting and within the same lock, creates a copy
of the event log, sequence counter and snapshots under `<data_dir>/backup_<timestamp>/` — the same
convention that `scripts/reset_donations.sh:32-44` already used. If the backup fails, **the reset
aborts** instead of merely warning. Two resets produce two backups, not one overwritten one.
*Covered by* `tests/spec/test_z1_donation_ledger_backup.py`.
*Counter-check:* before, all 3 tests red, each on its own guarantee; afterwards green;
full run 4,470 green, 0 failures.

### Z2 — A test run never touches production data.
No test writes to the real `config/`, regardless of which runner starts it and regardless of
whether `DDC_CONFIG_DIR` is set.

*Broken if:* after a test run, a file under `config/` has been changed or deleted.
**Today: fixed (2026-09-16).** Previously `MechResetService` resolved `config_dir="config"` against
the project root and ignored `DDC_CONFIG_DIR`; `test_mech_data_services.py:944` calls
`quick_mech_reset()` for real, and only the empty mount in `scripts/ddc_test.sh` prevented the
damage. Now the default case follows the same rule as `config_service.py:181` and
`progress_service.py:561`. An explicitly passed path behaves unchanged.
*Covered by* `tests/spec/test_z2_config_isolation.py`.
*Counter-check:* before the fix 2 of the 3 tests red, afterwards 3 green; full run 4,467 green,
0 failures.

### Z3 — No success is reported that did not happen.
When the interface says "done", the server has confirmed the operation. A half-executed operation
is never presented as completed.

*Broken if:* a success message appears without a request having been made, or although the
response reported a failure.
**Today: fixed for the two known cases (2026-09-16).** The "Clear" button reported success
without any request — removed. The donation broadcast sent a thank-you message even when the
booking had thrown (`:4885-4887` caught the exception, execution fell through into the broadcast)
or when, for lack of a booking service, nothing was booked at all (`:4789`). Now an explicit
`donation_booked` decides, and when the booking did not happen the user gets an honest message
instead of "Donation broadcast sent!".
*Covered by* `tests/spec/test_z3_z8_donation_broadcast.py`.
*Counter-check:* two false starts in the test scaffolding (red for the wrong reason; the test was
what got corrected); then a legitimate red on all three guarantees; the **first fix was incomplete**
and the test showed it (`{100: 1, 200: 0}`) — the lock depended on `donation_amount_euros`, which is
only assigned in the skipped block. Full run **4,478 green, 0 failures**.
*Found and fixed along the way:* An unconditional access to a possibly unassigned `new_state` made
the callback crash with `UnboundLocalError` in the "donation without amount" case — caught by
neither `except` block, so the user saw "Processing…" permanently and the support message never
went out. Three places affected, all switched to `new_evolution_level`. *Counter-check:* before
1 red / 14 green, afterwards 15 green.

### Z4 — Money is never credited twice or without evidence.
Every donation carries an idempotency key that does not depend on the clock time. The same donation
twice produces one entry, not two.

*Broken if:* two identical bookings at the same moment produce two entries.
**Today: fixed (2026-09-16).** The finding was a pass-through error, not a missing mechanism:
`ProgressService.add_donation` had supported idempotency for a long time and was tested for it
(`test_progress_service.py:322`) — the key was merely lost between the entry point and the service,
whereupon `progress_service.py:1024` fell back to `donor|amount|utcnow()`.

Now `DonationRequest` carries a field for it, and the key runs through all five layers
(`models` → `processors` → `mech_service_adapter` → `progress_service`). The entry points supply
it: Discord uses `interaction.id` (`docker_control.py:4822`); the browser generates a token on the
first submit and lets it expire only after a **confirmed** booking — a retry after the 30-second
abort therefore carries the same token, whereas a reload carries a new one, because that is a real
second donation.

*Decided by the operator:* browser token instead of a time window over (donor, amount) — a window
would have swallowed a real quick second donation and thus lost real money.
*Note:* `crypto.randomUUID` exists only in a secure context; since DDC deliberately runs as plain
HTTP (B3), the generation has a fallback path — without it no token would be created at all.

*Covered by* `tests/spec/test_z4_donation_idempotency.py` (3 service tests + 2 contracts on the
interface, because a pure backend pass-through does not fulfil the guarantee in everyday use).
*Counter-check:* service tests before: `TypeError` (the mechanism was missing) — an honest but weak
red. The two contract tests were at first red for the **wrong** reason (an error in the test
itself); after correcting them the counter-check was properly redone: token in the frontend
disabled → exactly these two red, restored → all green. Full run **4,475 green, 0 failures**.
*Found along the way:* `FakeMechService` in `tests/test_unified_donation_service.py` pinned down
the old signature — fixed as well.

### Z5 — No action on a container without channel permission and an allowed action.
Start, stop and restart happen only if the channel holds the permission **and** the container
allows the action — on **every** path: button, schedule, automation rule, web panel.

*Broken if:* a path exists that touches a container without passing both checks.
*Note:* authorization via the **channel** is intended (see Deliberate decisions B1). This guarantee
does not demand a user check — it demands that the channel check is **complete**.
*Clarified 2026-09-19 (operator):* "channel permission" includes **B2** — a user in the CURRENT
admin list may act where the channel alone permits nothing (the status channels). The Z5 fix of
2026-09-16/17 removed the "Admin Control" message title as a permission but put nothing in its
place; that title had been the only way admins got through in status channels, so the operator —
a registered admin — was refused there. Restored on every path the fix had touched (start/stop/
restart, the info admin view, both task delete buttons). The admin list is read at the moment of
the press, never from a message, so an old title still grants nothing to a non-admin.
*Covered by* `tests/spec/test_z5_admins_act_in_status_channels.py`.
**Today: fixed (2026-09-16).** The side question about the scheduler exception was decided on
2026-09-19: intended, recorded as B12.
The way there belongs here, because the original version of this line was too coarse and was
refuted on re-reading:

- *"Four places bypass the channel permission"* — partly refuted, **partly cleared wrongly.**
  `:429` only controls the redrawing of the admin message (`:483`). The flag set there,
  `_is_admin_control` (`:487`, removed at `:531`), is read in exactly two places
  (`status_handlers.py:1051`, `status_info_integration.py:1143`) and there, too, only suppresses
  display — the permission still comes unchanged from `_channel_has_permission` (`status_handlers.py:1040`).
- *What remains is **one** load-bearing place:* `control_ui.py:304` — `is_admin_control or <channel permission>`.
  It is redundant as long as the panel sits in a control channel (`/control` already checks the
  permission, `docker_control.py:1947`). It becomes a gap only when **the message outlives the
  permission**: panel posted, control permission revoked afterwards, panel remains usable.
- *The scheduler exception is **documented as intended***, not forgotten:
  `scheduler.py:1791-1794` — "Web UI tasks are admin tasks and always run (R4-1)". It belongs under
  **Deliberate decisions**, unless the operator objects.

**Decided 2026-09-16 (operator): (a)** — if a channel loses its `control` permission, old admin
panels **lose their effect immediately**. A permission must not reside in a message that can be
months old. `control_ui.py:304` is therefore a finding: the title heuristic is dropped at this
place, and the button checks only the **current** channel permission.
The purely presentational use at `:429` remains untouched — it grants no permission.

**Addendum 2026-09-17 — a second path, and a wrong classification from yesterday.**
Above it said that `control_ui.py:1019-1025` and `:1072-1079` were "purely presentational". **That
was wrong.** Both computed `has_control = is_admin_control or <channel permission>` and used it to
decide whether `ContainerInfoAdminView` is built. This view attaches `TaskManagementButton`
**unconditionally** (`status_info_integration.py:55`), and from there a path leads via
`TaskManagementView` → `DeleteTasksButton` → `ContainerTaskDeleteButton` to `delete_task()` —
**four levels, not a single permission check**. An old message title was therefore enough to be
able to delete scheduled tasks.
The comment at `:1053` even said so openly: "Don't re-check channel permission as it would
ignore admin control context."

*Second finding at the same place:* the same action required a different permission depending on
the path. `control_ui.py:1276` checks `schedule`; `status_info_integration.py` did not know the
string `'schedule'` at all. Anyone who had `control` but deliberately **not** `schedule` could
still delete via the second path.

*Fixed:* Both places now decide only by the **current** channel permission (like `:304` since
yesterday), the lines that became dead there are removed, and `ContainerTaskDeleteButton` checks
`schedule` like its twin.
*Covered by* `tests/spec/test_z5_task_delete_path.py` (3 tests).
*Counter-check:* 2 red as predicted, both for the right reason — the stack showed that the view was
built with `control: False` purely because of the title. After the fix 3 green,
`test_z5_channel_permission.py` unchanged at 3, `tests/unit/cogs` unchanged at 267.

*Checked and this time confirmed:* The flag `_is_admin_control` (`:496`, `:540`, `:1988`,
`:2034`) is read in two places (`status_handlers.py:1051`,
`status_info_integration.py:1143`) and there suppresses **only display**. Here the classification holds.

*Also checked and delimited:* The two web paths to `delete_task`
(`app/blueprints/tasks_bp.py:194`, `services/web/task_management_service.py:817`) depend on
`@auth.login_required`. The panel has its own permission model, not the channel model — not part
of this finding.
**Status: fixed (2026-09-16).** `control_ui.py:304` now reads only the current channel permission.
*Covered by* `tests/spec/test_z5_channel_permission.py`.
*Counter-check:* The red turned out **stronger than predicted** — I had expected a failure at
`pending_actions == {}`; in fact the tripwire at `:332` already snapped, and the log showed
`[ACTION_BTN] STOP action for 'nginx' triggered by Somebody`: without channel permission, purely
because of the title, the action was not merely queued but in full progress. After the fix
21 green, `tests/unit/cogs` unchanged at 267 green, full run **4,485 green, 0 failures**.
*Tightened afterwards:* A test that previously failed via a tripwire can be green afterwards because
the wire no longer snaps — not because the guarantee holds. The rejection text is therefore pinned
down; a mere `assert_awaited()` would also have been satisfied by the "no channel" path (`:294`).

*Not covered:* The scheduler path. `scheduler.py:1791-1794` explicitly exempts web panel tasks
from re-checking ("Web UI tasks are admin tasks and always run (R4-1)"). That is a documented
decision, not a gap. **Confirmed by the operator on 2026-09-19** and recorded as B12.

### Z6 — DDC never removes or destroys a container.
There are exactly three actions: `start`, `stop`, `restart`. No `kill`, no `remove`, no `prune`.

*Broken if:* any path triggers a different Docker action.
**Today: holds — and has been pinned down since 2026-09-16.** Two implementations, both limited to
these three (`docker_action_service.py:90-94`, `docker_utils.py:626-631`).
*Covered by* `tests/spec/test_z6_docker_actions.py`: both action lists, plus a project-wide search
for destructive calls (`container.remove()` and relatives) — it checks the **call site**, not just
the function.
*Counter-check, different in this case:* The guarantee holds, so there is no bug to revert. All
four tests were green immediately — which makes them suspicious. As a counterweight, a separate
test proves that the search pattern matches at all. That was necessary: the first version skipped
precisely `container.remove()` and could not fail for the most important case; a second place
contained `assert ... is None or True`. Both found while cross-reading, not in the run.

### Z7 — A configuration survives every write.
Every write to configuration or state files is atomic (temp file + rename). A crash in the middle
of a write leaves the old file intact.

*Broken if:* an abort during the write leaves an empty or truncated file behind.
**Today: all five places in the application code fixed (2026-09-16).** The scripts in `scripts/`
are excluded — that is an open question to you, see the end of this section.

*Fixed:* `progress_service.py:264` — the sequence counter of the donation ledger. The most serious
of the five: an abort left the file not stale but **empty** (`open(..., "w")` truncates on open),
`next_seq()` then read `int("" or 0)` and started again at 1 — in the middle of an event log in
which these numbers are already taken. Now goes through the new shared helper `utils/atomic_io.py`.
*Covered by* `tests/spec/test_z7_atomic_writes.py`.
*Counter-check:* before `assert '' == '5'`, afterwards 18 green; full run **4,482 green, 0 failures**.

*Also fixed:* `container_status_service.py:153` — the container configuration maintained by the
user (display name, allowed actions, order). An abort left it **completely empty**, and in an
operation that the user never triggers and never sees: the automatic deactivation when Docker
reports a container as permanently absent.
*Covered by* `tests/spec/test_z7_container_config_write.py`.
*Counter-check:* before `assert ''`, afterwards green; full run **4,497 green**, 2 red (Z10 only).

*The most instructive find of the day along the way:* `tests/unit/extended/test_docker_infra_gaps.py`
was supposed to check the same error path and had always been green — but its `_bad_open` threw on
**every** access, i.e. already on **reading**, long before the write. The method returned `False`,
the assertion was satisfied, the write path was never reached. The first repair attempt
(also patching `os.fdopen`) had no effect; that was only proven by a **mutation**: with a helper
that swallows all write errors, it stayed green while the new test turned red. Only the second
version — letting only write accesses fail — demonstrably takes effect.
**In general:** A green test says nothing about whether it takes effect. Of the 3,962 legacy tests,
exactly one was checked this way, and it was broken. That belongs in stage 3.

*Also fixed:* `member_count/service.py:174` — the member count snapshot. Not a cosmetic loss: the
number flows into `requirement_for_level_and_bin()` and thereby determines what the next mech level
**costs**. An empty or half-written file shifts that silently while the display looks normal. It
was written via `Path.write_text`, which truncates on open.
*Covered by* `tests/spec/test_z7_member_count_write.py`.
*Counter-check:* This test was **worthless twice** before it proved anything — green both times.
Once the interception point lay *before* the damage (the stub threw before the file was
truncated), once the leftover check also counted unrelated files in the same directory. Only the
third version, which *reproduces* the damage instead of preventing it, turned red (`assert ''`).
Additionally proven by **mutation** that the test takes effect.

*Also fixed:* `mech_reset_service.py:194` — the mech state. What was lost there was not a counter
value but the **mapping**: `last_glvl_per_channel` and `mech_expanded_states` record which Discord
channel had which state. The method keeps this structure and only resets values — an abort during
the write destroyed it entirely.
*Covered by* `tests/spec/test_z7_mech_state_write.py`.
*Counter-check:* hit on the first attempt (`assert ''`), the guard did not trigger; proven by
mutation that the test takes effect. That it was right immediately this time was because the two
traps of the previous rounds had been named beforehand: interception point **after** the
truncation, and hit **only** write accesses.
*Checked as well:* `mech_reset_service.py:302` accesses the same file too — read-only, not a
Z7 case.

*Also fixed — the fifth of five:* `server_order.py:45` — the server order. The classification
"cosmetic" remains correct: the order can be set again at any time. The reason to do it anyway is a
different one — **the loss never reports itself**. `load_server_order()` catches the
`JSONDecodeError` and silently returns `[]` (:72-74); the display falls back to the default order
without an error message. The run logged exactly this chain: first `Error saving server
order`, then `Error loading server order: Expecting value: line 1 column 1` — and nothing after that.
What is checked is therefore not "the file has bytes" but the user-facing statement: after the
failed write, `load_server_order()` still returns the order that was set.
*Covered by* `tests/spec/test_z7_server_order_write.py`.
*Counter-check:* before the fix red on exactly this guarantee, both guards held. Additionally proven
by **mutation**: with an `atomic_write_text` that swallows errors instead of passing them on, the
test turns red (`assert True is False` — "A failed write must not count as success"); restored,
green again, without mutation leftovers.
*Also checked, nothing to follow up:* The seven existing tests in `test_coverage_push_v3.py:138-225`
redirect `ORDER_FILE` and work with real files; the only one that intercepts (`os.makedirs`, :182)
hits a place **before** the write and remains unaffected. Unlike with
`_deactivate_container`, no test had to be adjusted here.

*Decided on 2026-09-19 (operator): Z7 applies to the application code, not to the scripts — B13.*
The question as it was put: the scripts in `scripts/`. Counted, not
estimated: **33 write sites in 16 scripts** (one grep line was a false hit, `migrate_to_modular.sh:281`
only reads). Two of them touch the same files as the program — `migrate_to_modular.sh` writes
the complete configuration set, `reset_mech.sh` the donation ledger.
My proposal: **Z7 applies to the application code, not to the scripts.** They run once, triggered
by the operator, who watches while they run — the damage would be noticed, not go unnoticed. That
would be a deliberate decision instead of an open guarantee. (Written as "B11" at the time; B11 was
assigned to another decision first, so it became **B13**.)

*Found along the way while counting, two side findings on the reset scripts:*
1. `reset_mech.sh` looks dangerous — it writes `mech_donations.json` directly — **but it is
   not**: line 15 aborts with `exit 1`, all the code below it is unreachable. Checked,
   not a Z1 hole.
2. The same script refers in :3 and :12 to `scripts/safe_reset_mech.**py**`. What exists is
   `safe_reset_mech.**sh**`. Anyone following the instruction literally gets "No such file or directory".
   A string, not data loss — but the operator faces a dead end in a reset situation.

*Side finding:* There were already **two** helpers for atomic writing, and they differed —
`utils/token_security.py:25` preserves the file permissions and uses `os.replace`;
`services/config/channel_config_service.py:47` does neither and on Windows removes the target file
beforehand, which opens a window with no file. `utils/atomic_io.py` adopts the safe one of the
two. Merging the legacy helpers is a separate item, not part of this fix.

### Z8 — No silent failure on something irreversible.
If an action fails that cannot be undone — touching a container, deleting a file, sending a
message, booking money — the error becomes visible. Never just `except: pass`.

*Broken if:* such an error ends up only in the debug log, or nowhere at all.
**Today: fixed on the donation path (2026-09-16), otherwise still broken.** Fixed: a swallowed
booking error led to a thank-you message to all channels — see Z3.
~~**Still open:** 25 bare `except:` in `cogs/` (33 in the whole project)~~ — **measured on 2026-09-19:
0 bare `except:` left**; they were removed in `e93100a` (they also swallowed the cancellation
signal). The two message deletions named here (now `docker_control.py:5016`, `:5026`) only remove
a "processing" message after the result was shown — a failure leaves a stale message, nothing is
lost.

**The Z8 sweep of 2026-09-19**, counted with an AST scan of the application code: **107** handlers
whose body is only `pass`/`continue`, **119** that log only at DEBUG. Sorted by what their `try`
does, most are harmless: a fallback error reply to the user after the real error was already
logged, removing a temp file after a failed atomic write (the original error is re-raised),
parsing with a fallback value. **Found and fixed:** the web-panel donation announcement
(`check_donation_notifications`) — after the notification file was consumed, an `AttributeError`
was logged only at DEBUG, and any other exception type stopped the loop for good. *Covered by*
`tests/spec/test_z8_web_donation_announcement_is_not_lost_silently.py`.
**Still open:** `event_manager.py:78` catches only `RuntimeError` — any other exception in one
listener skips the remaining listeners. **Not read one by one:** the DEBUG-only handlers were sorted
by the calls in their `try` body, not each read in full. This guarantee is therefore **not**
fulfilled everywhere — recorded so that it is not considered done.

### Z9 — The bot token never lies on disk in plain text.
Not in `config.json`, not in its backup, not in logs.

*Broken if:* the decrypted token appears in a file.
**Today: holds** and is already tested (`tests/unit/audit_2026_09/test_pkg_c2_config.py`).
*Announced exception:* `GET /api/migration-help` deliberately returns the token over HTTP — see B5.

### Z10 — No image is shipped whose tests have not run green.
A published image has a complete, passed test run behind it.

*Broken if:* an image is published without the suite having run, or although it was red.
**Today: fixed (2026-09-17)** — after the operator decided for the **full gate in
group-by-group form**. The guarantee was broken when it was formulated, and more severely than
noted in the inventory.

*What was found* — four places, three of them test runs that **could not turn red**:

| Place | Kind | today |
|---|---|---|
| `tests.yml:67` "Run unit tests with coverage" | `\|\| true` | removed, runs group by group |
| `tests.yml:122` "Run integration tests" | `\|\| true` **and** `continue-on-error: true` | both removed |
| `code-quality.yml:295` "Run tests with coverage" | `continue-on-error: true` | removed, runs group by group |
| `docker-publish.yml` | ran no tests at all | own `test` job, `build_and_push` depends on it via `needs:` |

*And the actual finding, which only surfaced while fixing:* The safety switches did not hide red
tests — they hid that **no testing happened at all**. `pytest tests/unit/` aborts with
**79** collection errors, `pytest tests/` with **18**; in both cases not a single test runs. The
cause is package shadowing: `tests/unit/services`, `tests/unit/cogs` and
`tests/unit/utils` have no `__init__.py` but are named like the real packages. The `✅ Unit tests
completed` in the report was an `echo` behind a pytest that had long since died.
Had only the safety switches been removed, CI would have been **permanently red from then on** —
and a permanently red gate is as worthless as a permanently green one. All three calls therefore
now run group by group via `tests/GROUPS.txt`.
*Rejected, because measured:* `--import-mode=importlib` changes nothing; three retrofitted `__init__.py`
make it worse, from 18 to **54** errors (reverted). Restructuring the test layout would moreover be a
rebuild "so that it becomes testable", with no test waiting for it.

*Covered by* `tests/spec/test_z10_ci_test_gate.py` (6 tests) and `tests/spec/test_z10_group_list.py`
(3 tests). The second keeps the hand-maintained group list from drifting: **every test file is in
exactly one group** — otherwise a new file would silently never run, without anything turning red.

*Counter-check, in three stages:* The first version of the test found only the integration step — in
the unit test step, `pytest` is at `:73` and the `|| true` only at `:80`, separated by
line continuations. After splitting into `- name:` steps and extending to `continue-on-error`:
four findings instead of one, the fourth previously unknown.
After the gate was built, the test **triggered again**, four times — and all four times on
**comments** that had only just been written ("No `|| true` any more …"). The executable
code was clean. Instead of deleting the explanations, the detector was sharpened: whole comment
lines are not executed and therefore do not count. Because this looks like a loosening, the
sharpening carries its own **proof of effect** with four cases — among them the decisive
`pytest … || true  # looks harmless`, which must still trigger. Afterwards `tests/spec`:
**50 green, 0 red.**

**What is explicitly NOT proven by this:** What is checked is the text and the YAML structure of the
workflow files, not a real GitHub run. That the `test` job starts there and actually blocks
`build_and_push` will only be shown by the first push. These tests prove that the gate
**is in place** — not that GitHub executes it that way.

**Shown on 2026-09-19 — the first real runs on `develop`.** The gate bit twice before it went
green, both times on something that had been invisible:
- `b20f101`: red — 7 spec tests matched only the Python 3.14 wording of a `TypeError`; CI runs
  3.10. Fixed in `47ef54d`.
- `47ef54d`: red — the Bandit scan passed `--exclude` five times and Bandit keeps only the last,
  so it scanned `tests/`. The Unraid runtime has no Bandit, so there the scan skips. Fixed in
  `2b09986`.
- `2b09986`: **green**. All 43 groups ran (42 unit groups plus integration): 4,775 passed,
  1 skipped.
Still not shown: that the `test` job blocks `build_and_push` in `docker-publish.yml`. That
workflow runs only on `main` and on tags.

---

## Deliberate decisions

Things that look like a bug but are intended. Without this section, the next rebuild silently
throws them out.

**B1 — Authorization follows the Discord channel, not the user.**
Whoever may write in a control channel may do everything. Access control lies with Discord (who
may see the channel), not with DDC. *Confirmed by the operator on 2026-09-16.*
**Do not "fix"** this by adding user checks — that would break the model.

**B2 — The global admin list exists for the status channels.**
`/addadmin` writes to `admins.json`; this permission outlives channel membership. The purpose is
that admins may also do things where channel membership alone permits nothing.
*Confirmed by the operator on 2026-09-16.*

**B3 — `SESSION_COOKIE_SECURE` stays `False`.**
Most installations run as plain HTTP on the LAN, where a `Secure` cookie would never be sent
(`app/web/config.py:36`). `SameSite=Lax` instead of `Strict`, so that a link from Discord does not
break the session in the other tab (`:39`).

**B4 — Donations are never hard-deleted, but reversed by a counter-entry.**
`progress_service.py:1525` writes a compensation event; deleting is a toggle and therefore
reversible. In addition, `donation_management_service.py:299` blocks the stale double click.

**B5 — `GET /api/migration-help` returns the decrypted bot token.**
Intended, behind login; the purpose is the move to an environment variable
(`services/web/security_service.py:175`). *Announced risk:* the token ends up in the DOM and
thereby in the browser's history and developer tools.

*Addendum 2026-09-18:* Until today this risk **did not exist in practice** — the path was
unreachable. `migrate_to_environment_variable` read `self.config_manager`, an attribute that
`__init__` never sets; the `AttributeError` was caught, and the operator saw the raw Python text
instead of their token in the token window. With the repair (the operator's decision) B5 holds for
the first time as it is written here. Anyone who read the entry before took a risk for real that
was none — and conversely would never have learned that the function behind it was dead.

**B6 — Stop and restart are never sent a second time after a timeout.**
The first attempt may still be running (`services/scheduling/scheduler.py:1812`).

**B7 — A single `NotFound` does not hide a container permanently.**
During an Unraid auto-update, a container is removed and recreated
(`container_status_service.py:504`).

**B8 — An empty token field means "keep", never "delete".**
`services/config/config_form_parser_service.py:439`.

**B9 — The login cache stores only credentials that have already been verified.**
It does not lower the iteration count and helps no attacker; the key contains the
password hash, so a password change makes all entries unreachable immediately
(`app/auth.py:23-42`).

**B10 — It was an oversight. Restored on 2026-09-18.** The spam protection on the toggle button was
"intentionally removed", but a reason was stated nowhere — neither in the comment nor in the
commit message. The removed code (`0195074^`) was functional. Every other button in the same
file checks; this one was the only exception, although every press triggers a `message.edit` against
the Discord API — the button with the lowest threshold for use was the only one without a brake.

*Not simply reverted, but adapted to the house pattern:* The old code had an **untranslated**
message and caught `Exception`. What is used now is the existing catalog entry without an
`{action}` placeholder (`locales/*.json:1453`, already used four times in the code) and the narrow
exception catch `(RuntimeError, AttributeError, KeyError)`.

**Decided on 2026-09-19: "refresh into the panel".** `refresh` now has its own panel field
(default 5), `auto_refresh` is removed from the defaults. The original question was:
The key `refresh` has **no field in the
panel** — what is there is `live_refresh`, a different key. The cooldown is therefore fixed at
5 seconds and not configurable. That is exactly what was removed back then, but it contradicts
the principle "the panel decides". Should `refresh` get a panel field? The same question
arises for `auto_refresh`: likewise no field in the panel — and unlike `refresh`, it has
not a single consumer in the code even after this fix.

**B11 — A scheduled task keeps its permission even if the channel loses it.**
`ScheduledTask.__slots__` (`services/scheduling/scheduler.py:167-172`) has 21 fields, **none
channel-related** — only `created_by` with the user name. A renewed channel permission check at
execution time is therefore possible for **no** scheduled task, not only for the web UI exception.
If you revoke a channel's control permission, tasks created there earlier keep firing.
*Decided by the operator on 2026-09-18: record it, do not rebuild.* Whoever was allowed to create a
task keeps it; legacy tasks remain valid unchanged.

*So that the scope is not misjudged:* The slash-command mixin in
`cogs/scheduler_commands.py` is **dead code** — the extension list (`app/bot/startup_steps/
commands.py:26-30`) loads only `docker_control`, `auto_action_monitor` and `translation_monitor`, and
nothing references the mixin. The live path is the button at
`cogs/status_info_integration.py:2331` ("TASK_CREATE_BUTTON"). Scheduled tasks are therefore still
created from Discord — just through a different door than first assumed.

**Do not "fix"** this by retroactively carrying `channel_id` along without deciding that
beforehand: the data format would change, and legacy tasks without the field would need a rule of
their own (keep running or pause).

**B12 — Tasks created in the web panel run without a channel permission check.**
`services/scheduling/scheduler.py:1791-1794`: "Web UI tasks are admin tasks and always run (R4-1)".
Such a task does not come from a Discord channel but from the administrator logged in to the
panel, and the panel has its own permission model (the login, `@auth.login_required`). A channel
check would have no channel to check.
*Confirmed by the operator on 2026-09-19.* This is the documented exception to Z5, no longer an
open question.

**B13 — Z7 (atomic writes) applies to the application code, not to `scripts/`.**
The scripts are started by the operator, who watches while they run: a broken write would be
noticed, not go unnoticed. Counted on 2026-09-16: 33 non-atomic write sites in 16 scripts, two of
them on real data (`migrate_to_modular.sh`, `reset_mech.sh`).
*Decided by the operator on 2026-09-19.* The two side findings on `reset_mech.sh` (dead code after
`exit 1`, a reference to a non-existent `safe_reset_mech.py`) are not covered by this exemption.

---

## Rules of the quality programme

Not guarantees to the user, but rules for us — recorded here so that they do not get
lost:

- **R1 — A test without a refutable check counts as a defect.** Mechanically checkable with
  `scripts/audit_tests.py`.
- **R2 — For every guarantee at least one test exists**, recognisable by `# @covers Zn`, and a
  further test checks that no guarantee remains without a marker.
- **R3 — One finding, one commit, one full test run.**
- **R4 — Every fix carries its reason in the code:** not what it does, but what was wrong before.
- **R5 — Coverage is not a target metric.**

---

## To be decided

1. ~~Which of the ten guarantees apply?~~ **Decided on 2026-09-19: all ten, unchanged.**
2. ~~**B10:** Was there a reason for removing the spam protection on the toggle button?~~ **Answered
   on 2026-09-18: an oversight, restored.** ~~What remains open is only the value question — should
   `refresh` get a panel field?~~ **Decided on 2026-09-19: yes; `auto_refresh` removed.**
3. ~~Order for stage 2~~ — stage 2 has been carried out; every guarantee has a test (R2).
4. **Decided on 2026-09-19 — the plan from here:**
   - Z8 (known, confirmed, still broken) is worked off **before** the review, one finding per commit.
   - Stage 4 review: all 37 sections one pass each with a verdict on every name of the check plan,
     the most sensitive sections (money, permissions, deletion, token) three passes each.
   - The single-file run of every test file (stage 3, proposal 4) becomes a check before every
     release, not a CI job.
   - Splitting `DockerControlCog` is planned as a strand of its own **after** the review.
   - The state of `quality-programme` goes to `develop` now, after the operator has approved the
     merge summary.
