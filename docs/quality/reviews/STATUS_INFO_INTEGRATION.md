# `cogs/status_info_integration.py` — the status-channel interface (2026-09-21)

**What the evidence said, before today:**

    cogs/status_info_integration.py    2396    NONE

2,396 lines holding everything a status channel offers after the overview is
posted: the info button, protected info, live logs, and the whole task
management flow. In no review package ever - although parts of it were repaired
blind by earlier findings (B3, F2, F3 and the spam-protection corrections of
stage C), which is why it reads better than its coverage line suggested.

## Findings

| # | What | Commit |
|---|---|---|
| E24 | **Every button and modal in DDC hung on failure.** Found here, but not a defect *of* here: py-cord hands view and modal errors to `on_error`, whose default prints to stderr and never answers. DDC defined neither. 25 views, 5 modals. | `16d0cca` |

E24 is written up in `PASS_E_FIXED.md` and in its own commit; it is listed here
because this is the file that led to it. Reading `ProtectedInfoButton.callback`
raised the question "and what happens if this raises?", and the answer was two
files away in py-cord.

## Put to the operator, and decided by them

**The protected-info EDIT modal shows the password in clear text.** Two buttons
sit on the same information and answer differently:

| Button | Shows | Asks for the password? |
|---|---|---|
| 🔒 view protected info | the content | **yes** - `PasswordValidationModal` |
| ✏️ edit protected info | the content **and the password**, both prefilled in clear text (`enhanced_info_modal_simple.py:390`) | **no** - control permission is enough |

The operator had already set the principle earlier the same day, answering
"A": *a set password always wins over control permission.* This is the one
place it is not applied.

Measured before asking, so the trade-off was real and not assumed: the web
panel holds the password in a text field
(`_server_selection.html:295`), so applying the rule here could not lock anyone
out - the panel remains the way back.

**The operator decided on 2026-09-21: leave it as it is.** Whoever may control
a container may also edit its protected information, and sees the password
doing so. Recorded so the next reader finds a decision rather than an
oversight.

## Checked and found sound

- **`_auto_refresh_loop` and `_auto_recreation_loop`** (`LiveLogView`) are
  bare `asyncio.create_task`, which is the shape that made E17 so bad
  elsewhere. They are safe here for a reason worth writing down:
  `container_logs_text` handles its own failures and always returns a string,
  so the loop body has nothing to raise. The `message_ref.edit` failure path
  breaks the loop and then runs the cleanup that resets the buttons, so the
  footer does not keep promising refreshes that will not come.
- **`CreateTaskButton.callback`** carries the permission check at creation
  time (SPEC.md B2/Z5, review B3) and the per-admin container check (F2), and
  answers in every branch including the two error ones.
- **`ProtectedInfoEditButton`** carries the F3 check, so an assigned admin
  cannot open somebody else's container.
- **Both mechanical scans over the whole file: nothing.** The four
  falsy-answer hits are early returns on an expired interaction, which is the
  correct thing to do - there is no interaction left to answer.

## What this file has not had

The dropdown classes (`CycleDropdown`, `ActionDropdown`, `MonthDropdown`,
`YearDropdown`, `TimeDropdown`, `WeekdayDropdown`, `SimpleMonthdayDropdown`)
were not read line by line; they were covered by the two scans only.
`DebugLogsButton.callback` (119 lines) and `TaskManagementButton._show_task_list`
likewise. The coverage ledger records what was read and not the file.
