# DDC v2.4.0 — Audit release

> Text for the GitHub release page. The version bump is done (2026-09-16): `ENV DDC_VERSION` in
> the Dockerfile, the README title and badge, and `docs/CHANGELOG.md`. The entrypoint banner, the
> Web UI footer and `/health` all read that one Dockerfile value — a rebuild is required for it
> to take effect, since the value is baked into the image.

This release comes out of a complete audit of DDC: every subsystem was reviewed, then a second
review pass looked specifically at what changes for **existing installations** on upgrade.
141 findings were fixed, with 564 new regression tests across 32 test modules.

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

- 141 findings fixed across bot, scheduler, web panel, config, mech and deployment.
- 564 new regression tests (32 modules) on top of the existing suite; all suites green in the
  production image (Python 3.14), lint clean.
- Every finding was documented with its evidence and its verification in an internal audit
  protocol kept with the project.
