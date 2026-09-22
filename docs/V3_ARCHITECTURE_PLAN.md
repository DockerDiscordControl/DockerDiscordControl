# DDC v3.0 — Security-by-Design architecture plan

**Status: not started. Nothing in this document is implemented.**
v2.4 is finalised first; v2.5 is skipped. Written 2026-09-22, revised the same
day after an independent review that measured the v2.4.1 tree, the running
container and docker-py 7.1.0 itself. Corrections are marked **(revised)**.

Every number in here was measured, not estimated. Where something could not be
measured from inside this repository it says so.

---

## 1. The goal, stated so it can be checked

The community's objection to DDC is that it needs `/var/run/docker.sock`, and
that write access to the Docker API is equivalent to root on the host. That is
correct today and no amount of documentation changes it.

v3.0 aims to make the objection false rather than answered.

### Three doors, not one

The blueprint's original sentence — *"a compromised Discord token cannot result
in a host root exploit"* — mixes up doors that need different locks. Keeping
them apart is what makes each measure checkable:

| Door | Who comes through it | What closes it |
|---|---|---|
| **A. The Docker API** | anything that can reach the socket: DDC's own code, a dependency, an attacker with code execution in the container | the proxy, and only if the socket is out of DDC's reach (§4) |
| **B. The web panel** | someone with the panel password — reused, leaked, or guessed | 2FA, and only over TLS (§5) |
| **C. The Discord bot** | someone with the bot token, or write access to a control channel | already bounded: the channel permission model (SPEC.md B1/B2). The bot can start/stop/restart configured containers and nothing else. It never touches proxy permissions, in v2.4 or v3.0 |

Door C is the one the original sentence named, and it is already the narrowest
of the three. **2FA does not protect door C, and the proxy does not protect
door B.** Saying which is which in the release notes is part of the work.

---

## 2. Where we actually start from

`docs/SECURITY.md` currently lists two mitigations under "Docker Socket
Security". Neither is one, and v3.0 should say so plainly rather than build on
top of them.

### "Read-only Docker socket mounting"

`docker-compose.yml:14` mounts `/var/run/docker.sock:...:ro`, and
`SECURITY.md:274` presents that as a security feature.

`:ro` makes the socket **file** unmodifiable. It does nothing to the API
reached through it. `POST /containers/{id}/stop` works exactly as before — and
DDC's own Stop button proves it, because it works today through that very
mount. A read-only socket mount is not a permission boundary and must stop
being described as one.

(The Unraid `docker run` line in `app/utils/port_diagnostics.py:351` does not
use `:ro` at all, so the two documented deployments differ. Immaterial, for the
reason above.)

### "Non-root user execution (uid 1000)"

True and worth keeping — but a non-root user that can open the Docker socket
has root-equivalent power on the host. The uid limits what DDC can do to its
own container's filesystem, not what it can ask the daemon to do.

**Starting position, honestly stated: DDC has unrestricted Docker API access
and no boundary of any kind between its code and the daemon.**

---

## 3. What DDC actually needs from Docker — measured

This is the whole API surface, taken from every docker-py call in every file
that imports `docker` under `services/`, `cogs/`, `app/`, `utils/`, `bot.py`,
`run.py` and `scripts/`:

```
GET  /_ping                      client.ping()
GET  /containers/json            client.containers.list(), client.api.containers()  (docker_utils.py:832)
GET  /containers/{id}/json       client.containers.get(), container.attrs
GET  /containers/{id}/logs       container.logs(tail=..)          never stream=True
GET  /containers/{id}/stats      container.stats(stream=False)    never a stream
POST /containers/{id}/start      container.start()
POST /containers/{id}/stop       container.stop(timeout=..)
POST /containers/{id}/restart    container.restart(timeout=..)
```

Eight endpoints in DDC's own code. Verified absent: `containers.create`,
`containers.run`, `container.remove`, `exec_run`, `events`, every streaming
call, and every `images.*`, `networks.*` and `volumes.*` call. DDC never
creates, deletes or modifies a Docker object other than changing the run state
of a container that already exists.

