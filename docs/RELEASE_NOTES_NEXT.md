# DDC v2.4.0 — Audit release

> Text for the GitHub release page. The version bump is done: `ENV DDC_VERSION` in
> the Dockerfile, the README title and badge, and `docs/CHANGELOG.md`. The entrypoint banner, the
> Web UI footer and `/health` all read that one Dockerfile value — a rebuild is required for it
> to take effect, since the value is baked into the image.

This release comes out of a complete audit of DDC: every subsystem was reviewed, then a second
review pass looked specifically at what changes for **existing installations** on upgrade.
**185 findings were fixed** and the test suite now stands at **5,699 tests**.

Every source file in the project carries written evidence that it was read — 183 of 183. That
includes `cogs/docker_control.py`, the largest file in DDC at 5,400 lines, which no earlier
review package had ever covered.

---

## ⚠️ Upgrade notes — please read

- **You will be logged out once.** The Flask secret key is now stored permanently
  (`config/.flask_secret_key`) instead of being regenerated on every start, and the session
  cookie was renamed to `ddc_session`. Log in again and **reload open browser tabs** — the first
  save from a stale tab fails with a "session expired" message.
- **Long-dead scheduled tasks are paused, not resurrected.** A bug made a recurring task stop
  forever once a single run was missed (host down, slow check cycle), while the Web UI still
  showed it as active. That is fixed — but reviving months-old tasks on upgrade would fire
  surprise restarts. So on first start, tasks that are long overdue are deactivated once and
  marked in the Web UI with a note saying when they last ran. The thresholds are: daily more
  than 2 days, weekly more than 14 days, monthly more than 62 days, yearly more than 400 days,
  cron more than twice its interval (at least 1 hour), everything else more than 2 days.
  Re-enabling a task in the Web UI computes a fresh next run.
- **The monthly donation message works again.** It has been broken for a while; it now posts to
  the configured channels on the 2nd Sunday of the month.
- **Migrated v1 installations:** on first start, the settings that were actually in effect are
  folded into `config.json` once (a backup is written first, legacy files are renamed to
  `*.folded-<timestamp>`). Without this, a password or bot token could have been lost.
- **Rotate your Discord bot token** if you care: older versions kept a decrypted copy in
  `config.json` (and `config.json.bak`). That is fixed, and the leftovers are cleaned up on the
  next save, but the token was on disk in plaintext before.
- **Downgrading to v2.3.1:** the mech keeps working — the snapshot format is unchanged and the
  interim decay field is migrated out on load. **But** if your installation was migrated from v1
  (it still has `bot_config.json` / `docker_config.json` / `web_config.json` in `config/`), the
  one-time fold makes `config.json` authoritative, while v2.3.1 reads only the old split files in
  that layout. After a downgrade, a password, bot token, language or timezone changed since the
  upgrade would silently fall back to the old values. The pre-fold state is in
  `config/backup_<timestamp>_settings_fold/`.

---

## Highlights

- **A button that fails now tells you so.** py-cord's default handler for a view or modal error
  prints to the log and never replies, so a failed press left the "thinking..." state spinning
  until Discord timed it out. Every one of the 25 views and 5 modals now logs the failure and
  answers you. The same gap existed for slash commands, where the error handler had been
  registered for an event that never fires.
- **Start, stop and restart answer even when Docker is unreachable.** They raised instead of
  returning a result, and nine places read that result as "did it work" — the buttons, the admin
  overview's Stop All / Restart All, and the scheduled tasks that run overnight.
- **One unexpected error no longer stops status updates until the next restart.** A background
  task loop ended permanently on anything outside a short list of network errors.
- **DDC now speaks your language everywhere.** 89 texts were English-only regardless of the
  configured language — button labels, dropdown placeholders, whole embeds. About 1,900 new
  catalogue entries across the 40 locale files, with a test that fails on the next one.
- **The log tabs in the web panel stay readable when Docker is down.** They answered with the
  framework's HTML error page — markup in the log window, at exactly the moment you opened it to
  find out what was wrong.
