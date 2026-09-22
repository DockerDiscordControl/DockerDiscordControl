# DockerDiscordControl - Security Model

This document says what DDC protects, against whom, and what it does not. It is
written to be checked: every claim here has a test or a script behind it
(named in brackets). Where something is not protected, it says so.

## Three doors

| Door | Who comes through it | What closes it |
|---|---|---|
| **A. The Docker API** | anything that can reach the Docker socket: DDC's own code, a dependency, an attacker with code execution in the container | the allowlist proxy - DDC's code reaches only the endpoints listed below |
| **B. The web panel** | whoever has the panel password - reused, leaked or guessed | two-factor authentication, set up over HTTPS |
| **C. The Discord bot** | whoever has the bot token, or can write in a control channel | the channel permission model: the bot starts, stops and restarts configured containers, nothing else |

**2FA does not protect the Discord bot, and the proxy does not protect the web
panel.** Each door has its own lock.

## The boundary

> A remote attacker holding the web panel password cannot widen DDC's Docker
> permissions without the second factor, and DDC's code cannot reach anything
> but the allowed Docker endpoints.

Whoever has root on the host stands outside this boundary, deliberately: they
can read and change every file DDC uses. The 2FA break-glass
(`scripts/disable_2fa.py`) relies on exactly that.

## Door A: the Docker allowlist proxy

DDC runs in one container with two users. `ddcproxy` is the only user in the
Docker socket's group and runs a small allowlist proxy
(`services/docker_proxy/allowlist_proxy.py`, stdlib only). DDC itself runs as
`ddc`, is not in the socket's group, and reaches Docker only through the proxy
(`DOCKER_HOST=unix:///run/ddc-proxy/docker.sock`).

The proxy passes these requests, matched on method and path with the query
string stripped, and answers everything else with 403:

```
GET   /_ping                     (and HEAD)
GET   /version                   docker-py negotiates the API version with it
GET   /containers/json
GET   /containers/{id}/json
GET   /containers/{id}/logs
GET   /containers/{id}/stats
POST  /containers/{id}/start
POST  /containers/{id}/stop
POST  /containers/{id}/restart
GET   /images/{name}/json        reserved, read-only (image-update notice)
```

`POST /containers/create`, `exec`, `kill`, `archive`, `/info`, `/events` and
every image, volume or network change are unreachable by construction
[tests/spec/test_the_docker_proxy_lets_through_only_what_ddc_needs.py]. Every
Docker client DDC builds goes through one factory that follows `DOCKER_HOST`
[tests/spec/test_every_docker_client_site_is_known.py].

**What the allowed endpoints still expose.** The allowlist limits what can be
*done*, not what can be *read*:

- `GET /containers/{id}/json` returns the container's configuration,
  including its **environment variables** - often passwords and tokens.
- `GET /containers/{id}/logs` returns whatever the container logs, and
  secrets in logs are common.

Anyone who gets through door B or door C can read both for every configured
container. The proxy does not change that.

**What keeps DDC out of its own start.** The code under `/app`, the entrypoint
and the proxy copy in `/opt/ddc-proxy` belong to root and are read-only for
`ddc`; only `config/`, `logs/`, `cached_displays/` and `cached_animations/`
belong to `ddc`. Otherwise code running as `ddc` could rewrite the entrypoint
that root runs at the next start. `scripts/check_image_boundary.sh` attempts
all of this as `ddc` in a running container and fails if any attempt succeeds.

**Not a boundary: the read-only socket mount.** `:ro` on
`/var/run/docker.sock` makes the socket file unmodifiable and does not restrict
the API behind it at all - it is no protection and is not relied on.

**Limits of the one-container design.** If the host's socket is world-writable
(mode 666), or `PGID` equals the socket's group, `ddc` can open the socket
directly and the proxy does not bind DDC. The entrypoint says so loudly at
start. A container started with `--user` has no root phase, so no proxy runs;
the entrypoint then warns that DDC uses the raw socket.

## Door B: the web panel

- **Password:** PBKDF2-SHA256 with 600,000 iterations. Login and setup attempts
  are rate-limited per client address.
- **Client address:** `X-Forwarded-For` / `-Proto` are believed only from the
  proxies in `DDC_TRUSTED_PROXIES`; a direct client cannot pick its own
  address to escape the rate limits
  [tests/spec/test_a_forged_forwarded_header_is_not_believed.py].
