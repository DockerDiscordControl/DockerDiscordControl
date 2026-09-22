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
| **E53** | **One container whose image had been removed emptied the entire container list** — no containers to select in the web panel, "Refresh" failing every time, and running servers reported as not found in Discord. Reported by a user on GitHub against v2.3.1. | `container.image` is a second request to Docker, not a stored field; a removed image answers 404, and the one error failed the whole refresh. Three places read it, each broke differently. The image name now comes from `attrs['Config']['Image']`, which Docker already sends — it cannot 404, and it saves one API call per container. Each of the three sites probed separately. | `aff5ae6` |
| **E14** | **A slash command that failed just hung.** No error, no reply — the command sat at "thinking" until Discord gave up. Same for a cooldown: you pressed the button, got nothing, and pressed again. | `events.py` registered `on_command_error`, which in py-cord is the **prefix**-command event. DDC has no prefix commands. Slash errors go to `application_command_error`, where py-cord's default prints to stderr and never answers. | `96cfd27`, `5abc322` |
| **E24** | **Any button or modal that failed left you staring at a spinner** until Discord said "This interaction failed" — Start, Stop, Restart, mech, Live Logs, task buttons. Nothing in the DDC log either. | py-cord hands view and modal errors to `on_error`, whose default prints to stderr and never answers. DDC defined neither. **The larger half of E14**: 8 slash commands versus 30 views and modals. | `16d0cca` |
| **E17** | **The status display could freeze for good** — stuck on some minute in the past, with nothing in the DDC log to explain it, until the next restart silently fixed it. | py-cord ends a `tasks.loop` permanently on any exception outside five types, and its default error handler is a bare `print()` to stderr. Three of eight loops had no guard; none had an error handler. | `e6538f0` |
| **E43** | **Stop, start and restart raised instead of answering when Docker was unreachable** — and so did the container list, the existence check and the three diagnostics. Seven functions that promise a value gave an exception instead. | Same sentence as E15/E16, found by running the scan over **all 183 files** instead of the 22 no pass had covered. The scanner itself had a false-positive bug; fixed in the same commit (86 hits → 38). | `ad94767` |
| **E44** | **The container status service raised instead of returning its own failure result** when Docker was unreachable — the result type with `error_type` and `error_message` that every caller knows how to read was never produced. | Fourth place for the same sentence. The file did not even import the exception class. | `815a0ab` |
| **E45** | **Every start, stop and restart handed back an exception instead of a result** when Docker was unreachable — including the admin overview's bulk buttons and the scheduler at four in the morning. The handler's own comment promised "a clean failure instead of an exception". | Fifth place for the same sentence, and the first where the code had already written down what it was meant to do. One fix cleared **nine** scan hits. | `515f35b` |
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

| **E37** | **Your 26th container would simply not be in the dropdown** — not shown, not reachable from Discord, and indistinguishable from a configuration that only has 25. (You run 7, so this is for everyone else.) | Discord's limit is 25 and is not negotiable. The dropdown now says "(25/30)" and the log names the ones left out. Paging is the real answer and is **a question for you** in `reviews/CONTROL_UI.md`. | `147afb1` |

| **E38** | **Five more English texts**, behind a third blind spot in the same guard: `embed.description = "..."` rather than `Embed(description=...)`. One of them is the message shown when the configuration cannot be loaded — the one you are most likely to meet on a bad day. | The guard has now been widened **twice after reporting zero**, and its docstring says so. Both times a hand-read found what it could not see. | `97c3298` |

| **E39** | **Nine more, including your `/help` text** — bold English labels wrapped around German values ("**Container Control:** Klicke auf …"), six raw "Create Task:" titles while the correct key sat two functions away, and the footer under protected information naming the reader in English. | The guard judged an f-string by its fragments, so `f"❌ Container '{name}' not found"` was two invisible crumbs. It judges the whole message now. | `1ec59cc` |

## Web panel

| # | What you would have seen | Cause | Commit |
|---|---|---|---|
| **E55** | **"Encrypt token" reported success and changed nothing.** The security panel didn't see the token either. Anyone who pressed it believed their token was protected. | The button read the v1 files `bot_config.json`/`web_config.json`, which no v2 install has. Found by the v2.3.1 upgrade test. Now encrypts in `config.json`, checks the round trip before writing, and only on request - your decision: nothing is encrypted at startup. 22 older tests rebuilt on the real storage; several had passed without reaching their code. | `80a1780` |
| **E54** | **Every save in the web panel reset the server order to 999.** Status messages stayed in order, the admin overview and both dropdowns lost it. | The parser read the order from a form field no template has ever rendered - v2.3.1 did the same. It now takes the order from `server_order`, which the page always sends. Your own install would have lost its orders 0-10 at the next save. | `09429b1` |
| **E22** | **Opening the Discord-admin dialog when the admin file could not be read showed "no users configured" — and pressing Save then deleted every admin and every container assignment.** A read error turning into a write that erases what it failed to read. | The route answered a read failure with HTTP **200** and an error body. `fetch()` does not reject on a 200, so the panel read the error as an empty admin list. | `8d9ab03` |

| **E25** | **A container you stopped on purpose could be restarted by an Auto-Action** — the "only if running" switch was silently not honoured when the container's state could not be read, and nothing anywhere said so. | Three-state answer, two-state check: only a confirmed "not running" skipped. **Semantics unchanged, and since confirmed by the operator** ("commands take priority"); what was fixed is the silence. | `80657ac` |

