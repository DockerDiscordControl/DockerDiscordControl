# Review task - section {SECTION} (commit {COMMIT})

You review one section of DDC (DockerDiscordControl): a Discord bot plus a web
panel that start, stop and restart Docker containers, and keep a donation
ledger. You did not write this code.

## Your material - and nothing else

This directory holds everything you may use:

- `source/` - the code of this section. Each file is one piece of a
  repository file; the numbers in front of every line are the REAL line
  numbers in that repository file, and the header names its path.
- `SPEC.md` - what DDC promises: the guarantees **Z1-Z10**, and the
  **deliberate decisions B1-B13** (things that look like a bug but are
  intended - do NOT report those as findings; you may say where the code
  contradicts one).
- `PLAN.txt` - the check plan: every public name of this section,
  {NAMES} names, as `path:line name`.

Read only files in this directory. Do not open other files, do not search
the web, do not run the code. Where something depends on code you cannot
see, say so - do not guess what it does.

## What to deliver

Write `REPORT.json` into THIS directory:

```json
{
  "section": "{SECTION}",
  "verdicts": [
    {"name": "<exactly as in PLAN.txt>", "verdict": "checked"},
    {"name": "...", "verdict": "finding", "finding": "F1"},
    {"name": "...", "verdict": "not_checked", "reason": "why not"}
  ],
  "findings": [
    {
      "id": "F1",
      "file": "<repository path as in the source header>",
      "line": 123,
      "trigger": "concrete input or state -> what happens",
      "suggestion": "what to change",
      "severity": "critical | high | medium | low",
      "certainty": "sure | unsure",
      "unsure_why": "only if unsure: what you could not tell apart"
    }
  ],
  "notes": "anything that does not fit above"
}
```

Rules:

1. **Every name in PLAN.txt gets exactly one verdict**, spelt exactly as in
   the plan. "checked" means you read it and found nothing. "not_checked"
   needs a reason. Do not add names that are not in the plan.
2. **A finding needs a trigger you can state**: "with this input / in this
   state, this happens". No trigger, no finding - put it in "notes".
3. **Rank by whether the user would notice, not by how technical it
   sounds.** An error that fails loudly is less severe than one that
   delivers a wrong result and reports "done". If in doubt, rank higher.
   - critical: money, data or a container is lost, or someone acts without
     the right - and nobody notices
   - high: a wrong result or a silent failure the user will believe
   - medium: a visible failure, or wrong behaviour in a rare case
   - low: everything else that is still a real defect
4. **Say when you are unsure.** "Unsure whether this is a finding or
   intended" is a valuable answer. A reviewer who is never unsure has not
   read closely.
5. Look especially at: values that are silently "tidied up" (a default
   that hides a failure, a broad `except`, a filter that drops entries);
   two places that do the same thing and may drift apart; a function that
   is right but called wrongly, too late or not at all; comments that
   promise more than the code does.
6. No style, naming or formatting findings. No refactoring wishes.

When done, reply with three lines: number of verdicts, number of findings,
and the one finding you consider most serious.
