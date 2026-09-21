# `cogs/control_ui.py` — the half nobody had read (2026-09-21)

**What the evidence said:**

    cogs/control_ui.py    3639    pass1:s02:plan pass2:s02:1-1900

Lines **1901-3639 were in no package at all** — 1,739 lines holding the whole
mech interface: the admin container dropdown, the expand and collapse buttons,
the donation buttons, the evolution chronicle, the story and song buttons.

## Findings

| # | What | Commit |
|---|---|---|
| E34/E35 | 75 pieces of user-facing text appeared in English in a German interface, 39 of them in this file. Written up in `PASS_E_FIXED.md`. | several |
| E37 | **The 26th container is not in the dropdown and nothing says so.** | `TBD` |

### E37, and the shape of it

Both container dropdowns built their options with `containers[:25]`, because
that is Discord's hard limit on a select. Everything past the twenty-fifth was
dropped in silence — not in the dropdown, not in the log.

An operator running thirty containers opens the admin panel, sees twenty-five,
and **cannot control the other five from Discord at all.** It looks exactly
like a configuration that only has twenty-five containers in it.

Fixed as far as a repair can go: the placeholder now reads
`Select a container to control... (25/30)` and a warning names the containers
that were left out. The marker is numbers on purpose — "(25/30)" needs no
translation and means the same in all forty languages.

Also quieted while there: the admin dropdown wrote **two INFO lines per
container** — once before sorting and once after — every time the panel was
opened, under a header that calls itself "Debug". Fourteen lines for one click
on a seven-container install. They are DEBUG now.

## ⚠️ One question for the operator

**Should the container dropdowns page, like the day picker already does?**

Discord's limit is 25 and it is not negotiable. This project has already met
it once and answered it properly: `SimpleMonthdayDropdown`
(`status_info_integration.py:1744`) pages through a month's 31 days, with the
comment *"Discord shows at most 25 options in one select, and a month has 31
days"*.

So the pattern exists and could be applied here. It is a **feature**, not a
repair, which is why it was not built unasked:

|  | today | with paging |
|---|---|---|
| ≤ 25 containers | unchanged | unchanged |
| > 25 containers | the rest are unreachable from Discord, and the dropdown says so | all reachable, one extra click |

The operator runs seven containers, so nothing here affects them today. It
affects anyone who installs DDC and runs more than twenty-five.

## Checked and found sound

- **`ActionButton.callback`** — start, stop and restart, the most consequential
  button in DDC. Its handlers carry reviews D17 and D31, the inner ones are
  `except BaseException`, and the outer one takes the pending mark back and
  **re-raises** rather than swallowing. That re-raise reaches `DDCView.on_error`
  since review E24, so the user is answered and the failure is logged. A scan
  hit here turned out to be exactly right as written.
- **`MechPrivateDonateButton` / `MechPrivateHistoryButton`** delegate to the
  full buttons and let a DDC exception through; E24 catches it at the view.
- Both mechanical scans over the whole file: nothing beyond the above.

## What this file still has not had

The story and song buttons (`ReadStoryButton`, `PlaySongButton`,
`EpilogueButton`), `MechDisplayButton` and the sequential animation sending in
`_create_mech_history_display` were read for their text and their handlers,
not for their logic line by line.
