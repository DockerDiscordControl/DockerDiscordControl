# Stage 3 — Weeding out tests that cannot fail

**As of:** 2026-09-17. Of the four checks of this stage, **three have been carried out completely**
("does it run alone?", mirror tests, function versus call site), **one only as a sample**
(cross-check by reverting: exactly one legacy test out of 3,962). What was not checked is below in
section 5 — and is the more important part of this report.

*Until 2026-09-17 the header said "two are outstanding" and thereby contradicted section 3.
Brought up to date — the same kind of self-contradiction had to be cleaned up three times today already.*

**Nothing was deleted.** The programme text says: report, remove nothing without consent.

---

## 1. "Does the test also run alone?" — carried out completely

**Every one** of the 127 test files was started individually in its own throwaway container.

| | |
|---|---|
| files checked | **127** |
| also pass alone | **125** |
| fail alone | **1** (two tests in it) |
| measurement dropout | 1 — **a bug in my tool**, see section 4 |

### The finding without a finding belongs in the report too

The AST census had found **16 places** that modify `sys.modules` — i.e. rebuild the module world for
all subsequent tests. I had expected this to produce order-dependent tests.
**Not a single one of them produces one.** My expectation was bleaker than the finding.

### The one find: `tests/unit/audit_2026_09/test_r2_g5_mech.py`

Two of the 41 tests in it fail alone:

- `test_r1_7_startup_step_keeps_updates_made_while_it_runs`
- `test_r1_7_startup_step_does_not_set_a_goal_at_max_level`

In the group both are green (`tests/unit/audit_2026_09`: 564 green).

**They do not fail on their own assertion, but already on the `import` in their first
line.** The chain is nine levels long:

```
from app.bot.startup_steps import member_count
  → app/bot/__init__.py:12   → events.py
  → startup.py:16            → startup_steps/__init__.py:25
  → scheduler.py:12          → services/scheduling/__init__.py:13
  → scheduler.py:27          → services/docker_service/__init__.py:10
  → docker_utils.py:76       → _load_timeout_from_config(...) → load_config()

AttributeError: 'types.SimpleNamespace' object has no attribute 'get_config'
```

**The cause lies in the production code, not in the test:** `docker_utils.py:76-80` calls
`_load_timeout_from_config(...)` **five times at module level**, and each of these calls calls `load_config()`.
Another case is in `progress_service.py:125` (`CFG = load_config()`), a sixth in
`docker_utils.py:676` (`_CACHE_TTL = _get_cache_ttl()`). **An `import` should do nothing.** Here
it reads configuration from disk — and can fail doing so.

*Why it works in the group — verified, not assumed:* `test_r2_g3_startup.py:42` imports
`app.bot` at **module level**, `test_pkg_f_startup.py:148` inside a test. Both come
**before** `test_r2_g5_mech.py` in the alphabetical collection order, which comes as the last file of the directory.
When its turn comes, the whole chain has long been in `sys.modules` and the
`load_config()` call no longer happens at all. Started alone, it does happen — and hits
the stub that the `ps` fixture only sets at `:104`, *after* the import.

*And the safety net has a hole:* `_load_timeout_from_config` catches
`(ConfigLoadError, KeyError, ValueError, TypeError)`. The `AttributeError` **slipped through**.
What else `get_config()` can pass up was **not** investigated (section 5).

**Ranking by "does the user notice":** The two tests are not worthless — they check
something real, but only as long as someone else has imported first. The more serious part is the
import with a side effect. In operation the configuration is real, so the case is rare; but if it
fails, it arrives as an `ImportError` deep in a nine-level chain instead of as an understandable message.

> **Fixed on 2026-09-17** — for `docker_utils.py`, not for `progress_service.py:125`
> (reasoning in section 6). The values now load on first access instead of on import.
> The waiting test came first and was red with exactly this stack;
> `tests/spec/test_import_without_side_effects.py` records this.
>
> **The proof of effect is stronger than a mutation:** `test_r2_g5_mech.py` alone before:
> 2 of 41 red, after: **41 green — without a single test being touched**. The
> order dependence disappeared because its cause is gone. The cause analysis of this
> section is therefore no longer inferred but verified.

