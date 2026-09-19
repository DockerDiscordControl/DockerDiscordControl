# Stage 4 — Review with verifiable coverage

**Status:** 2026-09-17 · **Review carried out. The check plan remains a scaffold without a single tick.**

This stage requires five things: a split into sections of at most 2000 lines, a contract test on
coverage, a check plan per section, a coverage calculation and a review by a different model.
**Four of them are in place, one is not:** the check plan is a scaffold with 1,513 names and not a
single tick. Filling it without having read the names would be the "report of how much was
achieved" that the programme text explicitly rejects.

---

## 1. Split — in place

37 sections, 190 pieces, **61,252 of 61,252 lines** in 185 files (`docs/quality/SECTIONS.txt`).
The cuts are made at class and function boundaries, not arbitrarily at line 2000: a section is
meant to be readable in one go.

Four files are above the limit and had to be split — `docker_control.py` (5,255),
`control_ui.py` (3,293), `status_info_integration.py` (2,590), `scheduler.py` (2,165).

### The structural finding along the way

**`DockerControlCog` is a single class of 4,485 lines** — 8.5 % of the entire application code. It
cannot be split at class boundaries because it is the boundary itself; the split had to cut
**inside** the class at method boundaries.

This is not a formal defect but the explanation for a gap in stage 0: the inventory only searched
this file in a targeted way and **never read it through**. A section made up of method bodies of
one class is not the same as a readable unit.

*Not fixed.* Breaking up a class of this size is a rebuild of production code without a waiting
test — exactly what the programme text rules out. It is a decision for the operator.

---

## 2. Contract test — in place and it bites

`tests/spec/test_stage4_sections.py` checks: every source file lies in **exactly one** section,
without gaps and without overlaps, no section above 2000 lines.

**Claim and expectation come from different sources** — the claim from `SECTIONS.txt`, the
expectation from the file system. If both were taken from the section file, it would be a mirror
test; exactly such a test slipped through in the wiring test of stage 3 and stayed green with the
CSRF protection removed.

*Proof of effect*, indispensable for a test that was green from the start — four mutations, each on
its own:

| Mutation | Result |
|---|---|
| File removed from the list | 1 failed |
| Gap torn open | 1 failed |
| Coverage ends before the end of the file | 1 failed |
| Section artificially above 2000 lines | 2 failed |

Restored: 3 green, file bit-identical to the backup.

---

## 3. Check plan — scaffold in place, not a single tick

`docs/quality/CHECK_PLAN.txt` lists, per section, the public names that would have to be judged
individually in a review.

There are **1,513 names** across 37 sections, on average 41 per section.

**The plan is a task list, not a proof.** No tick means: not judged. Filling it with 1,513 ticks
without actually having read the names would be exactly the "report of how much was achieved"
that the programme text rejects.

> *Figure corrected while still writing:* This first said 840. That was an earlier count that
> only counted **top-level** names; the check plan additionally covers the methods of public
> classes. Both figures are correct in themselves — but the report claimed the smaller one about a
> plan that contains the larger one. The eighth figure in this programme taken from an outdated source.

---

## 4. Coverage calculation — and why the friendly figure is the wrong one

| | Sections | Lines |
|---|---|---|
| contain a file in which something was changed | 33 | 55,773 (91 %) |
| not touched at all | **4** | **5,479 (9 %)** |

The calculation in the open, so that it can be checked instead of believed: the four untouched
sections add up to 5,479 lines as measured; 61,252 − 5,479 = 55,773.

**This figure is by now eight times out of date** — 12 sections with 17,242 lines, then 11 with
15,479, then 10 with 14,636, then 9 with 14,344, then 8 with 12,510, then 7 with 10,618, then 6 with 8,683, now 4 with 5,479. Every correction shifts it: **section 13**
dropped out with `config_service.py`, **section 20** with `update_notifier.py`, **section 37**
with `token_security.py`, **section 28** with `configuration_save_service.py`, **section 33** with `app/bot/token.py`, **section 22** with `mech_evolutions.py`, **section 07** and **21** with the translation into English (`scheduler_commands.py`, `animation_cache_service.py`). This is not a flaw of the calculation but its nature — and the reason to
measure it at the end instead of carrying it along.

**These 91 % are not coverage, and they must not be read as such.** "Touched" means: this
section contains a file in which a single line was changed. That is not a review.

**Honestly: not a single one of the 37 sections was read through systematically.** What did take
place were targeted searches for named patterns (bare `except:`, environment reads, character-identical
twins, call sites) and selective corrections. These searches were mechanical and complete — but
each of them checks one question, not the section.

### The four never-touched sections

| Section | Lines | Content |
|---|---|---|
| 08 | 1,341 | `status_handlers.py` |
| 14 | 1,435 | `channel_cleanup_service.py`, `embed_helper_service.py`, `status_overview_service.py`, … |
| 15 | 708 | `docker_client_pool.py` |
| 26 | 1,995 | `scheduler.py` |

