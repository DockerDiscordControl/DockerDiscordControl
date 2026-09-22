# DDC v2.4.0: Audit release

This release comes out of a complete audit of DDC: every part of it was reviewed, and a second
pass looked specifically at what changes for **existing installations** when they upgrade.
**188 findings were fixed.**

If you read only one section, read the upgrade notes.

---

## ⚠️ Upgrade notes (please read)

- **You will be logged out once.** The session key is now stored permanently
  (`config/.flask_secret_key`) instead of being regenerated on every start, and the session
  cookie was renamed to `ddc_session`. Log in again and **reload open browser tabs**: the first
  save from a stale tab fails with a "session expired" message.
- **Long-dead scheduled tasks are paused, not resurrected.** A bug made a recurring task stop
  for good once a single run was missed (host down, slow check cycle), while the Web UI still
  showed it as active. That is fixed. But reviving months-old tasks on upgrade would fire
  surprise restarts. So on first start, tasks that are long overdue are deactivated once and
  marked in the Web UI with a note saying when they last ran. The thresholds: daily more than
  2 days, weekly more than 14 days, monthly more than 62 days, yearly more than 400 days, cron
  more than twice its interval (at least 1 hour), everything else more than 2 days.
  Re-enabling a task computes a fresh next run.
- **Your bot token on disk.** On most installations the token is stored in plaintext in
  `config/config.json`, and upgrading does not change that. The **Encrypt token** button in the
  Web UI's token security panel now really encrypts it. In earlier versions that button reported
  "encrypted successfully" and changed nothing. So if you pressed it before, your token is
  still in plaintext: press it again. Where the token was already stored encrypted, older
  versions also wrote a decrypted copy next to it; that copy is removed on the next save.
  Nothing is encrypted automatically. If your token has sat on disk in plaintext and that
  worries you, reset it in the Discord developer portal and enter the new one.
- **The monthly donation message works again** and posts to the configured channels on the
  2nd Sunday of the month.
- **Installations migrated from v1:** on first start, the settings actually in effect are folded
  into `config.json` once (a backup is written first, legacy files are renamed to
  `*.folded-<timestamp>`). Without this, a password or bot token could have been lost.
- **Downgrading to v2.3.1:** the mech keeps working, because the snapshot format is unchanged. **But**
  if your installation was migrated from v1 (it still has `bot_config.json` /
  `docker_config.json` / `web_config.json` in `config/`), the one-time fold makes `config.json`
  authoritative, while v2.3.1 reads only the old split files in that layout. After a downgrade,
  a password, bot token, language or timezone changed since the upgrade would silently fall back
  to the old values. The pre-fold state is in `config/backup_<timestamp>_settings_fold/`.

---

## Highlights

