# DDC v3.1.0: only when nobody plays, and who is playing

DRAFT for the operator. Nothing here is published until they say so. The v3.0 notes this file
held before are in the release for that tag; the full list of changes is in `docs/CHANGELOG.md`.

---

Updating from v3.0 is a plain image update.

## Restart only when nobody plays

- **A scheduled restart or stop can wait for an empty server**, at most as long as you set
  (1-720 minutes, 120 by default), and then happens anyway: "restart daily at 4, but only once
  nobody plays, at the latest at 6". Auto-action rules take the same option.
- **A warning before it**, in the status and control channels: "Valheim will restart in 10
  minutes". DDC wakes up for the warning time you set; if it could not warn in time (it was
  restarted, say), it warns then and waits that long before acting.
- A player count that cannot be read counts as empty; whether it can be read is checked when
  you save the task or rule, and the panel tells you.

## Who is playing, in the info display

- **Every container has an info display now**: uptime, restarts, health, the image's version and
  whether a newer image is in the registry (checked every six hours, never pulled) - and for a
  game server who is playing, with the game, its version and the port to connect to.
- **Player joins can be announced** in a channel ("👋 Anna joined Valheim (2/10)"); off unless
  you tick "Player joins" for the channel.
- **A dead game server is shown ⚠️, not green**: its container runs, but the game does not answer.

## Quieter, and more careful

- The web panel asks Docker once per refresh instead of once per container, and only while
  somebody uses the panel.
- An admins.json or config.json that cannot be read is reported and left alone instead of being
  replaced by the next save.
- A review before this release went through every part again and fixed well over a hundred
  smaller defects, each with its own test. 8,340 tests pass.

## Messages that tidy up after themselves

- **Every public message but the status and control overviews has a lifetime**, and keeps it
  over a restart of DDC: auto-action and watchdog notices 1 hour, a player warning until 15
  minutes after its action, a thank-you for a donation 24 hours, the notice of a new DDC version
  7 days. The scheduled donation reminder stays - and is no longer swept away when DDC cleans
  its channels at start.

## Good to know

- **A plaintext bot token is encrypted automatically** once a web panel password is set.
- **At startup DDC clears its own old messages of any age** in its channels, not only recent ones.
- **An out-of-range query port is refused** when you save, with a message, instead of being kept.
- **A container that never answers a player query is asked for 15 minutes and then left alone**,
  as intended; before, every such container was asked every minute for as long as it ran.

Everything in detail: [docs/CHANGELOG.md](docs/CHANGELOG.md)
