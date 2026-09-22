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
| E37 | **The 26th container is not in the dropdown and nothing says so.** | `147afb1` |

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

## Answered by the operator (2026-09-22): built

**Should the container dropdowns page, like the day picker already does?**
Yes. `E37b`.

Both dropdowns now page. `_page_of` / `_page_arrows` / `_turn_page` in
`control_ui.py` follow `SimpleMonthdayDropdown` (`status_info_integration.py`,
review B21): the arrows carry numbers only, so they need no entry in the forty
catalogues, and turning a page swaps the select inside the same view rather
than rebuilding the message.

23 containers per page, not 24: every page has room for both arrows, so page
boundaries are identical whichever direction the operator arrives from. Page 1
could hold one more, and then "previous" from page 2 would land somewhere
other than where page 1 started.

|  | before | now |
|---|---|---|
| ≤ 25 containers | unchanged | unchanged - no arrows, no marker, nothing in the log |
| > 25 containers | the rest unreachable from Discord, and the dropdown said so | all reachable, one extra click |

The guarantee is one sentence and the test is named after it: **every
container in the list is reachable from some page.** `containers[:25]` can
never satisfy it. Reverting the page slice to a plain cut turns 10 of the 16
cases red.

`test_a_container_beyond_the_limit_is_not_hidden.py` is retired with this: it
pinned E37's warning about what was being dropped, and there is nothing left
to drop. Its counter-check - a list that fits is left completely alone - moved
into the new file.

`control_helpers.container_select` is deliberately NOT paged: it is a Discord
autocomplete, where narrowing by typing is how the interface works.

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

## A shape closed with no defect behind it (E40)

Button labels and select placeholders were the fifth shape the translation
guard did not watch, and a label is read exactly like any other text. Measured:
**one** hit in the whole project, `label="Mech"` — and that is the robot's
name, not a word to translate, in the same way "Docker" is not translated.

So the guard covers labels now and `PROPER_NOUNS` holds DDC's own names with
the reason written beside them. No defect was found and none is claimed; what
changed is that an English label added tomorrow will be.

Worth stating plainly because this review has widened that guard five times:
**four of those widenings found real defects and the fifth found nothing.**
A guard that only ever gets wider when something is already broken is a guard
that arrives late every time.

## Logic, read and found sound

- **`MechDetailsButton`** builds a cache-busting filename from the level and
  the power (`mech_level_3_power_12.50.webp`), which is right - Discord caches
  attachments by name, and without the power in it an evolving mech would keep
  showing yesterday's picture. `power_decimal` is a float with a `0.0` default
  on the result dataclass, so the `:.2f` cannot meet a `None`.
- **`MechExpandButton` / `MechCollapseButton`** take the interaction lock
  through `_start_interaction`, release it in a `finally`, and return without
  releasing only on the path where they never took it. Their spam-protection
  keys carry three earlier corrections and the reasons are written next to
  them.
- The `_`-shadowing comment in `MechExpandButton` describes exactly the
  mistake I then made twice myself today (reviews E34 and E38). It was already
  written down; I did not read it before editing.

## What this file still has not had

The story and song buttons (`ReadStoryButton`, `PlaySongButton`,
`EpilogueButton`), `MechDisplayButton` and the sequential animation sending in
`_create_mech_history_display` were read for their text and their handlers,
not for their logic line by line.
