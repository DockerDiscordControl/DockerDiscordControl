# Section 26 — `scheduler.py`, read for the first time (2026-09-21)

One of **three sections neither review pass ever looked at** (13, 26, 37 — see
`PASS2_STAGE_A.md`). This one starts and stops containers on a timetable
without anybody pressing anything, which is why it was read first.

Not a reviewer package this time: read by hand, plus one mechanical scan.

## Findings

| # | What | Commit |
|---|---|---|
| E1 | The task file lost its permissions on every save, and leaked three temp files per save when the disk was full. A fourth hand-rolled temp-and-rename in a file that already imports `atomic_write_text` twice. | `8141eeb` |
| E3 | A scheduled run that failed with a DDC exception wrote nothing **on the task**. The panel kept showing the previous run, quite possibly a success, while the nightly restart was not happening. | `87d772f` |
| E4 | An unreadable `tasks.json` is indistinguishable from "there are no tasks", and every writer builds its list from that. Adding one task after a failed read wrote a file with only that task in it. There is no backup. | `cb21266` |
| E5 | An error *while checking* a task's validity counted as "invalid", and the cleanup deletes on invalid. A validator meeting an unexpected value removed the task from the schedule for good. | `bdb4925` |
| E6 | A container configuration that could not be read answered "may run", so a scheduled action touched a container without confirming it was still allowed. Recorded as SPEC.md **B14**. | `2a156f4` |

## Refuted

**The DST inconsistency.** Three of six time calculators (`once`, `monthly`,
the donation task) bypass the shared `_localize` helper, which adds
`tz.normalize(...)` — and the existing daylight-saving tests only cover
`daily`, which uses it. It looked like a finding. Measured for
`Europe/Berlin`:

| case | raw `localize` | with `normalize` | same instant |
|---|---|---|---|
| spring-forward gap, 2026-03-29 02:30 | `02:30+01:00` | `03:30+02:00` | **yes** |
| fall-back double, 2026-10-25 02:30 | `02:30+01:00` | `02:30+01:00` | **yes** |
| ordinary day | `04:00+02:00` | `04:00+02:00` | **yes** |

`normalize` changes the representation, not the instant. The computed
`next_run_ts` is identical, so the bypass is cosmetic — it affects only how a
time looks in a DEBUG line. Written down because a refuted suspicion belongs
in the result as much as a confirmed one: "fixing" it would have been work and
risk for nothing.

## Noted, not repaired

- `_get_task_grouping_key` is dead code whose own docstring claims it is used
  by `save_tasks`. It carries an `@lru_cache(maxsize=8)` keyed by task object.
  Nothing calls it. Deleting it needs a probe of its own — that is exactly how
  `dfa3662` broke the panel's JavaScript (review E2).
- `reschedule_missed_task` records a missed run on the task for a ONE-TIME
  task and not for a recurring one. Defensible (a recurring task runs again
  tonight), but the two branches disagree and nobody decided that they should.

## What this section says about the programme

Three of the five findings are **the same sentence**: *a failure that looks
like an empty result.* That is what made the scan worth doing after the third
one — every handler in the file that answers a failure with a falsy value, 33
of them. Most are harmless, because the caller REFUSES on a falsy answer and
nothing is lost by refusing. E6 was the one where falsy meant "go ahead and
touch the container".

The technique is cheap and repeatable, and it belongs in the other two
unreviewed sections.

## What this section does NOT say

- The time calculations were read, and only the DST question was pursued to a
  measurement. They are covered by existing tests for `daily`, `weekly` and
  cron; `monthly` and `yearly` are not tested across a daylight-saving change.
- Sections 13 (`config_service.py` and the config services, 1,806 lines) and
  37 (`token_security.py`, `key_crypto.py`) have still been read by nobody.