**(revised) Two things the first count missed:**

1. **docker-py itself calls `GET /version` on every client construction.**
   docker-py 7.1.0 (`requirements.prod.txt:33`) treats `version=None` as
   "negotiate": `APIClient.__init__` calls `_retrieve_server_version()`, which
   is `GET /version` **without** the `/v1.xx` prefix. None of the eight client
   sites (§6) passes `version=`. A proxy that does not allow `/version` makes
   every `DockerClient(...)` and `from_env()` raise
   `DockerException("Error while fetching server API version")`. Tecnativa
   grants `VERSION` by default for exactly this reason.
2. `client.info()` in `docker_utils.py` (`analyze_docker_stats_performance`)
   would be `GET /info`. The function had no caller anywhere; it was dead code
   and is deleted (Etappe 2a) rather than allowlisted.
   `tests/spec/test_no_code_asks_docker_for_host_info.py` keeps it out.

So the surface is **eight endpoints plus one implicit `GET /version`**, and
every one of them carries query strings (`all=1`, `stream=false`, `tail=`,
`t=`) that the allowlist must ignore by matching the path only.

**This is the single most useful fact in this document.** A surface of nine
endpoints is small enough to allowlist exactly, and an exact allowlist is what
turns the security claim from a hope into a property.

### What the allowed surface still exposes

The allowlist limits what can be *done*; it does not limit what can be *read*
through the nine endpoints. Two of them deserve a sentence in `SECURITY.md`:

- `GET /containers/{id}/json` returns `Config.Env` of the container, i.e. the
  passwords and tokens that many images take as environment variables.
- `GET /containers/{id}/logs` returns whatever the container logs, and secrets
  in logs are common.

Anyone who gets through door B or door C can read both for every configured
container, today and after v3.0. The proxy does not change that; saying so is
part of the honest claim.

---

## 4. Component 1 — the proxy

### 4.1 Why `CONTAINERS=1, POST=1` does not deliver the claim

Tecnativa's `docker-socket-proxy` filters by **API section** (one env var per
path group) and by **method** (`POST=1` enables POST globally). It cannot
express "POST, but only for start, stop and restart".

With `CONTAINERS=1` and `POST=1`, `POST /containers/create` is permitted.
A container created with

```json
{ "HostConfig": { "Binds": ["/:/host"], "Privileged": true } }
```

is a complete host root exploit. Tecnativa's own README warns that granting
POST is dangerous for exactly this reason.

So that permission set leaves door A as wide open as a raw socket does, for any
attacker who can send API calls. It would restrict DDC's *own* code paths and
nothing else.

`POST /containers/{id}/exec` also lives under `/containers/` rather than under
Tecnativa's `EXEC` section. **(revised) Verified against the proxy's
`haproxy.cfg` (master):** line 48 is `http-request deny unless METH_GET ||
{ env(POST) -m bool }`, line 60 is `http-request allow if { path ... -m reg -i
^(/v[\d\.]+)?/containers } { env(CONTAINERS) -m bool }`. The `CONTAINERS`
rule is a prefix match with no method condition, so with `POST=1` it admits
`/containers/create` and `/containers/{id}/exec` alike. The `ALLOW_START`,
`ALLOW_STOP` and `ALLOW_RESTARTS` switches (lines 51-53) do not help: DDC needs
`CONTAINERS=1` for its GET calls, and that switch is what opens the POSTs. The
section filter genuinely cannot express DDC's surface. This question is closed.

### 4.2 Decision: an explicit allowlist, not a section filter

Because the needed surface is nine endpoints (§3), the proxy should be a
method-plus-path allowlist and nothing else. **(revised)** The rules match the
URL path with the query string stripped, and `/version` is in:

