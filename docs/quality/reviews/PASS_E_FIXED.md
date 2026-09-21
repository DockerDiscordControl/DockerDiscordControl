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
| **E24** | **Any button or modal that failed left you staring at a spinner** until Discord said "This interaction failed" — Start, Stop, Restart, mech, Live Logs, task buttons. Nothing in the DDC log either. | py-cord hands view and modal errors to `on_error`, whose default prints to stderr and never answers. DDC defined neither. **The larger half of E14**: 8 slash commands versus 30 views and modals. | `16d0cca` |
| **E17** | **The status display could freeze for good** — stuck on some minute in the past, with nothing in the DDC log to explain it, until the next restart silently fixed it. | py-cord ends a `tasks.loop` permanently on any exception outside five types, and its default error handler is a bare `print()` to stderr. Three of eight loops had no guard; none had an error handler. | `e6538f0` |
| **E15** | **When Docker really went away, you got no explanation** — the finished "🚨 Container Monitoring Unavailable" message, translated into 40 languages, telling you to check the socket mount, never appeared. | `check_connectivity`, whose only job is to *report* reachability, **raised** instead of answering on `DockerConnectionError` — the very case it exists for. | `ef53ca1` |
| **E16** | **The refresh button on a container panel failed** instead of showing that container as unreachable. | Same gap as E15 on the single-container path, which has no connectivity pre-check above it to make up for it. | `da41789` |
| **E28** | **A channel could silently lose its permissions** — one unreadable `channels/*.json` and DDC comes up as if that channel were not configured: no status messages there, commands refused, no reason given. | An unreadable file was skipped and the shorter result was indistinguishable from a complete one. The loss is now stated once, with its consequence and with "nothing was deleted". | `35164a9` |
| **E33** | **A container could vanish from the display entirely** — one unreadable `containers/*.json` and it is gone from `/serverstatus`, the overview and the control panel. Not offline, not "not found": absent, which is exactly what a container you switched off looks like. | Same as E28, one directory across. The loss is now stated once with its consequence. | `f507895` |
| **E21** | **DDC could come up with no container commands at all** — no `/serverstatus`, no buttons — because one JSON file could not be opened. Every start, until somebody worked out that a file recording which mech panels were expanded was the reason. | `load_state` caught a missing and a corrupt file, but not an unreadable one. `PermissionError` is an `OSError`, not a `FileNotFoundError`. A root-owned file has broken this install before. | `880cd5a` |
| **E27** | **Changing a protected password did not take effect for up to an hour.** The old password kept opening the protected information, and the old secret was what got shown — for as long as the status message went without a refresh. | The password was compared against a snapshot taken when the button was built, on a persistent view. It is now re-read when the password is submitted. | `4cecd27` |
| **E12** | **The monthly donation appeal was not sent at all** in a month where the mech's power had run to zero and its state could not be repaired. | The handler around the $1.00 power gift said "continue anyway to send the message" but listed types that did not include `MechStateError`. | `fc3ca28` |
| **E19** | **A donor who pressed Submit could be left at "⏳ Processing…" for ever**, with the public "Processing a $X donation" message never removed. Somebody who has just given money and is told nothing gives again. | Two bare `return`s, and a handler that did not list what the mech service raises. | `449b57c` |
| **E20** | **A broken mech hid your whole container list.** The overview builds the container lines first, then adds the mech on top — and a mech failure took the finished list with it. You lose "is my server up?" because of an animated robot. | The handler around the mech section listed four types, none of them what the mech services raise. **The file already recorded this happening once**, via an `ImportError` that "crashed outright"; that was repaired by fixing the import, not the shape. | `523a1b4` |
| **E23** | **Expanding a mech panel in one channel could delete and repost the overview in another**, moving that message to the bottom with a new id. Which channels it hit looked random. | The edit-or-recreate flag was the function's own parameter, reassigned inside the per-channel loop. The first channel that said "recreate" said it for all the rest, in dictionary order. | `71bf189` |
| **E18** | **Your refresh interval was ignored** when a helper service was unavailable: the overview was edited every minute instead of every 5 / 30 / 60 as configured. | Two branches taking the same decision had two different fallbacks; nobody decided they should differ. | `92fe615` |

