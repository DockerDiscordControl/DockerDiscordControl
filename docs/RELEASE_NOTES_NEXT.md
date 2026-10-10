# DDC v3.1.1: empty servers stop, and a cleaner image

DRAFT for the operator. Nothing here is published until they say so. The v3.1.0 notes this file
held before are in the release for that tag; the full list of changes is in `docs/CHANGELOG.md`.

---

Updating from v3.1.0 is a plain image update.

## Stop a game server nobody plays on

- **A new watchdog state: "a game server nobody plays on".** In the auto-action editor, tick it,
  set "nobody online for (minutes)" (5 to 1440, 30 by default), tick the game servers it watches
  and choose Stop or Notify: "stop Valheim when nobody was online for 30 minutes". It saves RAM and
  CPU on servers that run empty all night.
- A server is reported once per empty stretch, and a freshly started one always gets the full
  minutes, whether you, a task or DDC started it.
- A player count that cannot be read counts as empty; the editor says so when you save, and it
  warns when the rule's cooldown is longer than the minutes.

## The overview shows a join at once

- A changed player count redraws the overview in the same minute as the join notice, instead of
  at the channel's next update interval. A failed query does not make it jump.

## The live-log panel, gone over

- **More of the log:** up to 4000 characters of whole lines, the time as HH:MM:SS in your time
  zone, without colour codes.
- **📥 the whole log as a file:** the last 5000 lines as `<container>-<time>.log`, only for you.
- **It goes when it should:** "Message timeout (s)" now works, and the panel is deleted after it.
  Buttons redraw the panel without extra notes, and live updates end before Discord stops
  accepting edits.
- One title, translated texts, and the switch in the web panel names the 📋 button instead of a
  /logs command that never existed.

## Smaller things

- **No task for a date that does not exist:** Discord's task dropdowns no longer offer 31
  February, and an older panel that still holds one is refused with a clear sentence.
- **"Validate key" asks the server**, by the same list the save uses. It knew only five of six
  keys before, and no key list sits in the browser any more. The page redraws itself after a key
  switches the donations on or off.
- **A quieter log:** a minute without a problem leaves no line at INFO; the log was always bounded
  and now holds weeks instead of days.
- A used info panel in a control channel goes at its timeout like every private panel.

## Security

- **No known vulnerability in the image.** Docker Scout flagged three high CVEs in the v3.1.0
  image (zlib, expat). zlib is at Alpine 3.24's fixed version; expat and libexpat 2.9.0 come from
  Alpine edge until 3.24 carries them. A Trivy scan of the new image finds nothing.
- Two CodeQL findings are fixed: the saved config logs a count instead of the names of the fields
  it kept, and a test no longer reads like a URL check.

8,440 tests pass.

Everything in detail: [docs/CHANGELOG.md](docs/CHANGELOG.md)
