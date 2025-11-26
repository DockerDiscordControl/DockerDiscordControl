# Security

DDC is designed with security in mind, controlling access to critical Docker infrastructure.

---

## Zero Internet Exposure Architecture

DDC follows a **local-only architecture** where the Web UI never needs to be exposed to the internet. This eliminates entire attack vectors.

```
┌─────────────────────────────────────────────────────────────────────┐
│                           INTERNET                                  │
│                                                                     │
│   ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐     │
│   │  Zapier  │    │  IFTTT   │    │  GitHub  │    │ Steam DB │     │
│   └────┬─────┘    └────┬─────┘    └────┬─────┘    └────┬─────┘     │
│        │               │               │               │            │
│        └───────────────┴───────────────┴───────────────┘            │
│                                │                                    │
│                                ▼                                    │
│                    ┌───────────────────┐                            │
│                    │   Discord API     │  ◄── Outbound only         │
│                    │ (discord.com)     │                            │
│                    └─────────┬─────────┘                            │
│                              │                                      │
└──────────────────────────────┼──────────────────────────────────────┘
                               │
              ─ ─ ─ ─ ─ ─ ─ ─ ─│─ ─ ─ ─ ─ ─ ─ ─ ─  FIREWALL
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│                       YOUR LOCAL NETWORK                             │
│                                                                      │
│   ┌─────────────────────────────────────────────────────────────┐   │
│   │                      DDC Container                          │   │
│   │                                                             │   │
│   │   ┌─────────────┐         ┌─────────────┐                  │   │
│   │   │  Discord    │◄───────►│ Automation  │                  │   │
│   │   │    Bot      │         │  Service    │                  │   │
│   │   └─────────────┘         └──────┬──────┘                  │   │
│   │          │                       │                          │   │
│   │          ▼                       ▼                          │   │
│   │   ┌─────────────┐         ┌─────────────┐                  │   │
│   │   │   Web UI    │         │   Docker    │                  │   │
│   │   │  (Port 9374)│         │   Socket    │                  │   │
│   │   └─────────────┘         └─────────────┘                  │   │
│   │          │                                                  │   │
│   └──────────┼──────────────────────────────────────────────────┘   │
│              │                                                      │
│              ▼                                                      │
│   ┌─────────────────┐                                               │
│   │  Local Browser  │  ◄── 192.168.x.x:9374 only                    │
│   │  (Admin Access) │                                               │
│   └─────────────────┘                                               │
│                                                                      │
│   ❌ No port forwarding                                              │
│   ❌ No reverse proxy required                                       │
│   ❌ No public IP exposure                                           │
│   ✅ Full functionality via Discord                                  │
│   ✅ External automation via Discord webhooks                        │
└──────────────────────────────────────────────────────────────────────┘
```

### Why This Works

| Component | Internet Exposure | Risk Level |
|:----------|:-----------------|:-----------|
| **Web UI** | None (LAN only) | Minimal |
| **Discord Bot** | Outbound only | Low (Discord handles auth) |
| **Docker Socket** | None | Minimal (local only) |
| **Automation (AAS)** | None (via Discord relay) | Low |

### Security Benefits

1. **No Attack Surface**: No open ports = no direct attacks possible
2. **No Vulnerability Exposure**: Even if DDC had a bug, attackers can't reach it
3. **No SSL/TLS Required**: Local network traffic doesn't need encryption
4. **No Reverse Proxy Needed**: Simpler setup, fewer components to secure
5. **Discord as Gatekeeper**: All external communication goes through Discord's security

### External Automation Without Exposure

For services like Zapier, IFTTT, or GitHub Actions, DDC uses **Discord Webhooks as a secure relay**:

```
External Service → Discord Webhook → Discord Channel → DDC Bot → Docker Action
```

The Web UI **never** needs to be accessible from the internet. See [Auto-Action System](Auto_Action_System.md#external-service-integration-zapier-ifttt-n8n) for detailed examples.

### Recommended Network Configuration

```
Firewall Rules:
├── ALLOW: DDC → discord.com (outbound, TCP 443)
├── ALLOW: LAN → DDC:9374 (local only)
├── BLOCK: Internet → DDC:9374 (no inbound)
└── BLOCK: DDC → Internet (except Discord)
```

For Docker users:
```yaml
# docker-compose.yml
ports:
  - "127.0.0.1:9374:9374"  # Bind to localhost only (optional extra safety)
  # OR
  - "192.168.1.100:9374:9374"  # Bind to specific LAN IP
  # NOT
  # - "0.0.0.0:9374:9374"  # Avoid binding to all interfaces
```

---

## Web Dashboard Security

### Authentication
*   **Login Required**: The Web UI is protected by a login page.
*   **Single Admin User**: Currently, DDC supports a single admin user (default: `admin`).
*   **Password Hashing**: Passwords are never stored in plain text. They are hashed using secure algorithms before storage in `web_config.json`.
*   **Session Timeout**: Sessions automatically expire after a configurable time (Default: `3600s` / 1 hour).

### Best Practices
*   **Change Default Password**: Always change the default password immediately after installation.
*   **Keep it Local**: DDC is designed to run on your local network only. There is **no need** to expose it to the internet.
*   **Bind to LAN IP**: Use `192.168.x.x:9374:9374` in your Docker port mapping instead of `0.0.0.0:9374:9374`.
*   **Use Discord for Remote Access**: Control containers via Discord from anywhere - no VPN or port forwarding needed.

## Discord Security

### Permissions
The Bot requires specific permissions to function:
*   **Read/Send Messages**: To post status updates and respond to commands.
*   **Embed Links**: For rich status displays.
*   **Use External Emojis**: For custom UI elements.
*   **Manage Messages**: To clean up old status messages (optional but recommended).

### Intents
DDC uses `py-cord` and requires the following privileged intents in the Discord Developer Portal:
*   **Message Content Intent**: Required to read commands.

## Docker Security

### Socket Access
DDC requires access to the Docker Socket (`/var/run/docker.sock`) to control containers.
*   **Implication**: This grants the container effectively root-level access to the host system's Docker daemon.
*   **Mitigation**:
    *   **Keep DDC local-only** - the primary protection is not exposing the service
    *   Run DDC in an isolated Docker network if possible
    *   Use a Docker socket proxy (e.g., `tecnativa/docker-socket-proxy`) for fine-grained control
    *   Never expose port 9374 to the public internet

---

## Comparison: DDC vs. Traditional Approaches

| Approach | Internet Exposure | Complexity | Security Risk |
|:---------|:------------------|:-----------|:--------------|
| **DDC (Local + Discord)** | None | Low | Minimal |
| Portainer (exposed) | Full Web UI | Medium | High |
| SSH + Scripts | SSH port open | High | Medium |
| VPN + Web Panel | VPN port open | High | Medium |
| Reverse Proxy + Auth | HTTPS port open | Very High | Medium |

DDC's architecture eliminates the need for:
- VPN setup and maintenance
- SSL certificate management
- Reverse proxy configuration
- Dynamic DNS for home networks
- Port forwarding on routers

---

## Security Checklist

- [ ] Changed default Web UI password
- [ ] DDC port (9374) not exposed to internet
- [ ] Docker port binding uses LAN IP (not `0.0.0.0`)
- [ ] Discord bot token kept secret
- [ ] Protected containers list configured in AAS
- [ ] Webhook URLs kept private (for AAS integrations)

---

*Last updated: November 26, 2025*
