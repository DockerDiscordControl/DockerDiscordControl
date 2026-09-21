# `cogs/docker_control.py` — the file no pass ever covered (2026-09-21)

**What the evidence said, before today** (`docs/quality/COVERAGE_BY_FILE.txt`):

    cogs/docker_control.py    5294    NONE

5,294 lines, the largest file in DDC, holding the status display, every slash
command and eight background loops — and not one review package ever contained
a line of it.

Read by hand, in the loops first, plus the falsy-answer scan.

## Findings

| # | What | Commit |
|---|---|---|
| E17 | **A single bad cycle ended a background loop for the rest of the run**, silently. py-cord retries only five exception types and stops the loop on anything else, with a bare `print()` to stderr. Three of eight loops had no guard, including the status display refresh; no loop had an error handler. | `e6538f0` |
| E18 | A broken decision service made the overview refresh **every minute** instead of at the operator's interval — up to sixty times what they asked for — while the admin overview, taking the same decision three lines further down, kept to it. | `92fe615` |

### Why E17 is the worst shape a defect can have

Measured in the shipped py-cord (`ext/tasks/__init__.py`):

| line | what |
|---|---|
| 103 | `_valid_exception = (OSError, GatewayNotFound, ConnectionClosed, aiohttp.ClientError, asyncio.TimeoutError)` |
| 171 | only those are retried |
| 195 | anything else: `_has_failed = True`, call the error handler, re-raise — **the loop is over** |
| 474 | the default error handler is `print(..., file=sys.stderr)` |

So `periodic_message_edit_loop` — which begins with `load_config()`, which
raises `ConfigServiceError` — could stop for good on one unreadable config
read, and DDC's own log would never say so. The operator would see a status
display frozen at some minute in the past, with nothing anywhere explaining
it, until the next restart silently fixed it.

Both halves are now closed, because they answer different failures: the
decorator keeps a bad *cycle* from being fatal, and the error handler makes a
loop that dies anyway say so through DDC's logger. The test reads the loops off
the class, so a loop added tomorrow is checked today.

## Noted, not repaired

**An unreachable `except discord.NotFound`, disagreeing with the one that
fires.** In `_update_overview_message`:

```python
try:
    message = channel.get_partial_message(message_id)  # No API call
except discord.NotFound:
    ...delete the message from tracking...
    return False
```

Measured in `discord/channel.py:588`: `get_partial_message` constructs a
`PartialMessage` and returns it. No `await`, no HTTP, so it cannot raise
`NotFound` and that handler has never run.

What makes it worth writing down rather than just deleting: the `NotFound`
that *does* happen — on `message.edit()` sixty lines below — is caught by the
outer handler, which does the **opposite**. It recreates the message
(`_recover_deleted_overview`). So the file contains two answers to "this
message is gone", they contradict each other, and the dead one is the one that
gives up.

Not deleted here. Removing dead code needs a probe of its own, and that is
exactly how `dfa3662` broke the panel's JavaScript (review E2): the commit
message said *"No mutation probe: nothing can turn red when dead code is
deleted"*, and the reasoning was wrong.

## What this file still has not had

The read went to the loops first, because a silent permanent stop is the
failure an operator cannot see. What is still unread, in lines:

- `_create_overview_embed_expanded` (379), `_create_overview_embed_collapsed`
  (237), `_create_admin_overview_embed` (199) — what the operator actually
  looks at;
- `DonationBroadcastModal.callback` (316) — money;
- `_auto_update_ss_messages` (213), `_update_all_overview_messages_after_donation`
  (158);
- `__init__` (231), and the eleven numbered startup steps inside it;
- the slash commands other than `serverstatus`.

The ledger records the three loop bodies and nothing else, which is the
honest entry.
