# DDC v3.0: the Docker socket, behind a door

DRAFT for the operator. Nothing here is published until they say so. The v2.4.1 notes this
file held before are in the release for that tag; the full list of changes is in
`docs/CHANGELOG.md`.

---

DDC needs the Docker socket, and write access to the Docker API is root on the host. That has
always been true and no amount of documentation changed it. v3.0 changes it: inside the one
container, DDC's code can no longer reach anything but the handful of Docker endpoints it
needs. What that does and does not protect is written out in
[`docs/SECURITY.md`](docs/SECURITY.md) - please read it, including the part about what it does
NOT protect.

## Read before you update

- **Behind a reverse proxy:** set `DDC_TRUSTED_PROXIES` to your proxy's address or range. Until
  you do, the action log shows the proxy's address instead of the client's - DDC no longer
  believes `X-Forwarded-*` from just anyone, which is what let a direct client walk around the
  login rate limit before.
- **`docker_socket_path` in the configuration is no longer used.** Every Docker client follows
  `DOCKER_HOST`. If yours is set to something else, DDC says so once in the log.
- **Started with `--user`?** Then no proxy can run, and DDC says so and uses the raw socket.
  Start without `--user` and use `PUID`/`PGID` instead.
- **Going back to v2.4.1 is safe.** Measured with both images: 2FA state, the TLS certificate
  and the new container-state rules survive a downgrade and a second upgrade.

## The boundary

- **An allowlist in front of the socket.** A separate user inside the container speaks to
  Docker; DDC speaks to that user over a private socket and may ask for exactly ten things:
  ping, version, the container list, a container's details, logs and stats, start, stop,
  restart, and an image's details (read-only, for the update notice). Everything else -
  creating containers, `exec`, pulling images, the daemon's own information - is refused
  before it reaches Docker.
- **DDC cannot rewrite its own start.** Code, entrypoint and the proxy are root-owned and
  read-only for DDC; only the data directories belong to it.
- **One Docker client factory** instead of eight separate constructions, three of which used
  to ignore the configured timeout.
- **TLS:** `DDC_TLS_MODE=proxy` (TLS ends at your reverse proxy) or `self-signed` (DDC serves
  HTTPS with a certificate it creates and renews itself, fingerprint in the log). Default is
  `off`, exactly as before.
- **Two-factor authentication** for the panel: offered with a "Later" button, never forced.
  TOTP, ten recovery codes, and a break-glass script on the host for a lost phone. While it is
  on, the panel answers only over HTTPS.

## New things you will notice

- **A container watchdog.** Rules can react when a container stops on its own, turns unhealthy,
  restarts several times in a few minutes, or stays above a CPU or memory threshold. Notify, or
  restart/start/stop the container that changed. Set it up under Auto-Actions, trigger type
  *Container state*.
- **Image-update notices.** A rule can report when the registry has a newer image for the tag a
  container runs - a HEAD request every six hours, no pull, no effect on Docker Hub's pull
  limit.
- **Compose stacks.** The panel shows each container's stack and can sort the server order by
  it; the Admin Overview groups by stack and has a "Stack" button that restarts one.
- **The container info shows uptime, restart count and health.**

## Fixed on the way

- A container DDC could not ask - a query that timed out - was reported as offline. It is now
  reported as unknown, and the last known state stays.
- On a large installation no overview appeared at all: an embed longer than 4096 characters is
  refused by Discord. As many containers as fit are shown, and the last line says how many are
  missing.
- A long info text made the Info button answer with an error instead of showing the text.
- In the panel, a label that needs two lines no longer pushes its input field out of line.

## Testing

- 6,061 tests pass in the production image, over the 43 groups of `tests/GROUPS.txt`.
- Three independent review passes over the new code; every finding they confirmed is fixed with
  a test that was red against the old code, or written down as a decision.
