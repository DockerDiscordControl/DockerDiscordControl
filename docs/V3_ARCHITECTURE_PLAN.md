# DDC v3.0 — Security-by-Design architecture plan

**Status: not started. Nothing in this document is implemented.**
v2.4 is finalised first; v2.5 is skipped. Written 2026-09-22.

Every number in here was measured against the v2.4.0 tree, not estimated. Where
something could not be measured from inside this repository it says so.

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

This is the whole API surface, taken from every docker-py call in
`services/`, `cogs/` and `app/`:

```
GET  /_ping                      client.ping()
GET  /containers/json            client.containers.list()
GET  /containers/{id}/json       client.containers.get(), container.attrs
GET  /containers/{id}/logs       container.logs()
GET  /containers/{id}/stats      container.stats()
POST /containers/{id}/start      container.start()
POST /containers/{id}/stop       container.stop()
POST /containers/{id}/restart    container.restart()
```

Eight endpoints. Verified absent: `containers.create`, `containers.run`,
`container.remove`, `exec_run`, and every `images.*`, `networks.*` and
`volumes.*` call. DDC never creates, deletes or modifies a Docker object other
than changing the run state of a container that already exists.

**This is the single most useful fact in this document.** A surface of eight
endpoints is small enough to allowlist exactly, and an exact allowlist is what
turns the security claim from a hope into a property.

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
Tecnativa's `EXEC` section. **Needs verifying against the proxy's actual ACLs**
before any decision — if it is permitted by `CONTAINERS=1`, that is a second
full escape.

### 4.2 Decision: an explicit allowlist, not a section filter

Because the needed surface is eight endpoints (§3), the proxy should be a
method-plus-path allowlist and nothing else:

```
GET   ^/(v[0-9.]+/)?_ping$
GET   ^/(v[0-9.]+/)?containers/json
GET   ^/(v[0-9.]+/)?containers/[a-zA-Z0-9_.-]+/(json|logs|stats)$
POST  ^/(v[0-9.]+/)?containers/[a-zA-Z0-9_.-]+/(start|stop|restart)$
```

Everything else: 403, logged. Default deny, no env-var switches that can widen
it at runtime.

Properties this buys that a section filter does not:
- `POST /containers/create` is impossible to reach, by construction.
- The rule set fits on one screen and can be reviewed by a sceptical user in a
  minute. That matters: the objection being answered is a *trust* objection.
- It can be tested. A test per denied endpoint, plus a test that the eight
  allowed ones pass — the same shape as the 5,691 guards v2.4 already has.

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
escalation inside the container, and it depends on supervisord giving DDC no
route to run anything as the proxy's user. Both are checkable, and both must be
checked before this path is chosen — including how DDC reaches uid 1000 with
socket access today, which is not yet established.

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
run), document it, and flip `SESSION_COOKIE_SECURE` when a proxy header says
the connection is secure. Second option: ship a self-signed certificate with a
documented trust step.

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

---

## 6. What v2.4 owes v3.0

### The seven places that build a Docker client

Measured in the v2.4.0 tree:

| Site | Socket resolution | Timeout |
|---|---|---|
| `docker_client_pool.py` `_create_new_client_async` | config path **first**, then `from_env()` | 30 |
| `docker_client_pool.py:728` ("TEMPORARY FALLBACK") | `from_env()` | default (60) |
| `docker_utils.py:496/511` | `from_env()` **first**, then hardcoded | `DEFAULT_CONTAINER_LIST_TIMEOUT` (Advanced Setting) |
| `container_log_service.py:214` | hardcoded `unix:///var/run/docker.sock` | 30 |
| `web_helpers.py:280` | `from_env()` | `BACKGROUND_REFRESH_TIMEOUT` (Advanced Setting) |
| `web_helpers.py:553` | hardcoded `unix:///var/run/docker.sock` | **5** (fast diagnostic probe) |
| `status_info_integration.py:53` | `from_env()` | default (60) |