```
GET   ^/(v[0-9.]+/)?_ping$
GET   ^/(v[0-9.]+/)?version$
GET   ^/(v[0-9.]+/)?containers/json$
GET   ^/(v[0-9.]+/)?containers/[a-zA-Z0-9_.-]+/(json|logs|stats)$
POST  ^/(v[0-9.]+/)?containers/[a-zA-Z0-9_.-]+/(start|stop|restart)$
GET   ^/(v[0-9.]+/)?images/[a-zA-Z0-9_./:@-]+/json$     (reserved, §8 item 4)
```

Everything else: 403, logged. Default deny, no env-var switches that can widen
it at runtime. The image-inspect line is read-only and exists for the
image-update notice decided for the phase after v3.0; DDC's v3.0 code does
not call it, and the inventory guard says so.

The client factory of §7 step 6 additionally pins `version=` to one API
version, so DDC no longer negotiates. `/version` stays in the list anyway: the
web diagnostics show the daemon version, and a factory that forgets the pin
must not take DDC down.

Properties this buys that a section filter does not:
- `POST /containers/create` is impossible to reach, by construction.
- The rule set fits on one screen and can be reviewed by a sceptical user in a
  minute. That matters: the objection being answered is a *trust* objection.
- It can be tested. A test per denied endpoint, plus a test that the nine
  allowed ones pass — the same shape as the guards v2.4 already has.
- **(revised) And it must be tested from DDC's side, not only the proxy's.**
  The endpoint tests above would all stay green with `/version` missing, while
  DDC could not build a single client. So the first test written for the proxy
  is an end-to-end one: construct a real `docker.DockerClient` against the
  proxy the way the factory does, then `ping()`, `containers.list()`,
  `containers.get()`, `logs()`, `stats(stream=False)` and one `start`/`stop`.
  Only that test goes red when docker-py makes a call nobody listed.

Cost: roughly 150 lines plus tests, versus adding a dependency. Given that the
dependency cannot express the rule we need, writing it is the cheaper option.

### 4.3 Open decision: one container or two

**This is the most consequential open question in the plan, and it is the
operator's to make.**

The blueprint promises "the user will still only install ONE container". If the
proxy runs inside the DDC container, the socket must be mounted into that
container — and anything with code execution there can talk to the socket
directly and ignore the proxy. The proxy would then protect against DDC's own
logic bugs, which is worth something, but **not** against a compromise, which
is what the community is objecting to.

Tecnativa's security model depends on the socket being mounted **only** into
the proxy container, with the application container having no socket at all.

| | one container | two containers |
|---|---|---|
| install | unchanged, one Unraid template | a second container or a compose stack |
| boundary against door A | only if UID separation works (below) | real: DDC's container has no socket |
| the claim we can honestly make | "DDC's code cannot reach anything but eight endpoints" | "DDC cannot reach the Docker socket" |

**The middle path worth investigating: UID separation.** The socket inside the
container is a bind mount owned from the host (`root:docker`, mode 660). If the
proxy runs as a user in that group and DDC runs as a user that is **not**, DDC
cannot open the socket at all and must go through TCP to the proxy. That keeps
the one-container promise and gives a genuine boundary.

It is a thinner boundary than two containers: it falls to any privilege
escalation inside the container. **(revised) Both open questions were measured
on the running v2.4.1 container, and the answer changes what "one container"
would have to look like:**

*How DDC reaches the socket today.* `Dockerfile:157-160` creates group
`docker` with gid 281 and adds `ddc` to it at build time;
`scripts/entrypoint.sh:337-400` reads the socket's gid at start, creates a
group with that gid if none exists and adds `ddc`; `:596-624` then drops to
`ddc` with `su-exec`. Measured inside the container: `uid=1000(ddc)
groups=281(docker)`, socket `srw-rw---- root:281`. So the separation itself is
plain group membership, and a second user outside gid 281 cannot open the
socket. Nothing else grants access: no setuid/setgid binaries in the image,
`CapEff=0`, `/opt/runtime/site-packages` root-owned and read-only for `ddc`.