- **TLS (`DDC_TLS_MODE`):** `off` (default) is plain HTTP and the session
  cookie is not `Secure`. `proxy` (recommended: TLS at your reverse proxy)
  makes the cookie `Secure` and refuses plain requests that did not come
  through a trusted proxy over HTTPS. `self-signed` has DDC serve HTTPS itself
  with a certificate in `config/tls/`; compare the SHA-256 fingerprint in the
  log once [tests/spec/test_tls_modes_are_what_they_say.py].
- **Two-factor authentication:** offered and strongly recommended, never
  forced; it can only be set up over HTTPS. With it on, the password alone does
  not open the panel. Codes are TOTP (RFC 6238), each usable once, attempts
  rate-limited; ten recovery codes are shown once and stored as hashes. The
  state lives in `config/two_factor.json` (mode 0600), a file older DDC
  versions never rewrite. Lost phone and codes: on the host, run
  `docker exec -it -u ddc <container> python3 scripts/disable_2fa.py`.

## Door C: the Discord bot

Authorization is by Discord channel, by design: a control channel may control
the containers configured for it, a status channel may only show them. The
bot never changes proxy permissions. Treat write access to a control channel
like the panel password.

## Bot token

The token can come from the `DISCORD_BOT_TOKEN` environment variable or the
web panel; stored in the configuration it is encrypted.

## History: fixes before v3.0

### 2025-11-18: Multiple CodeQL Security Alerts Resolved

All CodeQL security vulnerabilities identified by static analysis have been fixed in v2.0.0:

#### 1. DOM-based XSS Vulnerability - Alert Messages (High Severity)
- **Alert:** js/xss-through-dom
- **Location:** app/templates/config.html (lines 1378, 1488)
- **Vulnerability:** User-controlled data inserted into DOM using innerHTML without sanitization
- **Attack Vector:** Malicious input could execute arbitrary JavaScript
- **Fix Applied:** Replaced unsafe innerHTML with safe DOM manipulation
- **Commit:** 55dea35fadfe89661041a6495c489a1e8bf1072a
- **Impact:** XSS attacks prevented, user input automatically escaped

Technical Details:
```javascript
// BEFORE (Vulnerable):
successDiv.innerHTML = `<div>${message}</div>`;

// AFTER (Secure):
const alertDiv = document.createElement('div');
alertDiv.textContent = message;  // Auto-escapes HTML
```

#### 2. DOM-based XSS Vulnerability - Container Info Modal (High Severity)
- **Alert:** js/xss-through-dom
- **Location:** app/static/js/config-ui.js (line 129)
- **Vulnerability:** Container name concatenated into innerHTML without escaping
- **Attack Vector:** Malicious container name could execute JavaScript: `<img src=x onerror=alert(1)>`
- **Fix Applied:** Split into safe innerHTML for static content + textContent for containerName
- **Commit:** ce0d3d7 (2025-11-18)
- **Impact:** Prevents XSS via container name injection

Technical Details:
```javascript
// BEFORE (Vulnerable):
modalLabel.innerHTML = '<i class="bi bi-info-circle"></i> ... - ' + containerName;

// AFTER (Secure):
modalLabel.innerHTML = '<i class="bi bi-info-circle"></i> ... - ';
modalLabel.appendChild(document.createTextNode(containerName));
```

#### 3. Information Exposure Through Exceptions (Medium Severity)
- **Alert:** py/stack-trace-exposure
- **Locations:** 18 endpoints across 3 blueprint files
- **Vulnerability:** Internal error details exposed to external users
- **Attack Vector:** Error messages revealed application structure
- **Fix Applied:** Generic user-facing error messages with detailed server-side logging
- **Commit:** 9fddd34eda4ca2a0f89265638f685d1dffcb84b0
- **Impact:** Application internals no longer exposed

Technical Details:
```python
# BEFORE (Insecure):
return jsonify({'error': result.error}), 500

# AFTER (Secure):
logger.error(f"Failed: {result.error}", exc_info=True)
return jsonify({'error': 'Failed to fetch data'}), 500
```

#### 4. Incomplete URL Substring Sanitization - Part 1 (Medium Severity)
- **Alert:** py/incomplete-url-substring-sanitization
- **Location:** cogs/status_info_integration.py (line 1186)
- **Vulnerability:** Simple substring check could be bypassed
- **Attack Vector:** Malicious URL like "https://evil.com/ddc.bot" would match
- **Fix Applied:** Secure URL validation using endswith() and exact match
- **Commit:** c6606a937c39d0567c6a67b40fc7102f90993816
- **Impact:** URL injection attacks prevented