---

## 2. Cross-check by reverting — only as a sample

During stages 1 and 2 the cross-check was run for **every** new assertion: first see the
test red and check the reason, then fix. In addition, for five Z7 tests it was proven by
**mutation** that they bite.

Of the **legacy tests**, exactly **one** test out of 3,962 was checked this way — and **it was broken**:
`tests/unit/extended/test_docker_infra_gaps.py` drove the same error path as a new test
and had always been green, because its `_bad_open` already raised on **reading**, long before writing.
The first repair attempt had no effect; that was only proven by a mutation.

**From a single sample, exactly nothing follows about the remaining 3,961** — not even that things look
better there. It only says: green proves nothing.

> **Correction, added 2026-09-17.** Until just now this said "three of 3,962" and "Three of 3,962
> do not permit an extrapolation". The number was never counted; it came from my memory of
> the same working day. The count shows: three `tests/spec` files carry mutation proofs —
> those are **new**, not legacy tests. The only mutation-checked legacy test is
> `test_docker_infra_gaps.py`. A hit in `tests/unit/utils/test_crypto_cache.py:519`
> ("Mutation isolation") is a false hit of the text search and describes a key cache.
>
> *Found along the way while counting:* `tests/spec/test_z7_server_order_write.py` carries **no**
> mutation note, although the mutation was demonstrably run (verified in the SPEC.md Z10 section
> on Z7). Four mutations, three noted — the same gap, only in the documentation.
>
> This makes it the sixth number of this programme that I had taken from memory instead of from a
> measurement. The other five are in `STAGE0_INVENTORY.md`.

---

## 3. Mirror tests · function versus call site — carried out (2026-09-17)

### 3a. Function versus call site — **one finding, fixed**

`app/web/app_factory.py:create_app` assembles the Flask application from eleven steps. Each
individual one is tested; the **wiring** was not. Proven by mutation: four steps removed
individually, `tests/test_web_factory.py` stayed **green every time** — among them `install_csrf_protection`.
The CSRF protection could drop out of the application without the suite noticing.

*Why the existing tests were blind:* `test_web_factory.py` checks the Flask instance, `/health` and
`Content-Security-Policy` — that covers `install_security_handlers` and nothing else.
`test_bundle3_security.py` **replaces** `register_blueprints` and `register_routes` via `monkeypatch`,
so it explicitly does not check the real assembly. `test_security_sast.py` imports from `app.web_ui`
and skips on `ImportError`.

*Fixed* by `tests/spec/test_app_factory_wiring.py`, proven effective by mutation.

**And the most instructive find of the whole stage is that my first version of this test was itself a
mirror test.** It took the expectation list from the *calls inside* `create_app`. If
a call drops out, it disappears from the expectation at the same time — the test compared the file with
itself and could not fail. Under the same mutations it stayed green. The guard
`len(schritte) >= 8` (`schritte` = steps) did not catch it: eleven become ten, the threshold holds.
Second version: expectation from the **imports**, delimited via the **signature of the module of origin**.
Both lie outside the code under test.

### 3b. Mirror tests — **one finding, reported**

*How the search was done, and why the first search was worthless:* A coarse pattern ("test reads source code")
found **60** files. The vast majority are false alarms: `read_text` appears in almost every Z7 test because it
reads a **data file in `tmp_path`** to check whether it is still complete after a crash —
the opposite of a mirror test. Narrowed down to reads from the **production tree**, **6** remain.

The boundary that matters: it is *legitimate* to check a production file against a rule that stands
outside it ("no bare `except:`", "no character-identical twins"). It is a *mirror* to make the file content
itself the expectation — then a change removes both sides.

Five of the six are contract tests. Verified rather than claimed: `test_settings_take_effect_everywhere.py`
was checked by mutation — a single reverted spot turns it red
(`docker_control.py:183`), restored it is green again. It **bites**.