*There is no supervisord.* PID 1 is `python3 run.py` running as `ddc`
(`README.md:367`). The proxy would need a real init or a second process
started by the entrypoint before it drops privileges.

*The route that defeats the boundary today.* The container starts as root
(`Config.User` is empty); the entrypoint runs as root, chowns `/app` to the
target uid (`entrypoint.sh:465-506`, `Dockerfile:179-181` already does
`chown -R ddc:ddc /app`) and only then drops privileges. Measured: `ddc` can
write `/app/entrypoint.sh`, `/app/services/` and `/app` itself. Anyone with
code execution in the DDC process overwrites the entrypoint; on the next
container start (a restart is enough, the change lives in the container's
writable layer) root executes it, and root in the container has the socket
regardless of any group. The same route exists for the proxy's own code if it
lives under `/app`.

**Conditions for the one-container option, all of them:**

1. `/app` code and `entrypoint.sh` owned by root, mode 755, and the entrypoint
   no longer chowns `/app` itself — only `config/`, `logs/`, `cached_*` belong
   to `ddc`. That changes the "fix permissions" behaviour NAS users rely on and
   is its own step, not a measurement.
2. The proxy binary and its rules outside every `ddc`-writable path.
3. A test that runs as `ddc` inside the built image, tries to write
   `entrypoint.sh` and the proxy rules, and fails if it can.
4. The proxy started by the entrypoint as a user in the socket's group before
   the drop to `ddc`, with `ddc` removed from that group.

Two containers have none of these conditions, because DDC's container has no
socket to reach. That is the honest comparison for the decision in §8.

---

## 5. Component 2 — the 2FA configuration lock

### 5.1 TLS is a prerequisite, not an addition

DDC has no HTTPS today. There is no certificate and `SESSION_COOKIE_SECURE`
must stay `False`.

A TOTP code sent over plain HTTP on the LAN is readable by anyone on the
network and replayable inside its 30-second window. The session cookie it
protects is readable for its entire lifetime. **2FA over HTTP raises the bar
against a leaked password and against nothing else.**

If the point of v3.0 is "credential X cannot lead to root", the network path
has to be closed first. Cheapest honest answer: terminate TLS in front of DDC
(the reference Unraid setup can use the NginxProxyManager many users already
run), document it, and treat the connection as secure when a **trusted** proxy
says so. Second option: ship a self-signed certificate with a documented trust
step.

**(revised) What "a proxy header says so" already looks like today, and why it
is not decision-free:**

- `app/web/extensions.py:20` already wraps the app in
  `ProxyFix(x_for=1, x_proto=1, x_host=1, x_port=1)` (called from
  `app_factory.py:50`), and `run.py:67-74` starts waitress without
  `trusted_proxy`. `ProxyFix` does not check who sends the headers; it believes
  the first hop. Anyone who reaches port 9374 directly sets `X-Forwarded-For`
  and `X-Forwarded-Proto` themselves.
- That is a bug today, independent of TLS: the login and setup rate limiter
  keys on `request.remote_addr` (`app/auth.py:152`; 5/min on `/setup`, 100/min
  with an `Authorization` header). A direct client rotates `X-Forwarded-For`
  and is never limited. The action log (`action_log_routes.py:33`) and the
  donation tracker (`donation_tracking_service.py:120-122`) record the forged
  address. Fixing this is step 2 of §7 and needs no decision.
- A forged `X-Forwarded-Proto: https` mostly hurts the forger (they get a
  `Secure` cookie). The real gap is the other way round: as long as DDC keeps
  accepting plain HTTP on `0.0.0.0:9374`, the reverse proxy is optional, and
  "2FA only over TLS" holds only for the users who actually put one in front.
- `SESSION_COOKIE_SECURE` is a static Flask setting, not a per-request one.
  "Flip it when the header says so" means either an explicit
  `DDC_BEHIND_TLS_PROXY=1` mode (cookie `Secure`, plain requests from
  non-proxy addresses refused or redirected) or custom cookie code. The mode is
  the simpler and more honest of the two.

