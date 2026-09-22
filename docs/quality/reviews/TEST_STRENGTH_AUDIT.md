# Can these tests fail? — an audit of all 4,956

> „Ein Test, der nicht fehlschlagen kann, ist kein Test."

Every finding in this programme got a red-first test and a mutation probe. The
suite those tests live in never got the same treatment. This is that audit,
run on 2026-09-22 against 4,956 test functions in 398 files.

It ran in three stages: classify all of them mechanically, read what the
classifier flagged, and then attack the tests from the other side — revert each
fix and see whether its guard notices.

---

## Stage 1 — classify all 4,956

| | count | share |
|---|---|---|
| **TAUTOLOGY** — true by construction, cannot fail | **1** | 0.0 % |
| **ISINSTANCE** — asserts only the type of a result | 36 | 0.7 % |
| **NO_CHECK** — no assertion; can only fail if something throws | 92 | 1.9 % |
| **OK** | 4,827 | 97.4 % |

143 flagged. That number is only useful because the filter was wrong six times
first, and each correction came from reading the hits rather than from thinking
harder about the rule:

1. **`assert x` on something that can genuinely be falsy is a real check.**
   `assert result.error_type` fails when it is None; `assert channel.sent`
   fails when nothing was sent. → 106 candidates became 30.
2. **`f(x) is f(x)` is not a tautology.** It calls twice and checks that a
   cache is a cache, or that a hash is deterministic. → 7 became 1.
3. **`pytest.fail(...)` is an assertion.** It is how a test that collects
   findings reports them. Without this rule the seven SAST security tests
   looked unfailable, and they are not.
4. **`side_effect=AssertionError("should not reach")` is a negative check.**
   `test_pre_generate_rest_skips_level_11` patches the inner call to explode
   and then calls the outer one. Elegant, and invisible to a scanner.
5. **"Does not raise" is often the whole guarantee.** `test_valid_task_passes`
   sits beside `test_invalid_task_raises`; between them the contract is
   complete. Six more are the E8 family: a `MechStateError` must not kill a
   bot startup step, and not raising is exactly the thing to check.
6. **The assertion can live in a helper.** `_no_box(embed)` asserts inside
   itself, so its two callers look empty and are not.

This is the same movement as the falsy-answer scan's 219 → 24. **The work is
making the list shorter before reading it, never reading it faster.**

---

## Stage 2 — what the reading found

### One test that could not fail (review E51)

```python
def test_difficulty_multiplier_clamped(self, tmp_path):
    with patch.object(svc, "save_config", return_value=True):
        svc.set_difficulty_multiplier(99.0)
        svc.set_difficulty_multiplier(-1.0)
    assert True  # no exception means the clamping branches executed
```

`save_config` is patched out, so nothing was written and nothing read back. A
`set_difficulty_multiplier` that stored 99.0 unclamped kept this green — in a
test named after the clamping.

It matters because **this exact guarantee was already wrong once**: review C69
found the reachable cost range at $2.50–$25, half the promised ceiling and
below the promised floor. The test that should have seen it asserted `True`.

Two things fell out of repairing it:

- The bounds are **not** 0.25 and 2.5. Those are what
  `_lowest_difficulty()`/`_highest_difficulty()` return when the level-2 base
  cost is 0 — a branch this test never takes, because an empty config file
  still resolves through the fallback, which prices level 2 at $10. The real
  reachable range for a default install is **0.5 to 5.0**. The comments in the
  test said otherwise for as long as they had existed.
- My first repair asserted the comment's values and went red. I had believed
  the comment instead of measuring — the same mistake the comment itself was.

### Five tests that checked less than their name claimed (review E52)

| Test | The name promises | What was checked |
|---|---|---|
| `test_input_sanitization` | path traversal is rejected | `isinstance(result, ServiceResult)` |
| `test_get_tasks_in_timeframe_filters_correctly` | correct filtering | that it returned a list |
| `test_load_tasks_corrupted_json_returns_system_tasks` | "at least the system donation task" | that it returned a list — empty passes |
| `test_load_config_corrupted_returns_defaults` | the defaults | only the type |
| `test_on_error_logs_traceback` | a logged traceback | `caplog` set up, never read |