Notable among them: **section 26** (`scheduler.py` — the documented Z5 exception lives there).
It was read by a second model (point 5), but still not by me — what is stated there comes from
checked reports, not from my own reading.

**Section 37** (`token_security.py` — Z9) was also listed here until the correction of the token
display; it has been touched since. That still does not mean I read it in one go — here too,
touched only means that lines in this file were changed.

**Section 28** (`configuration_page_service.py`, …) has been touched since commit 16eca1e. I did
**not** remove it from the list there: the file changed without a line difference, no header line
moved — and I had read "touched" off the header lines instead of off the diff's file list. It
only came to light in the following commit, when the same section number showed a header line
change. Corrected in the commit that switches over `configuration_save_service.py`.

---

## 5. Review by a different model — **carried out**

Three instances of a different model, one section each, chosen by "would the user notice it" and
never touched: **13** (configuration service — Z2, Z9, migration), **26** (`scheduler.py` — the
unconfirmed Z5 exception), **37** (`token_security.py` — Z9).

**Not a single finding was adopted unchecked.** A second model can be just as wrong as the first;
the review is the beginning of the work, not its end. That was not caution for form's sake: of the
reported findings, **one did not survive re-measurement**, and for two the matter was right but
not the reasoning.

### Fixed — one finding, one commit, one full run each

| Commit | Finding |
|---|---|
| `208ae81` | **A read error on the configuration looked like a fresh installation.** On `PermissionError`, `_load_json_file` returns the default, which carries `web_ui_password_hash: None` — and `app/auth.py:176` then opens `admin`/`setup` in front of 70 routes. The write path was already defended against exactly this loss (`config_service.py:385-386`), the read path was not. |
| `9ea946c` | **The same container was there for some callers and gone for others.** Two readers of the same files, opposite defaults for a missing `active`. The key really is missing: `config_migration_service.py:230` writes old entries verbatim, and the word `active` does not occur there. |
| `4aed2cb` | **A donation notice could land on disk half-written.** `open(…, "w")` + `json.dump` on the file that the bot polls every 30 seconds — and the reader **deletes** it on invalid JSON. As measured, what remained was not an empty nothing but a record that began validly and broke off in the middle of a key. |

### Refuted — and that is the most important result of the review

**The reported daylight-saving gap in the scheduler does not exist.** The report was that five raw
`tz.localize(...)` calls stand against the in-house `_localize` helper and that a timed task
therefore fires an hour off in the changeover night. I adopted the finding, made it more precise
and extended it from "two" to five places — and then measured (pytz 2024.2, Europe/Berlin,
transition 2027-03-28):

```
naive=02:30   raw=02:30+01:00   norm=03:30+02:00
raw.utc=01:30+00:00            norm.utc=01:30+00:00
```

`normalize` does **not change the point in time**, only its label. `scheduler.py:737` stores the
point in time (`.timestamp()`). The task therefore fires correctly; the difference is visible only
in `strftime` output of debug lines. According to its own docstring, the helper exists against
`replace(...) + timedelta`, not against `localize` alone — and at the call sites the
`timedelta` is applied to a **naive** date anyway. The inconsistency remains a matter of style,
not a break. **There is nothing to correct here.**

Had I stubbornly done "test first", the red would have failed to appear — but only after the work.

### Also largely refuted: the double execution after a restart

The report was: the Docker action (`scheduler.py:1829`) runs before `_persist_executed_task`
(`:1877`); if the process dies in between, the old `next_run_ts` is still there, and after the
restart `should_run()` executes the task a second time. I had adopted the suspicion and noted it
as unchecked.

