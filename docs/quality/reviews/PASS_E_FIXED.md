# What pass E fixed — in plain terms (running list)

Kept up to date as the pass runs, not written from memory afterwards. One line
per finding: **what the operator would have seen**, then the technical cause.
Commits are one per finding.

A hash in the last column is written in a follow-up commit, never in the one it
names - amending to insert it changes the hash it just recorded.

Pass E is the read of the files that no earlier pass ever covered
(`docs/quality/COVERAGE_BY_FILE.txt`), plus two mechanical scans
(`SCANS_2026-09-21.md`).

---

## Discord — what you see in the chat

| # | What you would have seen | Cause | Commit |
|---|---|---|---|
| **E14** | **A slash command that failed just hung.** No error, no reply — the command sat at "thinking" until Discord gave up. Same for a cooldown: you pressed the button, got nothing, and pressed again. | `events.py` registered `on_command_error`, which in py-cord is the **prefix**-command event. DDC has no prefix commands. Slash errors go to `application_command_error`, where py-cord's default prints to stderr and never answers. | `96cfd27`, `5abc322` |
| **E17** | **The status display could freeze for good** — stuck on some minute in the past, with nothing in the DDC log to explain it, until the next restart silently fixed it. | py-cord ends a `tasks.loop` permanently on any exception outside five types, and its default error handler is a bare `print()` to stderr. Three of eight loops had no guard; none had an error handler. | `e6538f0` |
| **E15** | **When Docker really went away, you got no explanation** — the finished "🚨 Container Monitoring Unavailable" message, translated into 40 languages, telling you to check the socket mount, never appeared. | `check_connectivity`, whose only job is to *report* reachability, **raised** instead of answering on `DockerConnectionError` — the very case it exists for. | `ef53ca1` |
| **E16** | **The refresh button on a container panel failed** instead of showing that container as unreachable. | Same gap as E15 on the single-container path, which has no connectivity pre-check above it to make up for it. | `da41789` |
| **E12** | **The monthly donation appeal was not sent at all** in a month where the mech's power had run to zero and its state could not be repaired. | The handler around the $1.00 power gift said "continue anyway to send the message" but listed types that did not include `MechStateError`. | `fc3ca28` |
| **E19** | **A donor who pressed Submit could be left at "⏳ Processing…" for ever**, with the public "Processing a $X donation" message never removed. Somebody who has just given money and is told nothing gives again. | Two bare `return`s, and a handler that did not list what the mech service raises. | `449b57c` |
| **E20** | **A broken mech hid your whole container list.** The overview builds the container lines first, then adds the mech on top — and a mech failure took the finished list with it. You lose "is my server up?" because of an animated robot. | The handler around the mech section listed four types, none of them what the mech services raise. **The file already recorded this happening once**, via an `ImportError` that "crashed outright"; that was repaired by fixing the import, not the shape. | `523a1b4` |
| **E18** | **Your refresh interval was ignored** when a helper service was unavailable: the overview was edited every minute instead of every 5 / 30 / 60 as configured. | Two branches taking the same decision had two different fallbacks; nobody decided they should differ. | `92fe615` |

## Under the floor — no symptom yet, but a trap

| # | What | Commit |
|---|---|---|
| **E13** | The two donation-key helpers raised instead of returning the `bool` they promise. No production caller today, so nothing was broken — pinned so the first caller is not the one who finds out. | `0927d2a` |

## Refuted while reading — not repaired, because there was nothing wrong

- **`new_state.Power` / `new_state.level`** in the donation modal looked like
  typos: `ProgressState` has `power_current` and `level`, no `Power`. Measured
  on the wrong object — the modal receives a `MechState`
  (`mech_service_adapter.py:37`), which carries both as backward-compatibility
  properties. Correct as written.
- **`configuration_save_service.py`** really does let a `ConfigSaveError` escape
  the handler a scan pointed at — and catches it one frame up, in a handler
  whose comment already names `save_config` as its source. The hit is real and
  the code is correct.
- **`config_service.py:499/506`** — `TokenEncryptionError` is a
  `ConfigServiceError`, so it lands in the panel's own handler, and it is
  raised before anything is written. Nothing is half-saved.
- **`save_spam_protection`** — a false positive of the scan's name matching:
  `spam_service.save_config` is a different method that raises nothing.

## Noted, not repaired

- An unreachable `except discord.NotFound` in `_update_overview_message` whose
  live counterpart sixty lines below does the **opposite**: one gives the
  message up, the other recreates it. Measured — `get_partial_message` makes no
  API call, so the dead one has never run. Deleting dead code needs a probe of
  its own; that is exactly how `dfa3662` broke the panel's JavaScript.
- `_save_server_order` writes the server order file *before* the main config
  save, so a failed save leaves the order already changed.
