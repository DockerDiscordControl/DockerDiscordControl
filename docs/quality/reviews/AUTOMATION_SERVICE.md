# Auto-Actions — `services/automation/` (2026-09-21)

Four files, 1,626 lines, none of them in any review package. Read by hand
around the two mechanical scans.

## Findings

| # | What | Commit |
|---|---|---|
| E25 | The **"only if running" safety switch could be silently not honoured.** When a container's state cannot be determined, the action runs anyway - so a container the operator stopped on purpose gets RESTARTed, which is exactly what the switch exists to prevent - and nothing said so. | `80657ac` |

## ⚠️ One question for the operator, deliberately left open

**Should an undeterminable container state skip the action, or run it?**

An Auto-Action rule can carry `only_if_running`. The code's own comment says
what it is for: *"don't touch a container that was stopped on purpose."* It
guards `{"RESTART", "RECREATE", "STOP"}`.

`_get_running_state` has three answers - True, False, and **None** when
`get_docker_info` raised or came back empty. Today only a confirmed `False`
skips, so **None runs the action**.

|  | fail open (today) | fail closed |
|---|---|---|
| Docker briefly unreachable | the action runs | the automation silently does not work |
| Container stopped on purpose, state unreadable | **it comes back up** | it stays stopped |

This was chosen deliberately - the line saying so is in the source, and has
been since before this review - and it is a real trade-off, not an oversight.
It is also the opposite of what review E6 decided for the scheduler, where a
container configuration that could not be read now **refuses** the action
(SPEC.md B14). The two subsystems answer the same question differently, and
nobody has decided that they should.

**Not changed without the operator.** What was changed is that the moment is
now visible: a WARNING naming the rule, the container and the action, ending
with *"If that container was stopped on purpose, this is why it came back."*

## Noted, not repaired

- **`trigger_count` is written and never read.** `increment_trigger_count`
  maintains `rule['metadata']['trigger_count']` and `last_triggered`, and
  nothing anywhere reads either. So its `False` return - one of the
  falsy-scan hits - costs nothing, which is why it is a note and not a
  finding. Worth knowing before somebody builds a rate limit on top of a
  counter that may quietly not advance.

## Checked and found sound

- `_safe_regex_search` answers `False` on a failed or timed-out pattern. Falsy
  here means "did not match", so the rule does not fire - a failure that
  REFUSES, which is the safe direction (the distinction review E6 drew).
  The 0.5 s budget is enforced by killing a worker process, not by a timeout
  that a catastrophic backtrack would ignore.
- Every other falsy-scan hit in these files is a `save_*` / `delete_*` /
  `_update_*` returning `False` on a write failure, where the caller refuses
  and nothing is lost by refusing.
- The DDC-exception scan finds nothing in these files.