So the TLS work is: (a) trusted-proxy list, with a test that sends a forged
`X-Forwarded-For` from an untrusted address and expects the real address to be
counted; (b) a documented behind-proxy mode that sets the cookie flag and
refuses plain direct access; (c) the reverse-proxy documentation. Only (a) is
decision-free.

**TLS ships before or with the 2FA wizard. Not after.**

### 5.2 What the lock can and cannot be

"Changes cannot be made via env variables or text files" cannot hold against
whoever owns the filesystem. Anyone with root on the Unraid host can edit any
file DDC reads, and trying to prevent that produces complexity and a false
promise at the same time.

The boundary that can hold, and that should be written down as *the* boundary:

> A remote attacker holding the web panel password cannot widen DDC's Docker
> permissions without the second factor.

The person with root on the host is outside the model, deliberately and
explicitly.

### 5.3 Lockout is the likely failure, not compromise

Forcing 2FA at first boot on a homelab tool, with no recovery path, will lock
people out — phone lost, phone reset, QR code never scanned. That is a
certainty at the download volume DDC has; an actual attack is not.

So: recovery codes shown once at setup, and a documented break-glass on the
host filesystem. The break-glass is not a hole in §5.2 — the host owner was
never inside the model.

### 5.4 Scope

- PyOTP, a QR code at setup, six-digit verification on permission changes.
- Forced at first boot **only if** §5.1 is satisfied. 2FA over plain HTTP is
  theatre and would cost real users their access for no real gain.
- The permission set of §4.2 is hardcoded and has no runtime switches, so on
  first release there may be nothing for the lock to guard. That is fine and
  worth stating: the lock exists for the moment a permission becomes
  configurable, and shipping it early means it is not bolted on later.

### 5.5 Downgrade to v2.4.1 **(revised, new)**

The mech snapshot is safe: `services/mech/progress_service.py:139-156` is not
touched by any step here, and `tests/unit/audit_2026_09/test_r2_g5_mech.py`
pins it to v2.3.1.

The configuration is not: v2.4.1's `extract_docker_config` and its siblings
(`config_validation_service.py:107-115`) copy only the keys they know, so a
v2.4.1 that loads a v3.0 config drops the 2FA secret and the proxy settings on
its first save. After a re-upgrade 2FA would be silently off. That is read from
the extractor, not yet exercised. Rule for step 9: 2FA secrets and recovery
codes live in their own file that v2.4.1 never writes, the same way the mech
snapshot survived the v2.3 → v2.4 round trip, and step 11 proves it with a
downgrade test.

---

## 6. What v2.4 owes v3.0

### The eight places that build a Docker client

Measured in the v2.4.1 tree **(revised: the fallback row was wrong)**:

| Site | Socket resolution | Timeout |
|---|---|---|
| `docker_client_pool.py:565-600` `_create_new_client_async` | config path **first**, then `from_env()` | 30 |
| `docker_client_pool.py:735-752` `get_docker_client_async` ("TEMPORARY FALLBACK") | config path **first**, then `from_env(timeout=..)` | the caller's `timeout` argument, default 30 |
| `docker_utils.py:496-512` | `from_env()` **first**, then hardcoded | `DEFAULT_CONTAINER_LIST_TIMEOUT` (Advanced Setting) |
| `container_log_service.py:214` | hardcoded `unix:///var/run/docker.sock` | 30 |
| `web_helpers.py:281` | `from_env()` | `BACKGROUND_REFRESH_TIMEOUT` (Advanced Setting) |
| `web_helpers.py:557` | hardcoded `unix:///var/run/docker.sock` | **5** (fast diagnostic probe) |
| `status_info_integration.py:53` | `from_env()` | default (60) |
| `docker_utils.py:453` `get_docker_client_async` → `individual_client` **(revised, found by the ratchet)** | `from_env()`, only when the pool is off or fails to import | default (60) |

Two honour `docker_config.docker_socket_path` (both pool entry points, same
order). Three hardcode the default socket path. Only `docker_utils.py` resolves
in the opposite order. None of the eight passes `version=` (§3).