- **One container can no longer make all your servers disappear.** If the image a container was
  created from had been removed from the host (after an update, a `docker image prune`, or with
  Docker's containerd image store), DDC failed with "No such image", the web panel showed no
  containers at all, "Refresh" kept failing, and running servers looked missing in Discord.
- **Admin users can be saved again.** Saving them always failed with "Failed to save admin users".
- **Scheduled tasks run the way you set them up.** Weekly tasks were dropped on the next load
  (and `/schedule_weekly` picked the wrong day), cron tasks were silently switched off, and one
  missed run could stop a recurring task for good.
- **The bot stays responsive.** Docker calls no longer block it, which was behind the repeated
  container timeouts and the flood of "SLOW batched processing" warnings.
- **Every button answers.** When a button, a form or a slash command fails, you now get a
  message instead of an endless "thinking…" that Discord eventually times out.
- **Status messages keep updating.** A single unexpected error used to stop them until the next
  restart.
- **Auto-actions with several containers work.** They locked themselves out and silently never
  ran.
- **"Change password" changes the password.** It used to do nothing, and it stored the new
  password in plaintext.
- **DDC speaks your language everywhere.** More than 200 texts stayed in English whatever
  language you had chosen: button labels, dropdowns, whole messages. All 40 languages now have
  them.

## Security

- The **Encrypt token** button really encrypts the token in `config.json` (see the upgrade
  notes), checking first that the bot can still decrypt it. The token security panel reports
  what is actually stored.
- A decrypted copy of an encrypted token is no longer written to `config.json`, and a token that
  cannot be decrypted is repaired instead of dropped.
- Protected container-info passwords are no longer stored in `config.json` in plaintext.
- The config save no longer accepts arbitrary posted fields (password hash, token, junk keys).
- CSRF protection is enforced on every route; the pages attach the token automatically, and a
  rejected request gets a clear message.
- A short `DDC_ADMIN_PASSWORD` is accepted again. Otherwise a fresh install silently stayed in
  first-time-setup mode, where `admin/setup` had full access.
- The session cookie (`ddc_session`) uses `SameSite=Lax`, so other apps on the same host can no
  longer break DDC's session. The switch that could lock out plain-HTTP LAN users was removed.
- New passwords need at least 12 characters; existing passwords keep working.
- Auto-action regex patterns are validated, and each search runs in a separate process with a
  hard 0.5 s budget, so a catastrophic pattern can no longer freeze the bot.

## Discord bot

- Status, Info and Help buttons acknowledge immediately, so "This interaction failed" no longer appears.
- Start, stop and restart report a clear result when Docker is unreachable, instead of breaking
  off with an internal error. That applies to the buttons, Stop All / Restart All and scheduled
  tasks.
- Stop All / Restart All respect each container's allowed actions and report what they skipped.
- More than 25 containers: Discord shows at most 25 entries in one dropdown, and the rest were
  silently left out. The container dropdowns now page.
- Deleted or renamed containers show ❓ "not found" instead of staying "offline" forever.
- Auto-actions honour the "only if running" option (it was stored but ignored) and post a short
  notice when a rule is skipped for that reason.
- Overviews refresh at least every ~60 s even with a long cache duration.
- Status fetches run up to 6 in parallel, and every Discord message on your server no longer
  costs DDC two config file reads. CPU% shows current load instead of an average since boot.
- Fixed crashes in `/control` error paths, in the status of containers with hidden details, and
  in overview building when the mech cache fails.
- Buttons on messages posted by the old version keep working.

## Scheduler & tasks

- Weekly tasks: the day is stored correctly, abbreviations ("Mon") are accepted, and
  `/schedule_weekly` uses the right day (Monday = 1).
- Missed runs: a task that is slightly late still runs once; anything older is rescheduled
  instead of being stuck forever.
- Daylight saving: daily, weekly and yearly runs keep their local time across transitions.
- Scheduled stop/restart wait for the container's configured StopTimeout and are never sent
  twice.
- Many tasks due at the same minute all run.
- Yearly tasks no longer skip the current year; Feb 29 is preserved in leap years.
- Tasks created from Discord use the configured timezone, are checked against the container's
  allowed actions, and show their own timezone in the delete panel.
- Tasks created in the Web UI always run, regardless of what Discord users may do.

## Web UI

- Saving keeps the server order you arranged. Every save used to reset the order of the admin
  overview and the container dropdowns.
- The log tabs stay readable when Docker is down, instead of showing an HTML error page.
- Enter in a text field no longer submits the config form to an error page and loses your edits.
- Heartbeat (Status Watchdog) settings are saved. Every save used to switch them off.
- The mech difficulty slider loads its current state; saving no longer reports "Failed".
- Donations: amounts keep their cents, deleting and restoring picks the right entry, and $0
  returns a clear error.
- The last channel can finally be deleted.
- Failed deletes, saves and expired sessions show the real reason instead of a generic error.

## Mech & donations

- Power decay is settled on every change: a donation adds to the power you see, instead of
  first paying off invisible decay debt. A mech at $0 shows as offline and is eligible for the
  one-time startup gift.
- Deleting or restoring a donation no longer shifts the displayed power or total.
- Level goals use the current member count and are not re-priced by a rebuild.
- A corrupt snapshot or a damaged line in the event log no longer blocks donations or silently
  resets the mech to level 1.
- The animation speed follows the real level.

## Deployment & startup

- New dependencies in the image: `croniter`, `psutil`.
- A Docker `HEALTHCHECK` is built in. It ignores `HTTP(S)_PROXY`, so a container with a proxy
  configured no longer reports itself unhealthy (which could make autoheal restart it in a loop).
- `DDC_WEB_PORT` (default 9374) sets the Web UI port; a busy port is retried and reported
  clearly instead of crash-looping.
- An invalid bot token keeps the Web UI reachable, and DDC restarts itself as soon as a new
  token is saved. Missing privileged intents are retried automatically.
- An unwritable `logs` directory falls back to console logging instead of a restart loop.
- On start, only files the app user genuinely cannot use get their ownership fixed.
- An invalid `TZ` falls back to UTC with a warning instead of crashing.
- `docker stop` takes about 2 s instead of hitting the 10 s kill timeout.
- **Removed:** `scripts/start.sh` no longer offers the "Python (direct)" run mode. It referenced
  a config that does not exist; without Docker it now points to `scripts/rebuild.sh`.

## Behaviour changes to be aware of

| Change | Effect |
|---|---|
| Stop All / Restart All | skip containers whose allowed actions exclude the action |
| Auto-actions "only if running" | now enforced: stopped containers are skipped, with a notice |
| Scheduled tasks from Discord | checked against allowed actions at run time |
| Old, long-dead tasks | paused once on upgrade (see upgrade notes) |
| Monthly donation message | starts posting again |
| Mech | decay debt cleared, startup gift may trigger, animation speed changes |
| CPU% in status | current load, not an average since boot |
| New passwords | minimum 12 characters |
| "Encrypt token" button | really encrypts, but only when you press it; nothing is encrypted at startup |
| Container order after saving | kept as you arranged it |
| Image name shown for a container | the name the container was created with (e.g. `ich777/steamcmd:valheim`), usually the same as before; a container created without a tag now shows none |

## Under the hood

- 188 findings fixed; 5,715 tests pass in the production image (Python 3.14). Fixes come with
  regression tests written to fail without them, and taking recent fixes out again was checked
  to turn their tests red.
- The tests themselves were audited as well: the one test found that could not fail at all has
  been fixed.
- Evidence, reports and the tools used are in `docs/quality/` in the repository.
