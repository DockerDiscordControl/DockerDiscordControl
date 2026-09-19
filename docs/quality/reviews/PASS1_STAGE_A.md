# Stage 4 review - pass 1, stage A (2026-09-19)

Eight sections, chosen by "would the user notice it": money (17, 18, 24),
permissions (01, 02, 31, 32), containers and deleting (14 - never touched
before). One pass each, reviewer model **Sonnet**, the code was written and
fixed by Opus. Commit reviewed: `6e19b2e`.

The reviewer got only its package (`scripts/review/build_package.py`, an
allow-list): the section's source with real line numbers, `SPEC.md`, the
section's check plan and `scripts/review/REVIEW_TASK.md`. Reports:
`section_NN_pass1.json`, the plan each was held against:
`section_NN_pass1.plan.txt`.

**One pass is a sample, not a review.** The programme text measured three
passes of the same reviewer over one section at 9, 10 and 7 findings with
pairwise overlap zero. Nothing below means "checked" beyond "looked at once".

## Coverage (scripts/review/coverage.py)

| Section | Names | Judged | Findings | of which "unsure" |
|---|---|---|---|---|
| 01 | 33 | 33 | 3 | 3 |
| 02 | 27 | 27 | 7 | 5 |
| 14 | 43 | 43 | 4 | 3 |
| 17 | 61 | 61 | 9 | 6 |
| 18 | 88 | 88 | 7 | 4 |
| 24 | 46 | 46 | 6 | 3 |
| 31 | 51 | 51 | 5 | 2 |
| 32 | 46 | 46 | 3 | 1 |
| **total** | **395** | **395** | **44** | **27** |

**The coverage calculation earned its keep on the first day.** Two of eight
reviewers (14 and 18) wrote bare names instead of `path:line name` and
reported "all names match the plan" - the calculation counted 0 of 43 and 0 of
88 as judged, and in section 18 a name that occurs several times was judged
once. Both reviewers were sent back and corrected their reports themselves;
nothing was repaired on their behalf.

## Every finding was re-checked against the code

Not one finding is adopted unchecked. Verdicts: **confirmed** (the trigger
holds), **partly** (the matter or the reasoning holds, not both), **refuted**,
**dead code** (holds, but nothing can reach it), **not re-checked** (low, see
the end).

### Confirmed - to be fixed, one finding per commit

| # | Report | What | Severity after re-check |
|---|---|---|---|
| A1 | 24 F1 | `add_donation` writes the event, then the snapshot. If the snapshot write fails, the donation is in the log but its effect on the mech is not, and nothing replays it (`load_snapshot` does not compare `last_event_seq` with the log). A retry with the same idempotency key is "already booked" and returns the old state. | high (rare trigger: failed atomic write) |
| A2 | 02 F3 | `ControlView.__init__` checks `pending_actions` with `display_name`; every other place uses `docker_name`. The admin panel (`control_ui.py:2063`) builds the view without its own pending check, so for a container whose display name differs from its docker name ("V-Rising" / "vrising") it offers start/stop during a running action - a second Docker action in parallel. | medium-high |
| A3 | 18 F4 | The action-log download button and `/action-log` read `logs/action_log.json`; the log is written to `logs/user_actions.json`. On the operator's server only the latter exists (checked): the button answers "Action log file not found". Two constants for one file, drifted apart. | medium, visible |
| A4 | 02 F1 | The channel-permission cache key uses `_cache_timestamp`, which nothing ever sets, and the hot-reload after a panel save does not clear the cache. A revoked control right stays effective until the 5-minute cache clear - the reviewer said "forever" and missed that loop. Contradicts the operator's decision of 2026-09-16 ("ineffective immediately"). | medium |
| A5 | 02 F2 (part) | `run_docker_action` never checks `success`: a failed Docker action shows "processing", then the unchanged status - never "the action failed". (The "stuck forever" part is refuted: the done-callback clears the pending entry.) | medium |
| A6 | 24 F3 | Double fault: corrupt snapshot AND damaged event log - the rebuild refuses (rightly), the mech restarts at level 1. Logged at ERROR, the corrupt file is kept. | medium (double fault, visible) |
| A7 | 18 F1 (rest) | After `bb11ede` a failing listener no longer reaches the donation service; what remains is `build_donation_event` itself raising after the booking - still reported as a failed donation. | low-medium |
| A8 | 02 F5 | The info dropdown decides on protected content with `allow_start`/`allow_stop` - keys a channel config does not have. Always False: protected info without password is never shown there. Fails closed. | low-medium |
| A9 | 17 F2, F3 | `validate_donation_key`, `is_donations_disabled`, `set_donation_disable_key` turn service errors into False with no log at all. | low-medium |
| A10 | 32 F1 (reasoning wrong) | The game-query retest spinner can stay on - not because `set_testing` raises (it cannot), but because `_atomic_update` below it swallows every write error at DEBUG. | low-medium |
| A11 | 14 F1 | Channel cleanup without "Manage Messages" logs "CLEANUP SUCCESS, deleted 0/N". | low |
| A12 | 02 F4 | Toggle button: `send_message` after `defer` on a config load failure - the user gets nothing. | low |
| A13 | 31 F2 | The task list shows `is_active` from before the expiry check. | low |
| A14 | 17 F7 | A reset that fails half-way reports `success=False` honestly; the backup (Z1) exists. | low |