Technical Details:
```python
# BEFORE (Vulnerable):
if "https://ddc.bot" in current_footer:

# AFTER (Secure):
if current_footer.endswith("https://ddc.bot") or current_footer == "https://ddc.bot":
```

#### 5. Incomplete URL Substring Sanitization - Part 2 (Medium Severity)
- **Alert:** py/incomplete-url-substring-sanitization
- **Location:** cogs/status_info_integration.py (line 1188)
- **Vulnerability:** replace() method replaced ALL occurrences, not just the suffix
- **Attack Vector:** Footer "Visit https://ddc.bot.evil.com • https://ddc.bot" would pass endswith() check but replace() would affect BOTH URLs
- **Fix Applied:** Use removesuffix() to only replace the URL at the end
- **Commit:** c36164a (2025-11-18)
- **Impact:** Prevents URL manipulation attacks

Technical Details:
```python
# BEFORE (Vulnerable):
enhanced_footer = current_footer.replace("https://ddc.bot", "ℹ️ Info Available • https://ddc.bot")

# AFTER (Secure):
prefix = current_footer.removesuffix("https://ddc.bot")
enhanced_footer = prefix + "ℹ️ Info Available • https://ddc.bot"
```

#### 6. Information Exposure Through Exceptions - Mech Reset Failure (Medium Severity)
- **Alert:** py/stack-trace-exposure
- **Location:** app/blueprints/main_routes.py (mech reset endpoint - failure path)
- **Vulnerability:** Internal error details from `result.message` exposed to users
- **Attack Vector:** Exception messages revealed file paths, method names, service structure
- **Fix Applied:** Log detailed errors server-side, return generic messages to users
- **Commit:** 4b6acbb (2025-11-18)
- **Impact:** Prevents information disclosure

Technical Details:
```python
# BEFORE (Vulnerable):
response_data = {'message': result.message}  # Contains "Error: /path/to/file.json"
return jsonify(response_data), 400

# AFTER (Secure):
current_app.logger.error(f"Mech reset failed: {result.message}", exc_info=True)
return jsonify({'error': 'Failed to reset mech system'}), 500
```

#### 6b. Information Exposure Through Exceptions - Mech Reset Success (Defense-in-Depth)
- **Alert:** py/stack-trace-exposure (CodeQL data flow analysis)
- **Location:** app/blueprints/main_routes.py (mech reset endpoint - success path)
- **Vulnerability:** CodeQL flagged that `result.message` and `result.details['operations']` could contain exception data
- **Attack Vector:** CodeQL's taint tracking cannot statically prove filtering logic prevents all exception exposure
- **Fix Applied:** Multi-layer defense with hardcoded messages + strict allowlist for operations
- **Commits:** 0e543fa, [current] (2025-11-18)
- **Impact:** Complete prevention of exception exposure through success responses

Technical Details:
```python
# BEFORE (Safe but flagged by CodeQL):
response_data = {
    'message': result.message,  # CodeQL: Can't prove this is safe
    'previous_status': current_status,
    'operations': result.details['operations']  # Tainted data flow
}

# INTERMEDIATE (Filtered but still flagged):
safe_operations = [op for op in result.details['operations']
                   if not any(x in op for x in ['Exception', 'Error:'])]
response_data['operations'] = safe_operations  # Still tainted by data flow

# FINAL (Strict allowlist - breaks taint tracking):
SAFE_OPERATION_ALLOWLIST = {
    "Donations: All donations cleared",
    "Mech State: Mech state reset to Level 1",
    "Evolution Mode: Evolution mode reset to defaults",
    # ... predefined safe messages only
}
safe_operations = [op for op in result.details['operations']
                   if op in SAFE_OPERATION_ALLOWLIST]  # Only exact matches
response_data['operations'] = safe_operations  # Safe: allowlist validation
```

**Security Rationale:** Allowlist approach ensures only predefined, known-safe operation messages are included in API responses. CodeQL's data flow analysis recognizes this pattern as breaking the taint chain from potentially unsafe `result.details`.

