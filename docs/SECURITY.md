# DockerDiscordControl - Security Guide

## Recent Security Fixes

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

---

## Security Best Practices

### Discord Bot Token Security

The Discord bot token can be provided via environment variable for enhanced security.

#### Environment Variable Method:
```bash
# Set in docker-compose.yml
environment:
  DISCORD_BOT_TOKEN: "your_token_here"
```

#### Configuration File Method:
Alternatively, configure via Web UI at http://your-server:9374

Security Benefits:
- Token not stored in plaintext when using environment variables
- Token not in version control
- Environment-based configuration
- Automatic fallback to Web UI configuration

### Docker Socket Security

**Important:** This application requires access to the Docker socket. Only deploy in trusted environments.

#### Security Features:
- Read-only Docker socket mounting (configured in docker-compose.yml)
- Non-root user execution (uid 1000, gid 1000)
- Resource limits (CPU, memory)
- Alpine Linux base with minimal attack surface

#### Deployment:
```bash
docker-compose up -d
```

#### Verification:
```bash
# Check container runs as non-root
docker exec ddc id

# Check resource limits
docker stats ddc

# Verify Docker socket permissions
docker exec ddc ls -la /var/run/docker.sock
```

### Session Security

#### Current Implementation:
- Strong password hashing (PBKDF2-SHA256, 600,000 iterations)
- Secure session cookies
- Rate limiting on authentication

#### Required Configuration:
1. **Set strong Flask secret key** via environment variable:
   ```bash
   FLASK_SECRET_KEY="$(openssl rand -hex 32)"
   ```

2. **Change default admin password** immediately after first login:
   - Default username: admin
   - Default password: setup
   - Change via Web UI Settings

3. **Enable HTTPS** in production environments (recommended)

## Quick Security Setup

### 1. Environment Variables:
```bash
# In docker-compose.yml or .env file
FLASK_SECRET_KEY="your-64-character-random-secret-key"
DISCORD_BOT_TOKEN="your-discord-token-here"
DDC_ADMIN_PASSWORD="your-secure-admin-password"
```

### 2. Generate Secure Keys:
```bash
# Generate Flask secret key
openssl rand -hex 32

# Use this in your docker-compose.yml or .env file
```

### 3. First-Time Setup:
1. Start container: `docker-compose up -d`
2. Access Web UI: `http://your-server:9374`
3. Login with: admin / setup
4. Immediately change password in Settings
5. Configure Discord bot token
6. Save configuration

## Security Checklist

### Completed Security Features:
- [x] CodeQL security alerts resolved (XSS, Exception Exposure, URL Sanitization)
- [x] Discord token via environment variable support
- [x] Enhanced Docker socket security
- [x] Non-root container execution
- [x] Resource limits and restrictions
- [x] Strong password hashing (PBKDF2-SHA256)
- [x] Alpine Linux base (minimal vulnerabilities)
- [x] Flask 3.1.1 and Werkzeug 3.1.3 (CVEs resolved)

### Recommended Additional Steps:
- [ ] Enable HTTPS with valid certificates
- [ ] Implement comprehensive rate limiting
- [ ] Add security headers (HSTS, CSP)
- [ ] Regular dependency updates
- [ ] Security monitoring and logging

### Known Limitations:
- Docker socket access provides significant container control
- Default credentials available for initial setup (must be changed)
- Some operations require elevated Docker permissions

## Additional Security Measures

### Network Security:
```yaml
# Recommended docker-compose.yml network configuration
networks:
  ddc_network:
    driver: bridge
```

### Monitoring:
```bash
# Monitor container logs
docker logs ddc

# Check for security events
docker logs ddc | grep -i "security\|error\|warning"
```

### Backup Security:
```bash
# Backup configuration securely
tar czf config_backup.tar.gz config/

# Store backups securely with restricted permissions
chmod 600 config_backup.tar.gz
```

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