**The likely case is already covered**, and explicitly so:
`scheduler_service.py:392-396` skips an execution whose occurrence has already run
(*"Skip if this occurrence already ran (its reschedule could not be saved)"*), and `:453-454`
records the occurrence **before** the execution (*"Remember the executed occurrence before execute_task()
moves next_run"*). So if only the saving fails while the process keeps running, the lock takes
effect. I found it only late: I had searched for `running`, `in_progress`, `lock` and
`idempot` — `_executed_runs` matched none of these patterns. Once again I searched for expected
**names** instead of reading the path.

**What remains is negligible.** `_executed_runs` is an instance field and empty after a real
process restart. It would therefore take a restart that falls *exactly* into the span between the
Docker action returning and `tasks.json` being written — milliseconds to tenths of a second — and
completes within the grace period. The grace period has since been measured:
`CHECK_INTERVAL = 60`, `MISSED_RUN_GRACE_SECONDS = max(180, 300)` = **300 seconds**
(`scheduler_service.py:47,52`); `_service_loop:278-281` runs a cycle immediately on start, without
sleeping first. The consequence would be a second restart of the same container — annoying, no
data loss.

**No guarantee, no rebuild.** A safeguard would require persisting `_executed_runs`; that would
be a new guarantee about crash behaviour and thus the operator's decision. To the question "why
should the process crash at all?" the honest answer is: it shouldn't — restarts are
commonplace (`rebuild.sh`, Unraid auto-update, see B7), but the window is too narrow for a
safeguard to be worthwhile.

### Operator questions — not mine to decide

1. **The security display equated "a secure source is being used" with "no insecure copy
   exists" — DECIDED AND FIXED (2026-09-18).** If `DISCORD_BOT_TOKEN` was set,
   `verify_token_encryption_status` returned immediately; `token_exists` stayed `False`. Consequence:
   `security_service.py:265` awarded 40/40 and "✅ Excellent", the panel showed green, and
   `auto_encrypt_token_on_startup` (wired in `app/bootstrap/runtime.py:194`) never ran —
   **while a plaintext token could be sitting in `bot_config.json`.** This touched Z9.
   **The operator's decision:** a warning next to the green, no point deduction. The environment
   variable is right and keeps its 40/40; in addition the display now reports the plaintext copy. That the
   warning becomes visible is checked, not assumed: `_token_security_modal.html:181-186`
   renders the `recommendations` list under its own heading.
   **What did NOT happen:** I had announced two deliberately written tests as casualties
   (`test_crypto_cache.py:272-274`, `test_utils_completion.py:530-534`). As measured, both stayed
   green — their fixtures create an empty configuration directory, and there the dropped early
   return changes nothing. The announcement was wrong, the correction before it right.
   **A side effect that was not built in:** without a guard, the code would in future have reported "⚠️ No bot
   token configured" on a clean installation that obtains the token exclusively from the
   environment variable. This message now appears only when there really is no token.
   *Already exonerating before:* `/encrypt-token` does **not** depend on this status.
2. **`migrate_to_environment_variable` is dead — and pinned down as dead.** The method reads
   `self.config_manager`, but only `self.config_service` is set (`:51-59`). The `AttributeError`
   is caught at `:247`, and the operator sees the raw Python text as the error message.
   `test_crypto_cache.py:332-340` checks exactly this path as expected behaviour;
   `test_utils_completion.py:1133` sets the missing attribute from outside and thereby checks a
   success path that does not exist in production — a mirror test.
3. **Which `active` default applies.** It was corrected to "missing means active", because this rule
   is written as a comment in the code in two places and is nailed down by two tests, while the
   other side has no test. The choice itself is yours.
4. **27 files derive the configuration directory on their own** (measured, ~44 places).
   Of these, **six** respect `DDC_CONFIG_DIR` — `container_status_service.py:135` even with a
   different default (`/app/config`). Three places fall back to a **relative** `Path("config")`
   that depends on the working directory. This is stage 2 point 3 on a large scale, but merging 27
   files is a rebuild without a waiting test — therefore not touched.
5. **`ScheduledTask` carries no channel** (`__slots__`, `scheduler.py:167-172`: 21 fields, none
   channel-related). A renewed channel-permission check at execution time is therefore possible for **no**
   timed task — not only for the documented Web UI exception. Checked myself.

### Minor findings, deliberately ranked low

- `update_notifier.py:63` wrote non-atomically — **fixed**, see below. `mech_reset_service.py:243`
  has the same construction and remains **uncorrected**: the method builds its payload itself, there is
  no injection point from outside, and a failure could only be forced by stubbing
  `json.dump` — then the test would check the stub. Stop where what one changes cannot be
  measured. The case is annoying all the same: the same file imports `atomic_write_json` at
  `:25` and uses it twelve lines earlier at `:202`, with a written-out justification — a
  deliberate switch-over in which a sister method was left behind.
- **Measured in passing:** `reset_evolution_mode` has exactly one caller (`mech_reset_service.py:106`),
  and its **success flag is not evaluated** — at `:107` only the message goes into a
  list. A failed reset would pass as part of a successful overall reset.
- `scheduler.py:438-448`: eleven unreachable lines after `return True` (`:436`), copied word for word from
  `_validate_monthly`. Harmless — until someone "repairs" them.

---

## 6. What was NOT checked

- **No section was read through systematically.** The 91 % "touched" says nothing about that.
- **None of the 1,513 names in the check plan has been judged.**
- **The four never-touched sections** (5,479 lines, 9 % of the tree) were covered in this programme
  exclusively by the mechanical searches — not read. Sections 26 and
  37 were read by a second model, not by me.
- ~~The suspicion of double execution after a crash~~ and ~~the unknown poll frequency~~
  stood here until 2026-09-18. **Both have since been measured** — result under point 5,
  "Refuted".
- ~~Whether `_impl_schedule_*` in `cogs/scheduler_commands.py` is reachable~~ — **settled on
  2026-09-18: dead code.** The extension list (`app/bot/startup_steps/commands.py:26-30`) loads
  only `docker_control`, `auto_action_monitor` and `translation_monitor`; nothing references the
  mixin. The live path for timed tasks from Discord is the button at
  `cogs/status_info_integration.py:2331`. Recorded in `SPEC.md` B11.
- **Whether the split makes sense** was not judged. It is machine-generated and meets the
  limit; nobody has checked whether the sections belong together thematically.