**The one finding:** `tests/unit/audit_2026_09/test_pkg_d1_services.py:197-206` reads the default value
`60` via regex from `scheduler_service.py` and compares the panel preset with it — **both sides
from the same source**. It is saved solely by the appended `== "60"`, which pins the expectation down from
outside. Without this literal it would be a pure mirror test. *Not corrected:* the test is
correct in its result, its construction is fragile. That is a decision for the operator.

*Old version of this section:* "Both checks of stage 3 are outstanding." — done.

The data basis from the AST census:

| Category | Count |
|---|---|
| no check at all | 85 |
| only trivial check (`is None`, `isinstance`, `len`) | 264 |
| mock tautology | 3 |
| `pytest.raises(Exception)` — catches everything | 3 |
| skipped | 6 |
| **hollow in total** | **361 of 4,017 (9.0 %)** |

Of these, **134 are in `tests/unit/extended/` alone** and **zero in `tests/spec/`** — the 21 files and 55
tests of this programme have not increased the hollow share. That is no merit but the
minimum requirement; it does show, however, that "see red first, then green" produces tests that the census
does not object to.

> **Figures corrected 2026-09-17.** This said 362 of 3,962 with 113 files. That was the
> census from last night. I had re-run it, but then evaluated the **old** output file in the
> scratchpad instead of the fresh one in the project directory — without a
> second argument, `audit_tests.py` writes to `./test_audit.json`. It was only noticed because a number **had not moved**
> after 14 deleted and 55 new tests. The seventh number of this programme that came from an
> outdated source.

### Decided: nothing gets deleted

The operator has approved deleting worthless tests. **I am not using this approval**, and that
is a reasoned decision, not convenience.

The 85 tests "without a check" were broken down by the length of their body: 13 single-line, the
rest 2 to 12 statements. The **thirteen single-line ones have been read in full** — none is empty.
Twelve assert that a call does not raise (`_debug_time_conversion` with broken input,
`_log_task_deletion` with missing keys, `_perform_sync_cache_warmup` with a missing module). That
is a weak but real assertion on paths nobody else touches. Deleting them
improves nothing and takes coverage away.

**And one is better than its category:**
`test_animation_cache_service.py:728` sets `side_effect=AssertionError("should not reach")` — the
test **falls over** if the code takes the forbidden path. The assertion sits in the stub,
not in an `assert`. The census does not see it.

**This is a finding about the measuring tool itself**, and it is counted rather than estimated:
**Three** of the 85 carry their assertion in a `side_effect` and are nevertheless listed by the census as
"no check at all" — `test_animation_cache_service.py:701`, `:728` and `:1221`. That leaves
**82** without a recognisable assertion.

`scripts/audit_tests.py` counts `assert`, `pytest.raises`, `mock.assert_*`, `pytest.fail()` and
helpers named `assert*`/`verify*`/`check_*`. A `side_effect=AssertionError(...)` is in
none of these forms — the assertion moves into the stub, and the tool does not see it.
The census thereby underestimates the coverage instead of overestimating it; that is the more harmless
direction, but it is an inaccuracy, and it deserves to be named.

The category "only `mock.assert_*`" (65 tests) does **not** count as hollow — it checks the
**call site** and is therefore a strength, not a flaw.

### A genus of its own, three of them read

Seven of the hollow tests near risk are named `*_swallows_*`, `*_handles_bad_*` or `*_is_caught`.
Their entire body is: call the function, it must not raise. They *can* fail, but
pin down only that nothing blows up — never whether the clean-up did the **right** thing.

Three were read in full, together with the code locations behind them. **Result: none of the three
code locations justifies an intervention.** The finding is the tests, not the code. Details and
the two mis-rankings I made along the way are in
`STAGE0_INVENTORY.md`, section on the census.

---

## 4. The measuring tool itself was broken

Three times my evaluation loop reported "no measurement" for a group that had in fact
run through. Once this silently became a total that was 447 too low.

**Cause, fully proven:** The loop evaluated with `echo "$R" | grep`. The shell is
zsh, and its built-in `echo` interprets backslash sequences. The file
`tests/unit/services/mech/test_animation_cache_service.py` contains a parametrised test whose
name carries the string `\x00` (`test_xor_is_symmetric[\x00\x01\x02\x03]`). `echo` turns this into
a **real NUL byte**; `grep` then treats the input as binary and outputs
**nothing** for matches — not `0`, but empty.