**(revised)** The first count and the independent review both found seven. The
syntax-tree ratchet `tests/spec/test_every_docker_client_site_is_known.py`
found the eighth: the pool sites pass `docker.DockerClient` to
`asyncio.to_thread` as a callable, and a text search for `DockerClient(` or
`from_env` by site misses such shapes.

**Why this matters for v3.0:** `docker.from_env()` reads `DOCKER_HOST`. Point
`DOCKER_HOST` at the proxy and the `from_env()` sites migrate for free —
while the three hardcoded sites, and the two config-path sites whenever
`docker_socket_path` is set, keep talking to the socket directly, past the
proxy. Both paths work, so **no test would catch it.** A proxy that sees part
of the traffic is worse than no proxy, because it produces a security claim
that is false.

**(revised) Where `DOCKER_HOST` is set today:** in `docker-compose.yml:33` and
nowhere else. The running Unraid container has no `DOCKER_HOST` in its
environment (measured with `docker inspect`); `from_env()` there falls back to
the default socket. So "point `DOCKER_HOST` at the proxy" must happen in the
image or the entrypoint, not only in compose, or Unraid users keep the raw
socket. The `docker_socket_path` Advanced Setting becomes meaningless with the
proxy and is retired in the same step, with a migration note.

### Why the consolidation is NOT being done in v2.4

The eight sites are not eight copies of one thing. They use five different
timeouts and two opposing resolution orders. Collapsing them changes behaviour:

- `web_helpers.py:553` uses `timeout=5` because it is a diagnostic that must
  fail fast. Give it 30 and a web page hangs for 30 seconds.
- Two of the timeouts are Advanced Settings the operator can tune. A single
  shared timeout discards that configuration silently.
- Both pool sites resolve the config path first; `docker_utils` resolves
  `from_env()` first. Choosing one order can flip which installation works.

The last point is the irreducible one: an installation with `DOCKER_HOST`
pointing at one daemon and `docker_socket_path` at another gets a different
daemon depending on the order, and such an installation cannot be seen from
inside this repository.

**Measured mitigation:** DDC's own `docker-compose.yml:33` sets
`DOCKER_HOST: unix:///var/run/docker.sock`, the same path the config defaults
to. In every deployment DDC documents, both orders point at the same daemon, so
the risk exists only in a hand-built configuration that DDC does not describe.
Real, but confined.

### What v2.4 should do instead: the inventory as a test

No production code changes. A guard that pins these eight sites and fails when
an eighth appears — the same shape as the ratchets in `tests/spec/` (for
example `test_z10_ci_test_gate.py`, which reads the workflow YAML and fails
when the gate is loosened). **(revised)** The guard pins the table above as it
*is*, including the fallback row, and it also pins "no site passes `version=`"
so that the day the factory starts pinning the version, the guard is updated
on purpose rather than silently.

- Risk to existing installations: none. It touches no runtime path.
- Value: v3.0 inherits a maintained checklist instead of a `grep`, and nobody
  adds an eighth bypass in the meantime.

The consolidation itself belongs inside v3.0, where the socket handling changes
anyway, where a major version number justifies the behaviour change, and where
it can be stated in the release notes.

---

## 7. Order of work, and what must be true before each step

**(revised)** The two research steps of the first version are done (§4.1,
§4.3); their place is taken by two fixes that are due today.