Exactly one honours `docker_config.docker_socket_path`. Three hardcode the
default socket path.

**Why this matters for v3.0:** `docker.from_env()` reads `DOCKER_HOST`. Point
`DOCKER_HOST` at the proxy and the three `from_env()` sites migrate for free —
while the three hardcoded sites keep talking to the socket directly, past the
proxy. Both paths work, so **no test would catch it.** A proxy that sees part
of the traffic is worse than no proxy, because it produces a security claim
that is false.

### Why the consolidation is NOT being done in v2.4

The seven sites are not seven copies of one thing. They use five different
timeouts and two opposing resolution orders. Collapsing them changes behaviour:

- `web_helpers.py:553` uses `timeout=5` because it is a diagnostic that must
  fail fast. Give it 30 and a web page hangs for 30 seconds.
- Two of the timeouts are Advanced Settings the operator can tune. A single
  shared timeout discards that configuration silently.
- The pool resolves the config path first; `docker_utils` resolves
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

No production code changes. A guard that pins these seven sites and fails when
an eighth appears — the same shape as `test_the_log_service_has_no_unreachable_helper`
and every other ratchet added in this audit.

- Risk to existing installations: none. It touches no runtime path.
- Value: v3.0 inherits a maintained checklist instead of a `grep`, and nobody
  adds an eighth bypass in the meantime.

The consolidation itself belongs inside v3.0, where the socket handling changes
anyway, where a major version number justifies the behaviour change, and where
it can be stated in the release notes.

---

## 7. Order of work, and what must be true before each step

| # | Step | Cannot start before |
|---|---|---|
| 0 | v2.4 finalised and released | — |
| 1 | Inventory guard for the seven client sites | 0 |
| 2 | Verify §4.1's open question: does `CONTAINERS=1` reach `POST /containers/{id}/exec`? | — (research, can run in parallel) |
| 3 | Establish how DDC reaches the socket as uid 1000 today, and whether UID separation is achievable in one container | — (research, can run in parallel) |
| 4 | **Operator decision: one container with UID separation, or two containers** | 2, 3 |
| 5 | TLS: reverse-proxy documentation, `SESSION_COOKIE_SECURE` driven by a forwarded-proto header | — |
| 6 | The allowlist proxy plus its test per denied endpoint | 4 |
| 7 | Single client factory, `timeout` a required argument per caller, `DOCKER_HOST` pointed at the proxy | 1, 6 |
| 8 | 2FA wizard, recovery codes, documented break-glass | 5 |
| 9 | Rewrite `SECURITY.md`: drop the `:ro` claim, state the three doors of §1 and the boundary of §5.2 | 6, 8 |

Steps 2, 3 and 5 need no decision and no risk. Step 4 is the one that needs the
operator.

---

## 8. Decided, and open

**Decided in this plan:**
- An explicit method-plus-path allowlist, not Tecnativa's section filter (§4.2).
- TLS before or with 2FA, never after (§5.1).
- The security boundary excludes the host root owner, explicitly (§5.2).
- Recovery codes plus a host-filesystem break-glass (§5.3).
- The client-site consolidation happens in v3.0, not v2.4 (§6).
- `SECURITY.md`'s read-only-socket claim is removed (§2).

**Open, for the operator:**
1. One container with UID separation, or two containers. §4.3.
2. Is 2FA forced at first boot, or offered and strongly recommended? Forcing it
   maximises the security claim and the lockout support load at the same time.
3. Does v3.0 ship its own TLS (self-signed plus trust step), or document a
   reverse proxy as the supported way?

**Open, needing measurement rather than a decision:**
4. Tecnativa's ACL for `POST /containers/{id}/exec` (§4.1) — only matters if
   the section-filter option is revived.
5. How DDC's uid 1000 reaches the socket today, and whether a second uid inside
   the container can be denied it (§4.3).