### Dead code - holds, but unreachable

- 18 F6 `ContainerInfoService.list_all_containers` - no caller.
- 24 F6 `requirement_for_bin` - no caller, marked deprecated.
- 32 F2 `/api/simulate-donation-broadcast` answers `success: true` for "not yet
  implemented" - a Z3 lie, but `simulateDonationBroadcast()` in config.html has
  no button and no input fields in any template.
- 31 F3 the 30 s timeout in `test_rule` is ineffective (`with ThreadPoolExecutor`
  waits on exit) - but the branch needs a running event loop in a request
  thread, which waitress does not have.

### Refuted

| Report | Why not |
|---|---|
| 01 F1 | Admins acting in a channel without the right is SPEC.md B2, restated by the operator today (Z5 clarification). |
| 01 F2 | `execute_docker_action` catches Docker, API, runtime and OS errors itself and returns `success=False`; the loop counts them. |
| 18 F2 | NaN cannot be booked: the Discord path parses digits only; on the web path `int(round(nan * 100))` in the ledger raises. |
| 18 F3 | "Success if at least one format was written" is documented; a failed JSON write is a WARNING and the entry is in the text log. |
| 24 F4 | No deadlock: `LOCK` is an `RLock` (`progress/runtime.py:37`). |
| 24 F5 | The panel's difficulty slider goes through the live mode service (`progress_service.py:519`); the import-time `CFG` holds only the base tables, edited by file. |
| 31 F1 | A once-task re-activated after its time is not run retroactively: missed by more than `MISSED_RUN_GRACE_SECONDS` (300 s) it is rescheduled, not executed. |
| 14 F4 | `should_force_recreate` is a plain time comparison. |
| 17 F4 | Sequence numbers start at 1 (`next_seq`), a 0 does not occur. |
| 17 F8 | The notification file is written atomically since `4aed2cb`. |

### Not re-checked one by one (all low)

01 F3, 02 F6 (two admin helpers - one of them is mine from `f9f4663`), 02 F7,
14 F2, 14 F3, 17 F1, 17 F5, 17 F6, 17 F9, 18 F5, 18 F7, 24 F2, 31 F4, 31 F5,
32 F3. They stay in the reports; none claims money, data or a container.

## What this stage does NOT say

- 29 of 37 sections have not been reviewed at all in this pass.
- Each of the eight was looked at ONCE by ONE reviewer. By the programme's own
  number, a second pass would find mostly different things.
- 27 of 44 findings were marked "unsure" by the reviewer; the re-check above
  decides them, the reviewer's own ranking is not adopted.
