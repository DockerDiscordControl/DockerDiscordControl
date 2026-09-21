# Stage 4 review - pass 2, stage A (2026-09-20/21)

The same eight sections as pass 1, chosen by "would the user notice it": money
(17, 18, 24), permissions (01, 02, 31, 32), containers and deleting (14). One
pass each, reviewer model **Sonnet**, one reviewer per section, each seeing
only its own package directory. The code was written and fixed by Opus.

**Why a second pass at all.** The programme text measured three passes of the
same reviewer over one section at 9, 10 and 7 findings with **pairwise overlap
zero**. Pass 1 closed with the sentence "each of the eight was looked at ONCE
by ONE reviewer; by the programme's own number, a second pass would find
mostly different things". This is that second pass, and the number below says
how well that held here.

Reports: `pass2/sNN/REPORT.json` in the session scratchpad, built by the same
tooling as pass 1 (`scripts/review/build_package.py`, `check_plan.py`,
`coverage.py`).

## Coverage

| Section | Names | Judged | Findings | of which "unsure" |
|---|---|---|---|---|
| 01 | 23 | 23 | 5 | 4 |
| 02 | 24 | 24 | 4 | 3 |
| 14 | 43 | 43 | 5 | 2 |
| 17 | 61 | 61 | 3 | 2 |
| 18 | 87 | 87 | 6 | 4 |
| 24 | 40 | 40 | 5 | 2 |
| 31 | 51 | 51 | 5 | 3 |
| 32 | 45 | 45 | 5 | 2 |
| **total** | **374** | **374** | **38** | **22** |

**374 of 374 names judged, 0 not_checked, 0 invented.** No reviewer had to be
sent back this time; the two failure modes of pass 1 (bare names instead of
`path:line name`, and a repeated name judged once) did not recur.

The name count differs from pass 1 (374 against 395) because the sections
themselves changed: the code was repaired 86 times between the passes, and the
check plan is generated from the current source.

## How much of it was new

This is the number the second pass exists to produce, and it is worth being
careful with, because "the same finding" is a judgement and not a measurement.
Three ways of counting, from loosest to tightest:

| Measure | Overlap | What it is worth |
|---|---|---|
| Same file, within 60 lines of a pass-1 finding | 21 of 38 (55 %) | **Over-counts.** Two findings can sit in one function and be unrelated. |
| Judged by hand while the work was done | **11 of 38 (29 %)** | The figure this report stands behind. |
| Same file AND the same line number | 4 of 38 (11 %) | **Under-counts.** The same defect gets described at different lines. |

So **the brother's "pairwise intersection zero" does not hold exactly here** -
roughly three in ten findings were in ground pass 1 had already stood on. But
71 % were new, which is the point: one pass is a sample.

## The two findings that make the case for more than one pass

Both were found **inside a repair pass 1 had just made**. Verified against the
history rather than remembered:

- **D1** (24 F1) corrects `_heal_if_lagging`, and that method was introduced
  by `d3ddcdb` - the commit for pass 1's **A1**. The healing that pass 1 built
  to stop a donation being buried could itself refuse to heal and say nothing,
  and the caller then buried the donation anyway.
- **D4** (14 F1) changed `channel_cleanup_service.py` lines 227-255; **A11**
  (`16d5bb4`) had rewritten 223-233 two days earlier. The repair landed inside
  the block the previous repair had just written.

A reviewer reading fresh code reads it as code. A reviewer reading a repair
tends to read the repair's own reasoning with it. That is the argument for a
second pass that no overlap percentage can make.

## The two findings that make the case for writing decisions in the code

Twice, pass 2 produced **the same false positive as pass 1**, without ever
having seen pass 1's verdict:

- **01 F1/F2** (bulk restart/stop check the admin list and not the channel).
  Pass 1 found it as 01 F1 ("high") and refuted it: SPEC.md **B2**. Pass 2
  found it again and called it **critical**, twice. Both were wrong, and the
  suggested fix would have re-created a regression the operator had already
  suffered once (the Z5 fix of 2026-09-16/17, undone on 2026-09-19).
- **32 F2 / A10** (the game-query retest spinner that stays on). Here the two
  passes named **different mechanisms** for the same symptom - pass 1 the
  swallowed cleanup write, pass 2 the worker that never starts - so both were
  real, and both are fixed.

The first of these changed how the repair was made. A decision that lives only
in `SPEC.md` and a review document does not stop the third reader from
"fixing" it. B2 is now written at both call sites and pinned by
`tests/spec/test_the_bulk_buttons_answer_to_the_admin_list.py`, whose probe M3
adds exactly the check both passes asked for and turns red.

## Every finding was re-checked against the code

As in pass 1, not one finding was adopted unchecked, and each was repaired in
its own commit with a waiting test that was announced before it was run.

**38 of 38 dealt with: 34 repaired, 2 refuted-and-pinned, 2 refuted as stated
with a different real repair found underneath.**

