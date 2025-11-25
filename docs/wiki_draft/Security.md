# Security

DDC is designed with security in mind, controlling access to critical Docker infrastructure.

## Web Dashboard Security

### Authentication
*   **Login Required**: The Web UI is protected by a login page.
*   **Single Admin User**: Currently, DDC supports a single admin user (default: `admin`).
*   **Password Hashing**: Passwords are never stored in plain text. They are hashed using secure algorithms before storage in `web_config.json`.
*   **Session Timeout**: Sessions automatically expire after a configurable time (Default: `3600s` / 1 hour).

### Best Practices
*   **Change Default Password**: Always change the default password immediately after installation.
*   **Reverse Proxy**: It is highly recommended to run DDC behind a reverse proxy (like Nginx or Traefik) with SSL/TLS encryption (HTTPS), especially if exposing it to the internet.

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
    *   Run DDC in an isolated network if possible.
    *   Use a strictly defined `DDC_DOCKER_SOCKET_PATH` if using a proxy socket.
    *   Do not expose the DDC port (9374) to the public internet without a secure reverse proxy and authentication.
