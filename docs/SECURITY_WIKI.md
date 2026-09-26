# DockerDiscordControl - Security Guide

DockerDiscordControl v3.0 provides robust security features for managing Docker containers via Discord. This guide covers security best practices, configuration, and monitoring.

## ⚠️ Critical Security Warning

**Docker Socket Access:** DDC's container needs `/var/run/docker.sock`, which grants extensive control over your Docker environment. Since v3.0 only an allowlist proxy inside the container opens it, and DDC's own code can ask for ten things through it (see [SECURITY.md](SECURITY.md)). Whoever controls the host's Docker still controls the host.

**Deploy only in trusted environments with proper security controls.**

## Security Principles

### 1. Least Privilege
- Grant minimal necessary permissions
- Use Discord role-based access control
- Limit container control to specific channels
- Regularly audit permissions

### 2. Defense in Depth
Multiple security layers protect your deployment:
- Web UI authentication (password hash with PBKDF2-SHA256)
- Discord bot permissions and channel restrictions
- Container isolation and resource limits
- Non-root user execution (UID 1000, GID 1000)
- Alpine Linux base (94% fewer vulnerabilities)

### 3. Regular Maintenance
- Keep DDC updated (check https://github.com/DockerDiscordControl/DockerDiscordControl/releases)
- Update Docker and host system
- Monitor security advisories
- Review logs periodically

## Authentication & Access Control

### Web UI Security

**Default Credentials:**
- Username: `admin`
- Password: `setup`
- **⚠️ CHANGE IMMEDIATELY after first login!**

**Port Configuration:**
- Container port: `9374`
- Default host mapping: `9374:9374` (Unraid template)
- Configurable in docker-compose.yml

**Password Requirements:**
- Strong passwords (12+ characters recommended)
- Mix of uppercase, lowercase, numbers, symbols
- Hashing: PBKDF2-SHA256 with 600,000 iterations

**Access Web UI:**
```
http://your-server:9374
```

### Discord Bot Token Security

**Recommended: Environment Variable Method**
```yaml
# In docker-compose.yml
environment:
  DISCORD_BOT_TOKEN: "your_bot_token_here"
```

**Benefits:**
- Token not stored in plaintext files
- Token not in version control
- Easy rotation without config file edits
- Automatic fallback to Web UI config

**Alternative: Web UI Configuration**
- Configure at http://your-server:9374
- Encrypted storage using admin password
- Security audit available in Web UI

### Token Encryption

DDC v2.0 includes built-in token encryption:
- Uses admin password as encryption key
- PBKDF2-SHA256 key derivation
- AES encryption for stored tokens
- Security audit endpoint shows encryption status

## Network Security

### Port Management

**Bind to localhost only (recommended for local access):**
```yaml
ports:
  - "127.0.0.1:9374:9374"
```

**Firewall rules:**
```bash
# Allow only from specific IP
ufw allow from 192.168.1.0/24 to any port 9374

# Or allow from localhost only
ufw allow from 127.0.0.1 to any port 9374
```

### Reverse Proxy (HTTPS)

**Nginx example:**
```nginx
server {
    listen 443 ssl http2;
    server_name ddc.yourdomain.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    # Security headers
    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;

    location / {
        proxy_pass http://localhost:9374;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

**Tell DDC it runs behind TLS.** Set `DDC_TLS_MODE=proxy`: the session cookie becomes
`Secure`, and DDC refuses plain requests that did not come through the proxy over HTTPS
(except `/health`), so the proxy is not optional. Without a proxy, `DDC_TLS_MODE=self-signed`
lets DDC serve HTTPS itself; check the certificate fingerprint printed in the log once.

**Tell DDC which proxy to believe.** DDC ignores `X-Forwarded-*` unless the request
comes from an address in `DDC_TRUSTED_PROXIES` (addresses or CIDR ranges,
comma-separated), for example `DDC_TRUSTED_PROXIES=172.18.0.0/16` for a proxy in the
same Docker network. Without it, a client that reaches port 9374 directly could pick
its own address and escape the login and setup rate limits.

## Docker & Container Security

### Socket Security

**Current configuration (docker-compose.yml):**
```yaml
volumes:
  - /var/run/docker.sock:/var/run/docker.sock:ro
```

`:ro` makes the socket FILE unmodifiable; it does nothing to the API reached
through it. What limits DDC is the allowlist proxy: `ddcproxy` is the only user
in the socket's group, and DDC (`ddc`) reaches Docker through the proxy's own
socket.

**Verify:**
```bash
docker exec ddc id ddc
# ddc must NOT be in the group that owns /var/run/docker.sock
curl -s http://<host>:9374/health
# reports whether the proxy and Docker are reachable
```

### Container Isolation

**Resource limits (docker-compose.yml):**
```yaml
deploy:
  resources:
    limits:
      cpus: '2.0'      # Maximum CPU cores
      memory: 512M     # Maximum memory
    reservations:
      cpus: '0.25'     # Reserved CPU
      memory: 128M     # Reserved memory
```

**Security features:**
- Non-root user execution (UID 1000)
- Alpine Linux base (minimal attack surface)
- Docker API allowlist proxy (start, stop, restart, read-only queries)
- Resource limits prevent DoS
- Isolated network namespace

## Configuration Security

### Environment Variables

**Required configuration:**
```bash
# Generate secure Flask secret key
FLASK_SECRET_KEY=$(openssl rand -hex 32)

# Set in docker-compose.yml or .env file
FLASK_SECRET_KEY="your-64-character-hex-key"
DISCORD_BOT_TOKEN="your-discord-bot-token"  # Optional, can use Web UI
DDC_ADMIN_PASSWORD="your-secure-password"   # Optional, change via Web UI
```

### File Permissions

**Recommended permissions:**
```bash
# Configuration directory
chmod 750 ./config
chown 1000:1000 ./config

# Configuration files
chmod 640 ./config/*.json
chown 1000:1000 ./config/*.json

# .env file (if used)
chmod 600 .env
```

### Storage Security

**Configuration files location:**
- `/app/config/` (inside container)
- Mounted from `./config` (host)
- Contains encrypted tokens, channel settings, task configs

**Backup securely:**
```bash
# Backup configuration
tar czf ddc-config-backup-$(date +%Y%m%d).tar.gz config/

# Restrict backup permissions
chmod 600 ddc-config-backup-*.tar.gz
```

## Monitoring & Auditing

### Activity Monitoring

**Check logs:**
```bash
# Recent activity
docker logs ddc --tail 100

# Security events
docker logs ddc | grep -i "security\|login\|token\|password"

# Discord actions
docker logs ddc | grep -i "action:"
```

**Web UI Security Audit:**
- Access: http://your-server:9374 → Settings → Security
- Shows security score (0-100)
- Token encryption status
- HTTPS status
- Running as non-root
- Recommendations

### Log Monitoring

**Log configuration (docker-compose.yml):**
```yaml
logging:
  driver: json-file
  options:
    max-size: "10m"
    max-file: "3"
```

**Monitor regularly:**
```bash
# Continuous monitoring
docker logs ddc -f

# Check for errors
docker logs ddc 2>&1 | grep -i "error\|failed"
```

## Security Hardening Checklist

### Initial Setup
- [ ] Set `DDC_ADMIN_PASSWORD` environment variable (recommended)
- [ ] Or change temporary password `admin` / `setup` immediately
- [ ] Generate and set `FLASK_SECRET_KEY`
- [ ] Configure Discord bot token (environment variable recommended)
- [ ] Configure firewall rules
- [ ] Set proper file permissions (chmod 750 config/, chmod 640 config/*.json)
- [ ] Enable HTTPS via reverse proxy (production)

### Configuration
- [ ] Use Discord role-based permissions
- [ ] Limit container control to specific channels
- [ ] Configure resource limits (CPU, memory)
- [ ] Review security audit in Web UI
- [ ] Encrypt bot token (if not using environment variable)

### Ongoing Maintenance
- [ ] Regular DDC updates (check GitHub releases)
- [ ] Monitor logs weekly
- [ ] Review permissions monthly
- [ ] Test backups regularly
- [ ] Update Docker and host system

## Security Features in v2.0

### Implemented Security Measures

✅ **CodeQL Security Fixes:**
- DOM-based XSS vulnerabilities fixed
- Information exposure through exceptions prevented
- URL substring sanitization hardened
- Taint tracking compliance

✅ **Authentication:**
- Strong password hashing (PBKDF2-SHA256, 600,000 iterations)
- Secure session cookies
- Rate limiting on authentication

✅ **Token Security:**
- Environment variable support
- Optional encryption with admin password
- Security audit endpoint
- Migration helper for environment variables

✅ **Container Security:**
- Non-root user execution (UID 1000)
- Alpine Linux 3.22.2 base
- Resource limits (CPU, memory)
- Docker API allowlist proxy in front of the socket

✅ **Infrastructure:**
- Secure logging (no sensitive data)
- Action audit trail
- Security service with scoring

### Known Limitations

⚠️ **Docker Socket Access:**
- Provides extensive container control
- Cannot fully isolate from host Docker daemon
- Trusted environment required

⚠️ **Default Credentials:**
- Set `DDC_ADMIN_PASSWORD` environment variable before first start (recommended)
- If not set, temporary password is `admin` / `setup` - change immediately
- No lockout on failed attempts (yet)

⚠️ **Web UI Exposure:**
- HTTP by default; HTTPS through a reverse proxy (`DDC_TLS_MODE=proxy`) or a
  self-signed certificate (`DDC_TLS_MODE=self-signed`)
- Two-factor authentication is offered, and needs HTTPS
- Firewall rules recommended

## Common Security Pitfalls

### ❌ Don't:
1. Leave default credentials (`admin` / `setup`)
2. Expose Web UI to internet without HTTPS
3. Store secrets in version control
4. Grant excessive Discord permissions
5. Ignore security logs
6. Start the container with `--user` or put DDC into the socket's group - both go around the allowlist proxy
7. Skip regular updates

### ✅ Do:
1. Change default password immediately
2. Use environment variables for secrets
3. Enable HTTPS for remote access
4. Implement least privilege
5. Monitor logs regularly
6. Keep DDC updated
7. Backup configuration securely

## Security Incident Response

### If Discord Token Compromised

1. **Immediate action:**
   ```bash
   docker stop ddc
   ```

2. **Rotate token:**
   - Go to https://discord.com/developers/applications
   - Select your application
   - Bot → Reset Token
   - Copy new token

3. **Update configuration:**
   ```yaml
   # Update docker-compose.yml or .env
   DISCORD_BOT_TOKEN: "NEW_TOKEN_HERE"
   ```

4. **Restart DDC:**
   ```bash
   docker-compose up -d
   ```

5. **Review logs:**
   ```bash
   docker logs ddc | grep -i "unauthorized\|failed\|error"
   ```

6. **Check Discord server** for suspicious activity

### If Container Compromised

1. **Stop immediately:**
   ```bash
   docker stop ddc
   ```

2. **Review logs:**
   ```bash
   docker logs ddc > ddc-incident-$(date +%Y%m%d-%H%M%S).log
   ```

3. **Check host system:**
   ```bash
   # Check for unusual processes
   ps aux | grep docker

   # Check Docker events
   docker events --since '24h' | grep ddc
   ```

4. **Rebuild from clean image:**
   ```bash
   docker-compose down
   docker rmi dockerdiscordcontrol/dockerdiscordcontrol:latest
   docker-compose pull
   docker-compose up -d
   ```

5. **Review and enhance security:**
   - Audit firewall rules
   - Review file permissions
   - Check for unauthorized configuration changes
   - Rotate all secrets

## Additional Resources

### Documentation
- [Installation Guide](Installation-Guide.md)
- [Configuration](Configuration.md)
- [Troubleshooting](Troubleshooting.md)
- [Performance](Performance-and-Architecture.md)

### External Resources
- [Docker Security Best Practices](https://docs.docker.com/engine/security/)
- [Discord Developer Security](https://discord.com/developers/docs/topics/oauth2#security)
- [OWASP Container Security](https://owasp.org/www-project-docker-top-10/)

### Security Contact

**For security vulnerabilities:**
1. **Do not** create public GitHub issues
2. Report privately to project maintainers via GitHub Security Advisories
3. Include detailed reproduction steps
4. Allow time for fix before public disclosure

**GitHub Repository:**
https://github.com/DockerDiscordControl/DockerDiscordControl

---

**Last Updated:** 2025-01-18
**Version:** v2.0.0
**Security is an ongoing process.** Regularly review and update your configuration.