| # | Report | Commit | # | Report | Commit |
|---|---|---|---|---|---|
| D1 | 24 F1 | `1c0079c` | D19 | 18 F5 | `6454e6e` |
| D2 | 24 F4 | `5473d20` | D20 | 18 F7 | `203db82` |
| D3 | 02 F3 | `af62580` | D21 | 31 F2 | `40cfa58` |
| D4 | 14 F1 | `045244f` | D22 | 31 F4 | `706dfc2` |
| D5 | 18 F3 | `b0c136b` | D23 | 31 F5 | `48b69ec` |
| D6 | 17 F1 | `031c5ee` | D24 | 32 F2 | `27cfd73` |
| D7 | 18 F6 | `831d860` | D25 | 32 F3 | `83d1ed1` |
| D8 | 32 F4 | `b3419b9` | D26 | 24 F2 | `d1d9887` |
| D9 | 32 F1 | `8839caf` | D27 | 24 F3 | `4274d0f` |
| D10 | 17 F2 | `3be3ab3` | D28 | 01 F5 | `1bea9ee` |
| D11 | 31 F1 | `0eb6846` | D29 | 32 F5 | `d3b3483` |
| D12 | 24 F5 | `3088993` | D30 | 31 F3 | `a92971c` |
| D13 | 18 F1 | `5e62f37` | D31 | 02 F2 | `3c3af7e` |
| D14 | 01 F3 + F4 | `042d5cd` | D32 | 02 F4 | `40a8cf1` |
| D15 | 14 F5 | `6139312` | D33 | 14 F2 | `e54edce` |
| D16 | 14 F6 | `182e989` | D34 | 14 F4 | `af26093` |
| D17 | 02 F1 | `5088358` | D35 | 17 F3 | `25c1cc6` |
| D18 | 18 F4 | `9452bb6` | D36 | 01 F1 + F2 | `23cad6a` |

### Refuted as stated

| Report | Verdict |
|---|---|
| 31 F2 (D21) | The rejected edit already left the task alone. Pinned rather than repaired. |
| 31 F3 (D30) | The import does fail, but it is caught by design. The dead `try` branch was removed and the working rate limit pinned. |
| 01 F1, 01 F2 (D36) | SPEC.md B2, as in pass 1. The real defect underneath: the confirmation press authorised nothing at all. |

## What this pass does NOT say

- **Three sections have never been reviewed by anyone: 13, 26 and 37.**
  Counted on 2026-09-21 out of the coverage tables of the three pass-1
  reports against `SECTIONS.txt`: stage A took 01 02 14 17 18 24 31 32, stage B
  03-11, stage C 12 15 16 19-23 25 27-30 33-36. That is 34 of 37. Missing are
  section 13 (`config_service.py` and the config services, 1,806 lines),
  section 26 (`scheduler.py`, 1,995 lines - the path that starts and stops
  containers on a timetable, without anybody pressing anything) and section 37
  (`token_security.py`, `key_crypto.py`, `performance_metrics.py`).
  Section 38 is not a gap: it was carved out of 32 on 2026-09-21 and its
  content was reviewed as part of it.
- **The first version of this line said "29 of 38 sections have not been
  reviewed in either pass", and `STAGE4_REVIEW.md` said "every section of the
  code base has been read once". Both were wrong, in opposite directions**, and
  neither was checked against the reports until the operator pushed back on a
  recommendation built on them. 26 sections have had exactly one look, 8 have
  had two, 3 have had none.
- So the eight sensitive sections have now been read twice while three
  sections central to configuration, scheduling and token encryption have not
  been read at all. That is the next work, not a release.
- Each of the eight was looked at once more, by one reviewer. A third pass
  would find fewer new things than this one - 29 % overlap after one repeat
  suggests the seam is not exhausted, but it is narrowing.
- 22 of 38 findings were marked "unsure" by the reviewer. That ranking is not
  adopted anywhere; the re-check decides, and two of the four "critical" ones
  were wrong.
- Severity as the reviewer ranked it is not the severity that mattered. The
  two "critical" findings in section 01 were refuted; the finding that
  actually left a visible, permanent failure in Discord (D31, a message stuck
  on "Processing...") was ranked **medium/unsure**.

## What the method produced besides repairs

At least twelve of the thirty-six commits record a **mis-announcement of my
own** - a mutation probe, a waiting test or a full-run total where the number
I announced was not the number I measured (D11, D14, D17, D20, D25, D28, D29,
D31, D32, D33, D34, D35; the count is a floor because the wording varies and
I counted by grep). Each is written into its commit with the reason. Three of
them found a weakness in the test rather than in the code:

- **D31 M2**: the test checked that a message had left "Pending" and never
  which of two messages arrived - the distinction the repair exists for.
- **D33 M1/M3**: the test checked that a label no longer said "no action" and
  never that anything was deleted. A label can lie.
- **D28**: a test case of mine demanded that `1.2.3.4.5` be refused. It is a
  legal DNS name. The code was right.

A probe that comes out at the announced number confirms the fix. A probe that
does not is worth more, because it is usually the test that is wrong - and a
test nobody has tried to break is a test nobody has checked.