**`test_input_sanitization` is the worst of them.** Its docstring forbids "any
unsafe filesystem write or script-shaped path being accepted as-is" and its
only assertion was the return type. Delete `_validate_path_safety` entirely and
it stayed green, because the method returns a `ServiceResult` either way. A
security test whose only check is the return type is not a security test.

It now drives six hostile names (`<script>`, `../../../etc/passwd`, spaces,
semicolons, backslashes), and checks three things that can each fail on their
own: the call is refused, the refusal carries a reason, and the containers
directory is unchanged afterwards. Plus a counter-check that an ordinary name
is still accepted — without it, the finding could be "fixed" by refusing
everything and the suite would agree.

Every one of the five was probed by breaking the production code it guards:

| Fix | Mutation | Result |
|---|---|---|
| `test_input_sanitization` | remove the name regex | 4 red |
| `test_get_tasks_in_timeframe_filters_correctly` | ignore both window bounds | 1 red |
| `test_load_tasks_corrupted_json_returns_system_tasks` | add no system tasks | 1 red |
| `test_load_config_corrupted_returns_defaults` | corrupted read turns translation ON | 1 red |
| `test_on_error_logs_traceback` | remove the `logger.error` | 1 red |

The translation one taught its own lesson. The first mutant used
`setdefault('enabled', True)` and the test stayed green — which looked like a
surviving mutant and was not one: a corrupted read already returns a
`settings` dict carrying `enabled: False`, so `setdefault` did nothing. **A
mutant that changes nothing proves nothing.** Forced to `True`, the guard goes
red as it should.

---

## Stage 3 — attack from the other side

The classifier reads shapes. It cannot tell whether an assertion checks the
*right* thing. So the guards were tested the other way round: for each of the
30 most recent fix commits, reverse-apply **only its production-code hunks** —
leaving its test file exactly as it is — and run the guard group.

A fix that can be reverted while the suite stays green has no guard, whatever
its test file claims.

```
26  CAUGHT    the guard went red
 4  SKIP      could not be reverse-applied (later commits touched the same lines)
 0  SURVIVED
```

| Reverted fix | tests turned red |
|---|---|
| E37b container dropdowns page | 18 |
| E46 log tabs answer | 10 |
| E24 a failing button answers | 9 |
| E34 every message reaches the catalogue | 7 |
| E20 a broken mech hides the container list | 6 |
| E48 client pool answers / E27 password / E19 donor / E25 safety switch | 5 each |
| E49, E45, E44, E39, E38, E35, E29, E22, E16 | 4 each |
| E50, E47, E33, E32, E28, E23 | 3 each |
| E41, E31 | 2 each |

The four SKIPs are E37 (superseded by E37b), E35 batch 2, E17 and one more
whose lines later changed. Not a failure — just not measurable this way.

---

## What this does and does not prove

**Proves:**
- Exactly one test in 4,956 could not fail. It is fixed and probed.
- Of the 30 most recent fixes, every one that can be reverted is caught by a
  guard. None of them is decorative.
- The measurement is conservative in the right direction: it ran only
  `tests/spec`, so a fix whose guard lives elsewhere would have shown as
  SURVIVED. None did.

**Does not prove:**
- The reverse-mutation run covers 30 fix commits, not all 141 findings of
  v2.4.
- 91 NO_CHECK and 32 ISINSTANCE remain after the repairs. They *can* fail — on
  an exception, or on a type change — so they are weak rather than vacuous,
  and roughly 40 of them were read individually. The rest are a named backlog,
  not a clean bill of health.
- A test can assert a great deal and still assert the wrong thing. The clamping
  repair is the proof: my own first version asserted two numbers with
  conviction and both were wrong.

**The honest one-line verdict:** the second principle held for the work this
programme did, and until today it had never been checked for the suite that
work lives in. It has now, once, with a tool that is in the repository and can
be run again.