#### 7. Information Exposure Through Exceptions - 12 API Endpoints (Medium Severity)
- **Alert:** py/stack-trace-exposure
- **Locations:** 12 endpoints across main_routes.py
- **Vulnerability:** `result.error` containing exception details returned to users
- **Attack Vector:** Internal errors exposed file paths, IOError details, service internals
- **Fix Applied:** Comprehensive fix across all endpoints with detailed logging
- **Commit:** eb81df6 (2025-11-18)
- **Impact:** Prevents information disclosure across entire API surface

**Affected Endpoints:**
- /api/containers/refresh
- /api/diagnostics/enable, disable, status
- /api/stats/performance
- /api/donations/manual, list, delete
- /api/mech/speed_config, difficulty (GET/POST/reset)

Technical Details:
```python
# BEFORE (Vulnerable):
return jsonify({'error': result.error}), 400  # Exposes "IOError: permission denied"

# AFTER (Secure):
current_app.logger.error(f"Operation failed: {result.error}", exc_info=True)
return jsonify({'error': 'Failed to process request'}), 500
```

#### 8. Information Exposure Through Exceptions - Mech Status Endpoint (Medium Severity)
- **Alert:** py/stack-trace-exposure (CodeQL alerts #21, #44)
- **Location:** app/blueprints/main_routes.py:1632 (/api/mech/status endpoint)
- **Vulnerability:** Service returns `{"error": "exception details"}` on exceptions, exposed to users
- **Attack Vector:** The `get_current_status()` service method returns error dictionaries containing exception messages (IOError, JSONDecodeError, etc.) which were passed directly to API responses. Additionally, tainted data could flow through list/string fields.
- **Fix Applied:** Three-layer defense: detect errors + strict type validation + exception marker filtering
- **Commits:** 36d95ec, [current] (2025-11-18)
- **Impact:** Complete prevention of exception exposure through status endpoint

Technical Details:
```python
# BEFORE (Vulnerable):
status = reset_service.get_current_status()  # May return {"error": "File I/O error: ..."}
return jsonify({
    'success': True,
    'status': status  # Error details + tainted data exposed to user
})

# AFTER (Secure - Three layers):
status = reset_service.get_current_status()

# Layer 1: Detect and handle error responses
if isinstance(status, dict) and "error" in status:
    current_app.logger.error(f"Mech status service error: {status['error']}", exc_info=True)
    return jsonify({'error': 'Failed to retrieve mech status'}), 500

# Layer 2: Strict type validation for complex fields
raw_glvl_values = status.get('glvl_values', [])
safe_glvl_values = []
if isinstance(raw_glvl_values, list):
    for val in raw_glvl_values:
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            safe_glvl_values.append(val)  # Only numeric values

# Layer 3: Exception marker filtering for strings
next_level_name = status.get('next_level_name', 'Unknown')
if not isinstance(next_level_name, str) or \
   any(x in str(next_level_name) for x in ['Exception', 'Error:', 'Traceback']):
    next_level_name = 'Unknown'

# Build safe status with fully validated fields
safe_status = {
    'donations_count': int(status.get('donations_count', 0))
                       if isinstance(status.get('donations_count'), (int, float)) else 0,
    'glvl_values': safe_glvl_values,  # Validated list
    'next_level_name': next_level_name,  # Filtered string
    # ... all fields with type validation
}
return jsonify({'success': True, 'status': safe_status})
```

**Security Rationale:** Multi-layer defense ensures no exception data can leak through any field type:
1. Error detection catches explicit error responses from service layer
2. Type validation ensures only expected data types (int, float, str) are included
3. Exception marker filtering prevents exception strings in text fields
4. List validation prevents malicious data in array fields (glvl_values)

This comprehensive approach satisfies CodeQL's taint tracking by breaking all possible data flow paths from potentially unsafe service responses.

---

## Security Incident Response

### If Token Compromised:
1. Immediately rotate Discord bot token in Developer Portal
2. Update environment variable or Web UI configuration with new token
3. Restart DDC container: `docker-compose restart`
4. Review logs for unauthorized access
5. Check Discord server for suspicious activity

### If Container Compromised:
1. Stop container immediately: `docker stop ddc`
2. Review logs: `docker logs ddc`
3. Check host system for signs of escape
4. Rebuild from clean image
5. Review and enhance security configuration

## Security Contact

For security issues:
1. Do not create public GitHub issues
2. Report privately to project maintainers
3. Include detailed reproduction steps
4. Wait for confirmation before public disclosure

---

**Note:** Security is an ongoing process. Regularly review and update your security configuration. Monitor the GitHub repository for security updates and advisories.