- **More than 25 containers are all reachable from Discord again.** Discord shows at most 25
  options in one dropdown; the rest were silently dropped. The dropdowns now page.
- **The server list is faster.** Every message on your server used to cost two config file reads
  (0.20 ms); now none. Building a status label went from 18.1 µs to 0.2 µs — it had been
  deep-copying the whole configuration to look up one setting.
- **Admin users can be saved again.** `/api/admin-users` was not covered by the CSRF exemption
  and the UI never sent a token, so every save failed with a generic error.
- **The bot no longer blocks itself.** All Docker SDK calls now run off the event loop. This was
  the cause of repeated container timeouts and the flood of
  "SLOW batched processing" warnings.
- **Auto-action rules with more than one container work.** They locked themselves out via the
  global cooldown and silently never ran — every trigger was recorded as skipped.
- **Weekly scheduled tasks survive.** The weekday was never written to `tasks.json`, so weekly
  tasks created from Discord or edited in the Web UI were dropped on the next load.
  `/schedule_weekly` also stored the wrong day (off by one).
- **Cron tasks run at all** — `croniter` was missing from the image, so cron tasks were created
  and then silently deactivated.
- **"Change password" in the Web UI actually changes the password.** It previously did nothing
  and stored the new password in plaintext.
- **CSRF protection is enforced** for all blueprints — no route is exempt any more, and pages
  that extend the base template attach the token automatically (the first-run setup page carries
  its own). If Flask-WTF is not installed, protection stays off and a warning is logged.

## Security

- Decrypted bot token is no longer written to `config.json`; the plaintext copy is removed on the
  next save, and a token that cannot be decrypted is repaired instead of dropped.
- Protected container-info passwords (`info_protected_*`) are no longer stored in `config.json`
  in plaintext either.
- The config save no longer accepts arbitrary posted fields (password hash, token, junk keys).
- CSRF is enforced for all blueprints; rejected requests return a clear JSON reason.
- A short `DDC_ADMIN_PASSWORD` is accepted again — otherwise a fresh install silently stayed in
  first-time-setup mode, where `admin/setup` had full access.
- Session cookie renamed (`ddc_session`) and set to `SameSite=Lax`, so other apps on the same
  host can no longer break DDC's session; the per-request global `SESSION_COOKIE_SECURE` switch
  was removed (it could lock out plain-HTTP LAN users).
- New passwords require 12 characters; existing passwords keep working.

## Discord bot

- Status/Info/Help buttons acknowledge the interaction immediately — no more
  "This interaction failed" (Unknown interaction / 10062).
- Stop All / Restart All respect each container's allowed actions and report what they skipped.
- Deleted or renamed containers show ❓ "not found" instead of staying "offline" forever.
- Auto-actions honour the "only if running" option (it was stored but ignored) and post a short
  notice in the channel when a rule is skipped for that reason.
- Overviews refresh at least every ~60 s even with a long cache duration.
- Status fetches run up to 6 in parallel; CPU% now shows current load instead of an average since
  host boot.
- Fixed crashes: `/control` error paths, the status path for containers with hidden details, and
  overview building when the mech cache fails.
- Buttons on messages posted by the old version keep working (no custom_id changes).

## Scheduler & tasks

- Weekly tasks: day is stored canonically, abbreviations ("Mon") are accepted, `/schedule_weekly`
  uses the correct day, numbers are 1–7 (Monday = 1).
- Missed runs: a task that is slightly late still runs once; anything older is rescheduled
  instead of being stuck forever.
- Daylight saving: daily, weekly and yearly runs keep their local time across transitions.
- Scheduled stop/restart wait for the container's configured StopTimeout and are never sent
  twice.
- Many tasks due at the same minute all run.
- Yearly tasks no longer skip the current year; Feb 29 is preserved in leap years.
- Tasks created from Discord use the configured timezone, are checked against the container's
  allowed actions, and are shown with their own timezone in the delete panel.
- Tasks created in the Web UI always run, regardless of what Discord users may do.

## Web UI

