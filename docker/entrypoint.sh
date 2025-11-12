#!/usr/bin/env sh
set -eu

# This entrypoint ensures the app does not run as root by default.
# It dynamically grants the app user access to /var/run/docker.sock by
# adding the user to the socket's group (by GID), fixes data dir permissions
# on first run, then drops privileges using su-exec.

APP_USER="${DDC_USER_NAME:-ddcuser}"
APP_GROUP="${DDC_GROUP_NAME:-ddcuser}"
TARGET_UID="${DDC_UID:-1000}"
TARGET_GID="${DDC_GID:-1000}"
DATA_DIRS="${DDC_DATA_DIRS:-/app/config /app/logs}"
INIT_MARKER="/app/config/.ddc_permissions_initialized"
FORCE_ROOT="${DDC_FORCE_ROOT:-false}"

info()  { echo "[ddc] $*"; }
warn()  { echo "[ddc] WARNING: $*"; }

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

group_exists_by_name() {
  grep -q "^${1}:" /etc/group 2>/dev/null
}

group_name_by_gid() {
  awk -F: -v gid="$1" '($3 == gid) { print $1; exit }' /etc/group 2>/dev/null || true
}

ensure_group() {
  # Ensure base app group exists with desired GID
  if group_exists_by_name "$APP_GROUP"; then
    :
  else
    addgroup -g "$TARGET_GID" "$APP_GROUP" 2>/dev/null || addgroup "$APP_GROUP"
  fi
}

ensure_user() {
  # Ensure base app user exists with desired UID/GID
  if id -u "$APP_USER" >/dev/null 2>&1; then
    true
  else
    adduser -D -H -u "$TARGET_UID" -G "$APP_GROUP" "$APP_USER" || adduser -D -H "$APP_USER"
  fi
}

user_in_group() {
  local user="$1" group="$2"
  id -nG "$user" 2>/dev/null | tr ' ' '\n' | grep -qx "$group" && return 0 || return 1
}

add_user_to_group() {
  local user="$1" group="$2"
  if ! user_in_group "$user" "$group"; then
    addgroup "$user" "$group" 2>/dev/null || true
  fi
}

socket_group_setup() {
  # If docker socket is mounted, add the app user to the socket's group by GID
  if [ -S /var/run/docker.sock ]; then
    local gid gname
    if command_exists stat; then
      gid="$(stat -c %g /var/run/docker.sock 2>/dev/null || true)"
    fi
    if [ -z "${gid:-}" ]; then
      gid="$(ls -ln /var/run/docker.sock | awk '{print $4}')"
    fi
    if [ -n "${gid:-}" ]; then
      gname="$(group_name_by_gid "$gid")"
      if [ -z "$gname" ]; then
        gname="dockersock"
        # Create group with the socket's GID
        addgroup -g "$gid" "$gname" 2>/dev/null || true
      fi
      add_user_to_group "$APP_USER" "$gname"
      info "docker.sock group access configured (GID=$gid, group=$gname)"
      export DDC_DOCKERSOCK_GID="$gid"
    else
      warn "could not determine docker.sock GID"
    fi
  fi
}

configure_supervisor_auth() {
  # Configure credentials for supervisord unix_http_server and supervisorctl
  # Defaults: SUPERVISOR_USER=ddc; SUPERVISOR_PASS from env or DDC_ADMIN_PASSWORD or random
  local sup_user sup_pass conf
  sup_user="${SUPERVISOR_USER:-ddc}"
  sup_pass="${SUPERVISOR_PASS:-}"
  auto_gen=0
  if [ -z "$sup_pass" ]; then
    sup_pass="${DDC_ADMIN_PASSWORD:-}"
  fi
  if [ -z "$sup_pass" ]; then
    # Generate a random alphanumeric fallback
    if command_exists tr && [ -r /dev/urandom ]; then
      sup_pass="$(tr -dc 'A-Za-z0-9' </dev/urandom | head -c 16 || echo ddcTempPass1234)"
    else
      sup_pass="ddcTempPass1234"
    fi
    auto_gen=1
  fi
  conf="/etc/supervisor/conf.d/supervisord.conf"
  if [ -w "$conf" ]; then
    # Remove existing creds in sections and insert fresh ones right after headers
    for sec in unix_http_server supervisorctl; do
      sed -i "/^\[$sec\]/,/^\[/ { /^username=/d; /^password=/d; }" "$conf" || true
      sed -i "/^\[$sec\]/a username=${sup_user}\npassword=${sup_pass}" "$conf" || true
    done
    info "configured supervisord auth for user '${sup_user}'"
    if [ "$auto_gen" = "1" ]; then
      # Write a small marker to inform Web UI that the password was auto-generated at startup
      mkdir -p /app/config 2>/dev/null || true
      echo "1" > /app/config/.supervisor_pass_autogen 2>/dev/null || true
      chown "$TARGET_UID:$TARGET_GID" /app/config/.supervisor_pass_autogen 2>/dev/null || true
    fi
  else
    warn "supervisord.conf not writable; skipping supervisor auth configuration"
  fi
}

bootstrap_permissions() {
  # Chown data dirs on first run only
  if [ ! -f "$INIT_MARKER" ]; then
    for d in $DATA_DIRS; do
      if [ -d "$d" ]; then
        chown -R "$TARGET_UID:$TARGET_GID" "$d" 2>/dev/null || warn "chown failed for $d (non-fatal)"
      fi
    done
    # Create marker as app user to validate write access
    if command_exists su-exec; then
      su-exec "$TARGET_UID:$TARGET_GID" sh -c "umask 002 && touch '$INIT_MARKER' || true"
    else
      warn "su-exec not found; cannot create init marker as app user"
      touch "$INIT_MARKER" || true
    fi
  fi
}

drop_privileges_and_exec() {
  if command_exists su-exec; then
    # If we're already non-root effective UID, exec directly
    if [ "$(id -u)" != "0" ]; then
      info "already non-root (uid=$(id -u)), starting process directly"
      exec "$@"
    fi
    if command_exists setpriv && [ -n "${DDC_DOCKERSOCK_GID:-}" ]; then
      exec setpriv --reuid "$TARGET_UID" --regid "$TARGET_GID" --groups "$DDC_DOCKERSOCK_GID" "$@"
    fi
    exec su-exec "$TARGET_UID:$TARGET_GID" "$@"
  fi
  # Fallback: run as root if su-exec is not available
  warn "su-exec not available; running as root (compat)"
  exec "$@"
}

main() {
  if [ "$FORCE_ROOT" = "true" ]; then
    warn "running as root due to DDC_FORCE_ROOT=true"
    exec "$@"
  fi

  ensure_group
  ensure_user
  socket_group_setup
  bootstrap_permissions || true
  configure_supervisor_auth || true

  info "dropping privileges to $APP_USER ($TARGET_UID:$TARGET_GID)"
  # Ensure home exists and ownership is correct to avoid EACCES on process spawn
  if [ ! -d "/home/$APP_USER" ]; then
    mkdir -p "/home/$APP_USER" 2>/dev/null || true
  fi
  chown -R "$TARGET_UID:$TARGET_GID" "/home/$APP_USER" 2>/dev/null || true
  export HOME="/home/$APP_USER"
  export PYTHONPATH="/opt/runtime/site-packages${PYTHONPATH:+:$PYTHONPATH}"
  umask 002
  drop_privileges_and_exec "$@"
}

main "$@"