| **E26** | **If the bot could not log in, the log said the opposite.** An encrypted token with no Web UI password was handed to Discord as-is, and DDC reported "Successfully decrypted token for usage" — sending you after a wrong token instead of a missing password. | `_decrypt_token_if_needed` fell through to `return token` when there was no password hash. It now answers None and names which of the two situations it is. | `22a93cc` |

| **E34** | **42 messages appeared in English in your German interface** — DDC ships 40 languages and these never went through the translation function at all. The test that guards translations could not see them: it asks whether every translated string has a key, not whether every message is translated. | 14 that cannot change what you do became the generic answer that was already translated (four of them gained the log line they never had); 14 got their own key in all 40 languages. A ratchet test now stops it growing back. | `e1f8994` |

| **E35** | **33 more English texts — this time inside the embeds**, which is most of what you actually read. The guard added for E34 could not see them and reported zero. | My own guard, two hours old, could not fail in the way that mattered. It covers embeds now; all 33 are done (33 → 29 → 24 → 14 → **0**). With E34 that is **75 pieces of user-facing text** that were English in a German interface. | `6488eff` |

| **E36** | **A mistyped placeholder in any of the 40 languages would have crashed where the message is shown** — `{second}` for `{seconds}` raises KeyError, in that language only, which nobody here reads. Nothing checked it. | Every placeholder-bearing key is now formatted in every catalogue. All 1,600-odd pass today. | `d2fcc90` |

## Web panel

| # | What you would have seen | Cause | Commit |
|---|---|---|---|
| **E22** | **Opening the Discord-admin dialog when the admin file could not be read showed "no users configured" — and pressing Save then deleted every admin and every container assignment.** A read error turning into a write that erases what it failed to read. | The route answered a read failure with HTTP **200** and an error body. `fetch()` does not reject on a 200, so the panel read the error as an empty admin list. | `8d9ab03` |

| **E25** | **A container you stopped on purpose could be restarted by an Auto-Action** — the "only if running" switch was silently not honoured when the container's state could not be read, and nothing anywhere said so. | Three-state answer, two-state check: only a confirmed "not running" skipped. **Semantics unchanged, and since confirmed by the operator** ("commands take priority"); what was fixed is the silence. | `80657ac` |

| **E29** | **A config file edited by hand could go on being ignored** — change a channel permission directly in `config/channels/` and DDC keeps serving the old configuration until a restart. | The cache checked only the mtime of `config/`, which does not move when a file in a subdirectory changes. No live defect (every save path invalidates explicitly, and bot and panel are one process) — a trap for hand edits and for the next save path. Its cost was measured afterwards: +49 µs per `load_config`, which is one call per embed. **Corrected 2026-09-21:** that was first put at 0.05% of "the 96 ms an embed takes" — 96 ms was a COLD measurement including service initialisation. Warm, with the real containers, an overview embed takes **3.8 ms**, so it is about 1.3%. Still nothing, but the first number was wrong and a review record that quietly fixes its own figures is worth less than one that shows them. See E30. | `c490916` |

| **E30** | **Every label DDC writes re-read the whole configuration.** `_()` — behind every embed label, button and message — deep-copied a 361-key, 19 KB config to look up one key. Measured: 18.1 µs per call, 16.5 of them load_config. Now **0.2 µs**, ninety times faster. | The language is cached for five seconds instead of re-read per string. Found because **E29 was a 4× regression on that same path** and only measuring showed it. | `` |

| **E31** | **1.2 seconds off every start.** Importing any service imported five of them, because the package re-exported names that nothing in the codebase uses. Measured before: 1199 ms and 23 modules. After: **0 ms, 0 modules.** | It also meant an ImportError in the mech service made `services.config` unimportable — a mech problem becoming a config problem, one layer below E8. | `b269adf` |

| **E32** | **Every message on the server cost two config file reads.** Anyone typing anything, in any channel, made DDC open and parse `channel_translations.json` twice — to work out the message had nothing to do with it. Measured: 0.20 ms and 2.0 reads per message. | The translation monitor listens to every message and the config had no cache. Now cached on the file's mtime, handing out a copy so a failed save cannot leave a phantom setting in memory. **Verified after deploying: 0.066 ms and 0 file opens per message.** | `574b913` |

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