Verified on the same output: 0 NUL in the original → 1 NUL after `echo` → `grep` without `-a` empty, with `-a`
it finds the line. With `printf '%s\n'`: 0 NUL, line found. This also explains why precisely
the three groups containing exactly this file were affected.

**Fixed** and proven at scale: before the fix the full run reported
`FEHLENDE_MESSUNGEN=1` (missing measurements), afterwards `0` — with 43 of 43 groups each having exactly one count value.

**It was noticed only because a number had been announced before every run.** The first time, the
result deviated by 444 instead of 3. Without this prediction it would have slipped through — the guard that
finally caught it did not exist yet at that point.

---

## 5. What was NOT checked

- **Practically the entire legacy test base** was never checked by mutation or reverting. Exactly
  **one** test of the then 3,962 has been checked this way (section 2) — nothing is known about the rest
  except: they are green. Today the tree counts 4,017 test functions in 134 files; the 55
  added ones all came into being with red seen first, which says nothing about the legacy tests.
  (This first said 3,959, then 3,961 — both from outdated census states.)
- **What `get_config()` can raise.** Its body contains neither `raise` nor `except`; it passes
  on whatever `_migrate_legacy_config_if_needed`, `_loader_service.load_modular_config`,
  `_decrypt_token_if_needed` and the cache service raise. These four were **not** read.
  The only thing verified is that the `AttributeError` slipped through the net in `docker_utils.py:69`.
- **Whether the six imports with side effects ever strike in operation.** `progress/runtime.py:100-112`
  is guarded against `FileNotFoundError` and `json.JSONDecodeError`; not against `OSError` on
  writing. Whether that is reachable in real operation was not determined.
- **The remaining hollow tests** were counted and sorted, but not read individually. Of the
  361, 13 have been read in full (the single-line ones without a check, section 3) and 3 proven to be
  misclassified by the census. About the remaining 345 this report says nothing.
- **Whether further assertions are hidden in stubs.** Only `side_effect=AssertionError`
  and `pytest.raises` were counted. Other forms — a `Mock` whose return value is compared later, or an
  `autospec` that would expose a wrong signature — are not covered.

---

## 6. Proposals — to be decided, not implemented

1. ~~**Defuse the six imports with side effects.**~~ **Done on 2026-09-17** — for
   `docker_utils.py` (five timeout values plus `_CACHE_TTL`), **not** for `progress_service.py:125`.
   The values now load on first access instead of on import, via a module-level `__getattr__`
   (PEP 562); to every reader everything looks unchanged. The waiting test that this proposal
   still lacked exists as `tests/spec/test_import_without_side_effects.py` and checks in a
   **separate process** that an `import` reads no configuration.
   *`progress_service.py:125` deliberately stays as it is:* five test files assign
   `progress_service.CFG` from outside, so it is effectively an interface. Making it lazy
   would not be a refactoring without a waiting test, but one **against** five waiting tests.
2. ~~**The two order-dependent tests** would then run alone by themselves.~~
   **Confirmed:** `test_r2_g5_mech.py` alone before: 2 of 41 red, after: **41 green — without a
   single test being touched**. That is the proof of effect of the fix and at the same time the
   evidence that the cause analysis of this report was right.
3. **The safety net in `_load_timeout_from_config`** catches four exception types. Whether those are the
   right ones can only be said once it is known what `get_config()` can raise.
4. **Measure order dependence permanently.** The individual run over all 127 files was a
   one-off action. As a recurring check it would catch regressions — but it costs 127
   container starts.

**As of 2026-09-17:** Points 1 and 2 are implemented and measured (see above). Points 3 and 4 are
**not** — both touch production code or runtime and remain decisions for the operator.

*Point 1 was not implemented in the form in which it originally stood here.* The proposal named
six places in one breath. When recounting the call sites it turned out that
`progress_service.CFG` is assigned from outside by five test files and is thus an interface
— the proposal was bad there, and it was bad because I had written it without counting the
call sites. Therefore only `docker_utils.py` was implemented.