| **E29** | **A config file edited by hand could go on being ignored** — change a channel permission directly in `config/channels/` and DDC keeps serving the old configuration until a restart. | The cache checked only the mtime of `config/`, which does not move when a file in a subdirectory changes. No live defect (every save path invalidates explicitly, and bot and panel are one process) — a trap for hand edits and for the next save path. Its cost was measured afterwards: +49 µs per `load_config`, which is one call per embed. **Corrected 2026-09-21:** that was first put at 0.05% of "the 96 ms an embed takes" — 96 ms was a COLD measurement including service initialisation. Warm, with the real containers, an overview embed takes **3.8 ms**, so it is about 1.3%. Still nothing, but the first number was wrong and a review record that quietly fixes its own figures is worth less than one that shows them. See E30. | `c490916` |

| **E30** | **Every label DDC writes re-read the whole configuration.** `_()` — behind every embed label, button and message — deep-copied a 361-key, 19 KB config to look up one key. Measured: 18.1 µs per call, 16.5 of them load_config. Now **0.2 µs**, ninety times faster. | The language is cached for five seconds instead of re-read per string. Found because **E29 was a 4× regression on that same path** and only measuring showed it. | `` |

| **E31** | **1.2 seconds off every start.** Importing any service imported five of them, because the package re-exported names that nothing in the codebase uses. Measured before: 1199 ms and 23 modules. After: **0 ms, 0 modules.** | It also meant an ImportError in the mech service made `services.config` unimportable — a mech problem becoming a config problem, one layer below E8. | `b269adf` |

| **E32** | **Every message on the server cost two config file reads.** Anyone typing anything, in any channel, made DDC open and parse `channel_translations.json` twice — to work out the message had nothing to do with it. Measured: 0.20 ms and 2.0 reads per message. | The translation monitor listens to every message and the config had no cache. Now cached on the file's mtime, handing out a copy so a failed save cannot leave a phantom setting in memory. **Verified after deploying: 0.066 ms and 0 file opens per message.** | `574b913` |

| **E41** | **A dict claiming to count loop runs and failures, that nothing ever wrote to or read.** Anyone reading it would conclude DDC tracks loop health — and E17 is what actually happened when a loop died. Three more dead attributes went with it. | No symptom; a misleading artifact removed. The probe is in the commit, including why an attribute scan alone would have deleted a live one. | `e8b583c` |

| **E42** | **The admin panel header was built twice**, the first one thrown away — and the discarded version was the one that would have shown you `Online: {online}` in words if the rebuild ever stopped running. | No symptom today. The waste is gone and the outcome is pinned by a test that was probed the other way round: deleting the rebuild turns it red. | `fafe61f` |

| **E46** | **The log tabs in the web panel answered with Flask's HTML error page** when the log files were missing and Docker was unreachable — markup in the log pane at the exact moment you opened it to find out what was wrong. Bot, Discord, Web UI and Application, all four. | Sixth place for the same sentence as E15/E16/E43/E44/E45. C18 had already fixed it for the *other* entry point and left this one, the one the panel actually uses. One handler, **six** scan hits closed (20 → 14). | `dd601a3` |

| **E47** | **Three async log helpers that nothing calls** — and one of them answers every Docker failure with `None`, which is precisely the defect C18 removed from the live path twenty lines above. Its name says it is the modern one, so reconnecting it is the obvious move, and it would bring C18 back. | No symptom today; a trap removed, 52 lines. The guard is not "no dead code" but "every private helper is reachable from something the service offers" — it fails on the next orphan too. Scan 14 → 12. | `6f99ad0` |

| **E50** | **A stop timeout that goes missing without a word.** `get_stop_timeout_kwargs` answers `{}` both when no StopTimeout is configured *and* when the container object cannot be read — and `{}` makes docker-py's `restart()` fall back to ten seconds, overriding whatever the container has. It sits on **every** stop and restart: buttons, admin overview, scheduled tasks. Valheim, Satisfactory and V-Rising all write their world on shutdown. | Low probability, high damage, and a diagnosis nobody could make — there was no line anywhere pointing at DDC. The silent branch now names the container and says what it fell back to. Found by filtering the 219 falsy-answer hits down to the 24 that log nothing; 23 of those were correct. | `9c0b3e2` |

| **E37b** | **The container dropdowns now page.** E37 made the cut visible — "(25/30)" plus a log line naming the five you could not reach. You still could not reach them. Both dropdowns now page through the whole list, the way the day picker has paged through a month's 31 days since B21. | A feature, asked and answered. Nothing changes for your seven containers: no arrows, no marker, no log line below 26. It changes everything for anyone who installs DDC and runs more than twenty-five. | `8a61947` |

## Under the floor — no symptom yet, but a trap

| # | What | Commit |
|---|---|---|
| **E13** | The two donation-key helpers raised instead of returning the `bool` they promise. No production caller today, so nothing was broken — pinned so the first caller is not the one who finds out. | `0927d2a` |

| **E48** | The Docker client pool's SERVICE FIRST entry point raised instead of returning its result when Docker was unreachable — on **both** of its paths. The return type exists to carry a failure as a value; the failure was never counted in the pool's own statistics either. No production caller today, so nothing was broken. C33 had taught the queue processor to tell the waiting request what happened — and the telling then walked out of the building. | `b40c6c9` |

| **E49** | `get_docker_stats` and `get_docker_info` raised instead of returning the `(None, None)` / `None` their signatures promise. E43 repaired their neighbour forty lines away and left these two. The one live caller already guards with `except Exception`, so nothing was broken. | `8dd62c8` |

| **E49b** | Fixing E49 would have made the performance report **worse**: the unreachable daemon used to arrive there as an exception object and was written down as "Info error: …". Answering None instead meant the report listed a container nobody could reach with a timing and no errors — reading as healthy. The report now reads the None. Found because the test asked for the error text, not just for a dict. | `8dd62c8` |

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