- Enter in a text field no longer submits the config form to a 405 page and loses edits.
- Heartbeat (Status Watchdog) settings are saved — every save used to switch them off.
- The mech difficulty slider loads its current state; saving no longer reports "Failed".
- Donations: amounts keep their cents; deleting/restoring uses a stable id instead of a list
  index; $0 returns a clear error instead of a 500.
- The last channel can finally be deleted.
- Deleting an entry, saving the config or hitting an expired session now shows the real server
  message instead of a generic error.
- 118 previously untranslated bot and UI strings are now available in all 40 languages, and 3
  outdated texts were corrected (the setup page still asked for 6-character passwords). All 40
  language files carry the same key set and the same placeholders.

## Mech & donations

- Power decay is settled on every change: a donation now adds to the power you see, instead of
  first paying off invisible decay debt. A mech at $0 shows as offline and is eligible for the
  one-time startup gift.
- Deleting or restoring a donation no longer shifts the displayed power or total.
- Level goals use the current member count and are not re-priced by a rebuild.
- A corrupt snapshot or a truncated line in the event log no longer blocks donations or silently
  resets the mech to level 1.
- Animation speed follows the real level.

## Deployment & startup

- New dependencies in the image: `croniter`, `psutil`.
- Docker `HEALTHCHECK` in the image. It ignores `HTTP(S)_PROXY`, so a container with a proxy
  configured no longer reports itself unhealthy (which could make autoheal restart it in a loop).
- `DDC_WEB_PORT` (default 9374) sets the Web UI port; a busy port is retried and reported
  clearly instead of crash-looping.
- An invalid bot token keeps the Web UI reachable and DDC restarts itself as soon as a new token
  is saved. Missing privileged intents are retried automatically (90 s, backing off to 15 min).
- An unwritable `logs` directory falls back to console logging instead of a restart loop.
- The entrypoint only fixes files the app user genuinely cannot use, instead of rewriting
  ownership of everything.
- An invalid `TZ` falls back to UTC with a warning instead of crashing.
- `docker stop` takes ~2 s instead of hitting the 10 s kill timeout.
- **Removed:** `scripts/start.sh` no longer offers the "Python (direct)" run mode — it referenced
  a gunicorn config that does not exist and started bot and web server as separate processes.
  Without Docker it now exits with a pointer to `scripts/rebuild.sh` / the Docker image.

## Behaviour changes to be aware of

| Change | Effect |
|---|---|
| Stop All / Restart All | skip containers whose allowed actions exclude the action |
| Auto-actions "only if running" | now enforced: stopped containers are skipped, with a notice |
| Scheduled tasks from Discord | checked against allowed actions at run time |
| Old, long-dead tasks | paused once on upgrade (see upgrade notes) |
| Monthly donation message | starts posting again |
| Mech | decay debt cleared, startup gift may trigger, animation speed changes |
| CPU% in status | now current load, not an average since boot |
| New passwords | minimum 12 characters |

## Under the hood

- **185 findings** fixed across bot, scheduler, web panel, config, mech and deployment.
- **5,699 tests**, all green in the production image (Python 3.14), lint clean. Each finding has
  a test that failed before its fix and a probe afterwards proving the test can still fail.
- **183 of 183 source files** carry written evidence of having been read.
- Two mechanical scans were written and run over the whole project rather than a sample. The
  first looked for functions that raise where their signature promises a value: 86 candidates,
  worked down to 7, and each of those 7 read back to its definition and explained in writing.
  The second looked for failures answered with a silent empty value: 219 candidates, filtered to
  the 24 that log nothing at all; 23 were correct, and the one that was not could have cost a
  game server its world save.
- **The test suite was audited against itself.** All 4,956 test functions were classified by what
  their assertions can actually constrain. One could not fail at all; five checked less than
  their names claimed, including a path-traversal security test whose only assertion was the
  return type. Then each fix was reverse-applied to see whether its test noticed: 26 of 30 could
  be reverted cleanly and all 26 turned a test red. The tools that did this are in the
  repository, because a result nobody can reproduce is not one.
- Every finding is documented with its evidence and its verification in the audit protocol kept
  with the project.