| # | Step | Cannot start before |
|---|---|---|
| 0 | v2.4.1 released | done |
| 1 | Inventory guard for the eight client sites (§6), and delete the dead `analyze_docker_stats_performance` so `GET /info` is not part of the surface | 0 |
| 2 | Trusted-proxy list for the forwarded headers (§5.1 a), with the forged-`X-Forwarded-For` test; fixes today's rate-limiter bypass | 0 |
| 3 | **Operator decision: one container (with all four conditions of §4.3) or two containers** | — (both measurements exist) |
| 4 | End-to-end test: a real docker-py client through the proxy (§4.2) — written first, red until step 5 | 3 |
| 5 | The allowlist proxy, nine endpoints, path-only matching, one test per denied endpoint | 4 |
| 6 | Single client factory: `timeout` required per caller, `version=` pinned, `DOCKER_HOST` set by the image/entrypoint, `docker_socket_path` retired | 1, 5 |
| 7 | Root-owned `/app`, entrypoint without `chown /app`, proxy outside `ddc` paths, the write-attempt test (§4.3) — decided: one container | 3 |
| 8 | Behind-proxy mode (§5.1 b), reverse-proxy documentation (§5.1 c), and the self-signed fallback certificate with renewal and trust step — decided: both | 2 |
| 9 | 2FA wizard (offered, not forced — decided), recovery codes, documented break-glass; secrets in a file v2.4.1 never rewrites (§5.5) | 8 |
| 10 | Rewrite `SECURITY.md`: drop the `:ro` claim, state the three doors of §1, the boundary of §5.2 and the read exposure of §3 | 5, 9 |
| 11 | Upgrade test from v2.4.1 and downgrade test to v2.4.1 (§5.5); `/health` distinguishes "proxy unreachable" from "Docker unreachable" | 6, 9 |

Steps 1 and 2 need no decision and carry no risk. Step 3 is the one that needs
the operator.

---

## 8. Decided, and open

**Decided in this plan:**
- An explicit method-plus-path allowlist, not Tecnativa's section filter (§4.2).
- The allowlist has nine entries: the eight DDC calls plus docker-py's implicit
  `GET /version`; it is proven by an end-to-end test from DDC's side (§3, §4.2).
- TLS before or with 2FA, never after (§5.1).
- Forwarded headers are trusted only from a configured proxy address; the
  bypass of today's rate limiter is fixed before anything else (§5.1).
- The security boundary excludes the host root owner, explicitly (§5.2).
- Recovery codes plus a host-filesystem break-glass (§5.3).
- 2FA state lives in a file v2.4.1 never rewrites; a downgrade test proves it (§5.5).
- The client-site consolidation happens in v3.0, not v2.4 (§6).
- `SECURITY.md`'s read-only-socket claim is removed, and the read exposure of
  `inspect` and `logs` is stated (§2, §3).

**Decided by the operator on 2026-09-22:**
1. **One container**, with all four conditions of §4.3: root-owned `/app` and
   entrypoint, no `chown /app` in the entrypoint (the NAS permission fix is
   limited to `config/`, `logs/` and `cached_*`), proxy outside every
   `ddc`-writable path, and the write-attempt test. The release-note claim is
   "DDC's code cannot reach anything but the allowed endpoints", not "DDC has
   no socket". Two containers stay described in §4.3 as the comparison, and
   are not built.
2. **2FA is offered and strongly recommended, not forced.** Setup dialog at
   first boot with a "later" button, and a persistent panel notice while it is
   off. Nobody gets locked out.
3. **TLS: both.** A reverse proxy is the recommended way, with the
   behind-proxy mode of §5.1; a self-signed certificate in the image is the
   fallback for installations without a proxy, with a documented trust step
   and renewal.
4. **A tenth, read-only endpoint is reserved:** `GET /images/{name}/json`
   (`RepoDigests`) for the image-update notice planned after v3.0. It goes
   into the allowlist, the inventory guard and the end-to-end test now, and
   `SECURITY.md` names it as read-only, so the later feature does not widen
   the proxy after the fact.

**Measured, no longer open:**
4. Tecnativa's `CONTAINERS=1` plus `POST=1` admits `/containers/create` and
   `/containers/{id}/exec` (§4.1, `haproxy.cfg` lines 48 and 60).
5. DDC's uid 1000 reaches the socket through gid 281 membership set up by the
   Dockerfile and the entrypoint; a second uid can be kept out of the group,
   but `/app` being `ddc`-owned and executed by root at start is a route around
   it (§4.3).
