#!/bin/sh
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                      #
# Licensed under the MIT License                                               #
# ============================================================================ #
#
# Hardened entrypoint with comprehensive edge case handling for:
# - Unraid, Synology, QNAP, TrueNAS, and other NAS systems
# - NFS/SMB/CIFS mounted volumes
# - Custom PUID/PGID configurations
# - Docker socket permission handling
#
# ============================================================================ #

# Don't use set -e globally - we handle errors explicitly
# set -e would cause silent exits on non-critical failures

# ============================================================================ #
# CONFIGURATION
# ============================================================================ #

VERSION="2.1.2"
APP_USER="ddc"
DEFAULT_UID=1000
DEFAULT_GID=1000
MIN_UID=1
MAX_UID=65534
DATA_DIRS="/app/config /app/logs /app/cached_displays"
CONFIG_SUBDIRS="info tasks channels"

# ============================================================================ #
# LOGGING FUNCTIONS
# ============================================================================ #

log_info() {
    echo "[DDC] $*"
}

log_warn() {
    echo "[DDC] WARNING: $*"
}

log_error() {
    echo "[DDC] ERROR: $*" >&2
}

log_fatal() {
    echo "" >&2
    echo "===============================================================" >&2
    echo "   FATAL ERROR                                                 " >&2
    echo "===============================================================" >&2
    echo "$*" >&2
    echo "===============================================================" >&2
    exit 1
}

# ============================================================================ #
# BANNER
# ============================================================================ #

print_banner() {
    echo "==============================================================="
    echo "   DockerDiscordControl (DDC) - Container Startup              "
    echo "==============================================================="
    echo "   Version: $VERSION (Optimized)"
    echo "   Architecture: Single Process (Waitress + Bot)"
    echo "==============================================================="
}

# ============================================================================ #
# VALIDATION FUNCTIONS
# ============================================================================ #

# Check if a value is a positive integer (including 0)
is_valid_id() {
    case "$1" in
        ''|*[!0-9]*) return 1 ;;  # Empty or contains non-digits
        *) return 0 ;;
    esac
}

# Validate PUID/PGID values
validate_ids() {
    local puid="$1"
    local pgid="$2"

    # Check PUID is numeric
    if ! is_valid_id "$puid"; then
        log_fatal "PUID must be a positive integer, got: '$puid'"
    fi

    # Check PGID is numeric
    if ! is_valid_id "$pgid"; then
        log_fatal "PGID must be a positive integer, got: '$pgid'"
    fi

    # SECURITY: Check length to prevent integer overflow in shell arithmetic
    # Max valid UID is 65534 (5 digits), reject anything longer
    if [ "${#puid}" -gt 5 ] || [ "${#pgid}" -gt 5 ]; then
        log_fatal "PUID/PGID too large (max 65534). Got: PUID=$puid, PGID=$pgid"
    fi

    # Special handling for root (UID 0) - allow with warning
    if [ "$puid" -eq 0 ]; then
        log_warn "=================================================="
        log_warn "PUID=0 detected - running as ROOT user!"
        log_warn "This is a SECURITY RISK and not recommended."
        log_warn "Consider using a non-root user (PUID=1000)."
        log_warn "=================================================="
        # Don't exit - allow it but warn strongly
    elif [ "$puid" -lt "$MIN_UID" ] || [ "$puid" -gt "$MAX_UID" ]; then
        log_fatal "PUID must be between $MIN_UID and $MAX_UID, got: $puid"
    fi

    # Check PGID range (0 is allowed for root group, but warn)
    # Note: is_valid_id already ensures pgid contains only digits, so it can't be negative
    if [ "$pgid" -eq 0 ]; then
        log_warn "PGID=0 detected - using ROOT group!"
        log_warn "This may expose sensitive files. Consider using a non-root group."
    elif [ "$pgid" -gt "$MAX_UID" ]; then
        log_fatal "PGID must be between 0 and $MAX_UID, got: $pgid"
    fi

    return 0
}

# ============================================================================ #
# UTILITY FUNCTIONS
# ============================================================================ #

# Check if a command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Get GID of a file/socket (handles both busybox and GNU stat)
get_file_gid() {
    local file="$1"
    local gid=""

    if [ ! -e "$file" ]; then
        return 1
    fi

    # Try GNU/BusyBox stat first, then BSD stat, then ls fallback
    gid=$(stat -c %g "$file" 2>/dev/null) || \
    gid=$(stat -f %g "$file" 2>/dev/null) || \
    gid=$(ls -ln "$file" 2>/dev/null | awk '{print $4}')

    if [ -n "$gid" ] && is_valid_id "$gid"; then
        echo "$gid"
        return 0
    fi
    return 1
}

# Get UID of a file
get_file_uid() {
    local file="$1"
    local uid=""

    if [ ! -e "$file" ]; then
        return 1
    fi

    uid=$(stat -c %u "$file" 2>/dev/null) || \
    uid=$(stat -f %u "$file" 2>/dev/null) || \
    uid=$(ls -ln "$file" 2>/dev/null | awk '{print $3}')

    if [ -n "$uid" ] && is_valid_id "$uid"; then
        echo "$uid"
        return 0
    fi
    return 1
}

# Get group name by GID
get_group_name_by_gid() {
    local gid="$1"
    awk -F: -v gid="$gid" '($3 == gid) { print $1; exit }' /etc/group 2>/dev/null
}

# Get user name by UID
get_user_name_by_uid() {
    local uid="$1"
    awk -F: -v uid="$uid" '($3 == uid) { print $1; exit }' /etc/passwd 2>/dev/null
}

# Check if user exists
user_exists() {
    id "$1" >/dev/null 2>&1
}

# Check if group exists by name
group_exists_by_name() {
    getent group "$1" >/dev/null 2>&1 || grep -q "^$1:" /etc/group 2>/dev/null
}

# Check if group exists by GID
group_exists_by_gid() {
    local gid="$1"
    [ -n "$(get_group_name_by_gid "$gid")" ]
}

# Check if directory is writable
is_writable() {
    local dir="$1"
    [ -d "$dir" ] && [ -w "$dir" ]
}

# ============================================================================ #
# USER/GROUP MANAGEMENT
# ============================================================================ #

setup_user_and_group() {
    local target_uid="$1"
    local target_gid="$2"

    log_info "Setting up user $APP_USER with UID=$target_uid, GID=$target_gid"

    # Check for existing users/groups with target UID/GID
    local existing_user_with_uid=$(get_user_name_by_uid "$target_uid")
    local existing_group_with_gid=$(get_group_name_by_gid "$target_gid")

    # =========================================
    # STEP 1: Handle the primary group
    # =========================================
    local primary_group=""

    if [ -n "$existing_group_with_gid" ]; then
        # A group with this GID already exists - reuse it
        primary_group="$existing_group_with_gid"
        if [ "$existing_group_with_gid" != "$APP_USER" ]; then
            log_info "GID $target_gid belongs to group '$existing_group_with_gid', will use it"
        fi
    else
        # No group with this GID exists - create one
        # First, remove old ddc group if it exists (might have different GID)
        if group_exists_by_name "$APP_USER"; then
            log_info "Removing existing $APP_USER group (different GID)"
            delgroup "$APP_USER" 2>/dev/null || true
        fi

        # Create the group with target GID
        if addgroup -g "$target_gid" -S "$APP_USER" 2>/dev/null; then
            primary_group="$APP_USER"
            log_info "Created group $APP_USER with GID $target_gid"
        else
            # GID creation failed - try without specific GID
            log_warn "Could not create group with GID $target_gid"
            if addgroup -S "$APP_USER" 2>/dev/null; then
                primary_group="$APP_USER"
                log_warn "Created group $APP_USER with auto-assigned GID"
            else
                log_error "Failed to create group $APP_USER"
                # Try to continue with existing group if any
                if group_exists_by_name "$APP_USER"; then
                    primary_group="$APP_USER"
                else
                    return 1
                fi
            fi
        fi
    fi

    # Verify we have a primary group
    if [ -z "$primary_group" ]; then
        log_error "No primary group available for user creation"
        return 1
    fi

    # =========================================
    # STEP 2: Handle the user
    # =========================================

    # Warn if UID is already used by another user
    if [ -n "$existing_user_with_uid" ] && [ "$existing_user_with_uid" != "$APP_USER" ]; then
        log_warn "UID $target_uid is already used by user '$existing_user_with_uid'"
        log_warn "This may cause permission issues. Consider using a different PUID."
    fi

    # Remove existing ddc user if present (to recreate with correct UID/GID)
    if user_exists "$APP_USER"; then
        log_info "Removing existing $APP_USER user"
        deluser "$APP_USER" 2>/dev/null || true
    fi

    # Create user with target UID
    local user_created=0
    if adduser -u "$target_uid" -G "$primary_group" -D -H -s /sbin/nologin "$APP_USER" 2>/dev/null; then
        user_created=1
    else
        # UID might be taken, try without specific UID
        log_warn "Could not create user with UID $target_uid, trying without specific UID"
        if adduser -G "$primary_group" -D -H -s /sbin/nologin "$APP_USER" 2>/dev/null; then
            user_created=1
        fi
    fi

    if [ "$user_created" -ne 1 ]; then
        log_error "Failed to create user $APP_USER"
        return 1
    fi

    # =========================================
    # STEP 3: Verify user was created correctly
    # =========================================
    if ! user_exists "$APP_USER"; then
        log_error "User $APP_USER does not exist after creation"
        return 1
    fi

    local actual_uid=$(id -u "$APP_USER" 2>/dev/null)
    local actual_gid=$(id -g "$APP_USER" 2>/dev/null)

    log_info "User $APP_USER ready: UID=$actual_uid, GID=$actual_gid"

    # Warn if actual differs from requested (but don't fail)
    if [ "$actual_uid" != "$target_uid" ]; then
        log_warn "Actual UID ($actual_uid) differs from requested ($target_uid)"
        log_warn "This is usually fine if permissions match."
    fi
    if [ "$actual_gid" != "$target_gid" ]; then
        log_warn "Actual GID ($actual_gid) differs from requested ($target_gid)"
        log_warn "This is usually fine if permissions match."
    fi

    return 0
}

# ============================================================================ #
# DOCKER SOCKET HANDLING
# ============================================================================ #

setup_docker_socket_access() {
    local docker_sock="/var/run/docker.sock"

    # Check if socket exists
    if [ ! -S "$docker_sock" ]; then
        log_warn "Docker socket not found at $docker_sock"
        log_warn "Docker operations will not work!"
        log_warn "Mount the socket with: -v /var/run/docker.sock:/var/run/docker.sock"
        return 0  # Not fatal - continue startup to show the error in web UI
    fi

    # Get socket's group ID
    local sock_gid=$(get_file_gid "$docker_sock")

    if [ -z "$sock_gid" ]; then
        log_warn "Could not determine Docker socket GID"
        log_warn "Docker operations may fail"
        return 0
    fi

    log_info "Docker socket GID: $sock_gid"

    # Handle root group (GID 0) specially
    if [ "$sock_gid" = "0" ]; then
        log_warn "Docker socket owned by root group (GID 0)"
        log_warn "User will need root group membership or socket mode 666"
        # Check if socket is world-readable
        if [ -r "$docker_sock" ] 2>/dev/null; then
            log_info "Docker socket appears to be world-accessible"
        fi
        return 0
    fi

    # Find existing group with socket's GID or create one
    local sock_group=$(get_group_name_by_gid "$sock_gid")

    if [ -z "$sock_group" ]; then
        # No group exists with this GID - create one
        # Try several name variants to avoid collision
        local try_names="dockersock docker$sock_gid ddc_docker$sock_gid"
        local created=0

        for try_name in $try_names; do
            if ! group_exists_by_name "$try_name"; then
                if addgroup -g "$sock_gid" -S "$try_name" 2>/dev/null; then
                    sock_group="$try_name"
                    log_info "Created group $sock_group with GID $sock_gid"
                    created=1
                    break
                fi
            fi
        done

        if [ "$created" -ne 1 ]; then
            log_warn "Could not create group for Docker socket GID $sock_gid"
            log_warn "Docker operations may fail"
            return 0
        fi
    fi

    # Add our user to the socket group
    if ! addgroup "$APP_USER" "$sock_group" 2>/dev/null; then
        log_warn "Could not add $APP_USER to group $sock_group"
        log_warn "Docker operations may fail"
        return 0
    fi

    log_info "Added $APP_USER to docker group ($sock_group, GID $sock_gid)"
    return 0
}

# ============================================================================ #
# PERMISSION HANDLING
# ============================================================================ #

setup_directories() {
    log_info "Setting up data directories..."

    local failed=0

    # Create main data directories
    for dir in $DATA_DIRS; do
        if [ ! -d "$dir" ]; then
            if mkdir -p "$dir" 2>/dev/null; then
                log_info "Created directory $dir"
            else
                log_warn "Could not create directory $dir"
                failed=1
            fi
        fi
    done

    # Create config subdirectories
    for subdir in $CONFIG_SUBDIRS; do
        local full_path="/app/config/$subdir"
        if [ ! -d "$full_path" ]; then
            mkdir -p "$full_path" 2>/dev/null || true
        fi
    done

    # Return status (0 = all ok, 1 = some failures)
    return $failed
}

fix_permissions() {
    local target_uid="$1"
    local target_gid="$2"

    log_info "Checking/fixing ownership of data directories..."

    # Check if ALL directories have correct permissions (optimization for restarts)
    local all_correct=1
    local dir_uid dir_gid

    for dir in $DATA_DIRS; do
        if [ -d "$dir" ]; then
            dir_uid=$(get_file_uid "$dir")
            dir_gid=$(get_file_gid "$dir")
            if [ "$dir_uid" != "$target_uid" ] || [ "$dir_gid" != "$target_gid" ]; then
                log_info "$dir: UID=$dir_uid, GID=$dir_gid (needs fix)"
                all_correct=0
            fi
        fi
    done

    if [ "$all_correct" = "1" ]; then
        log_info "All directories already have correct ownership (UID=$target_uid, GID=$target_gid)"
        return 0
    fi

    # Try to fix permissions
    log_info "Fixing ownership to UID=$target_uid, GID=$target_gid..."
    local chown_failed=0

    for dir in $DATA_DIRS; do
        if [ -d "$dir" ]; then
            if chown -R "$target_uid:$target_gid" "$dir" 2>/dev/null; then
                log_info "Fixed ownership of $dir"
            else
                log_warn "chown failed for $dir (NFS/SMB restrictions?)"
                chown_failed=1
            fi
        fi
    done

    # Also try to chown /app itself (for any temp files)
    chown "$target_uid:$target_gid" /app 2>/dev/null || true

    if [ "$chown_failed" = "1" ]; then
        log_warn "Some chown operations failed"
        log_warn "Will verify actual write access next..."
    fi

    return 0
}

verify_write_access() {
    local target_uid="$1"
    local target_gid="$2"
    local test_file="/app/config/.ddc_permission_test"

    log_info "Verifying write access as UID $target_uid..."

    # Clean up stale test files from previous runs
    rm -f /app/config/.ddc_permission_test* 2>/dev/null || true
    rm -f /app/config/.permission_test_* 2>/dev/null || true

    # Check if su-exec is available
    if ! command_exists su-exec; then
        log_error "su-exec not found!"
        log_error "The container image may be corrupted."
        log_error "Please pull a fresh image: docker pull dockerdiscordcontrol/dockerdiscordcontrol"
        return 1
    fi

    # First verify the user exists for su-exec
    if ! user_exists "$APP_USER"; then
        log_error "User $APP_USER does not exist!"
        log_error "User creation must have failed. Check earlier log messages."
        return 1
    fi

    # Try to write as the target user using su-exec
    # Note: We use the APP_USER name, not UID, for better su-exec compatibility
    local write_result
    write_result=$(su-exec "$APP_USER" sh -c "touch '$test_file' 2>&1 && echo SUCCESS || echo FAILED")

    if echo "$write_result" | grep -q "SUCCESS"; then
        rm -f "$test_file" 2>/dev/null || true
        log_info "Write access: OK"
        return 0
    fi

    # Write test failed - provide detailed diagnostics
    echo ""
    echo "==============================================================="
    echo "   PERMISSION ERROR - CANNOT WRITE TO CONFIG                   "
    echo "==============================================================="
    echo ""
    echo "User $APP_USER (UID $target_uid) cannot write to /app/config"
    echo ""
    echo "Diagnostic information:"
    echo "  User info: $(id "$APP_USER" 2>/dev/null || echo "user lookup failed")"
    echo "  Volume:    $(ls -ld /app/config 2>/dev/null || echo "cannot read")"
    echo ""
    echo "This commonly occurs on NAS systems where volumes are owned"
    echo "by a specific user (e.g., 'nobody' on Unraid)."
    echo ""
    echo "SOLUTIONS (try in order):"
    echo ""
    echo "  1. Set PUID/PGID to match your volume owner:"
    echo "     - Check owner: ls -ln /path/to/your/appdata/ddc"
    echo "     - Set environment variables to match:"
    echo "         PUID=<owner_uid>"
    echo "         PGID=<owner_gid>"
    echo ""
    echo "  2. Fix permissions on the host:"
    echo "     chown -R $target_uid:$target_gid /path/to/your/appdata/ddc"
    echo ""
    echo "  3. Last resort (less secure):"
    echo "     chmod -R 777 /path/to/your/appdata/ddc"
    echo ""
    echo "Common NAS defaults:"
    echo "  Unraid:   PUID=99   PGID=100  (nobody:users)"
    echo "  Synology: PUID=1026 PGID=100"
    echo "  TrueNAS:  PUID=568  PGID=568  (apps:apps)"
    echo "  QNAP:     PUID=1000 PGID=1000"
    echo ""
    echo "==============================================================="

    return 1
}

# ============================================================================ #
# PRIVILEGE DROP
# ============================================================================ #

drop_privileges() {
    local target_uid="$1"
    local target_gid="$2"
    shift 2  # Remove uid and gid from args

    log_info "Dropping privileges to $APP_USER (UID=$target_uid)..."

    if ! command_exists su-exec; then
        log_fatal "su-exec not found - cannot drop privileges safely.

The container image appears to be corrupted or modified.
Please pull a fresh image:
  docker pull dockerdiscordcontrol/dockerdiscordcontrol

Workaround: Run container with --user $target_uid:$target_gid
(Note: This skips permission setup and may cause issues)"
    fi

    # Verify user exists before trying to switch
    if ! user_exists "$APP_USER"; then
        log_fatal "Cannot drop privileges - user $APP_USER does not exist!

User creation must have failed. Please check the logs above."
    fi

    # Re-execute this script as the target user
    # Use user name instead of UID for better compatibility
    exec su-exec "$APP_USER" "$0" "$@"
}

# ============================================================================ #
# NON-ROOT STARTUP
# ============================================================================ #

start_as_user() {
    local current_uid=$(id -u)
    local current_gid=$(id -g)

    log_info "Running as: $(id)"

    # Check if PUID/PGID were set but we're running as different user
    # (happens when someone uses both --user and PUID/PGID)
    if [ -n "$PUID" ] && [ "$PUID" != "$current_uid" ]; then
        log_warn "PUID=$PUID was set but running as UID $current_uid"
        log_warn "PUID/PGID are ignored when using --user flag"
    fi

    # Verify docker socket access
    local docker_sock="/var/run/docker.sock"
    if [ -S "$docker_sock" ]; then
        if [ -r "$docker_sock" ] && [ -w "$docker_sock" ]; then
            log_info "Docker socket: read/write OK"
        elif [ -r "$docker_sock" ]; then
            log_warn "Docker socket: read-only (some operations may fail)"
        else
            log_error "Docker socket: NO ACCESS"
            log_error "Container control will not work!"
            log_error "Check socket permissions or add user to docker group"
        fi
    else
        log_error "Docker socket not mounted!"
        log_error "Container control will not work!"
    fi

    # Final write test for config directory
    if ! is_writable "/app/config"; then
        echo ""
        echo "==============================================================="
        echo "   PERMISSION ERROR                                            "
        echo "==============================================================="
        echo "Cannot write to /app/config as $(id)"
        echo ""
        echo "If you used --user flag, ensure the volume has correct permissions."
        echo "Otherwise, set PUID/PGID environment variables."
        echo ""
        echo "Example for Unraid: PUID=99 PGID=100"
        echo "==============================================================="
        exit 1
    fi

    # Check logs directory (warn but don't fail)
    if ! is_writable "/app/logs"; then
        log_warn "Cannot write to /app/logs"
        log_warn "File logging will be disabled"
    fi

    # Check cached_displays directory
    if ! is_writable "/app/cached_displays"; then
        log_warn "Cannot write to /app/cached_displays"
        log_warn "Display caching may not work"
    fi

    # All checks passed - start the application
    log_info "All checks passed - starting DDC..."
    exec python3 run.py
}

# ============================================================================ #
# MAIN
# ============================================================================ #

main() {
    print_banner

    # Get PUID/PGID from environment with defaults
    PUID="${PUID:-$DEFAULT_UID}"
    PGID="${PGID:-$DEFAULT_GID}"

    # Sanitize: trim whitespace (handles "PUID= 1000" edge case)
    PUID=$(printf '%s' "$PUID" | tr -d '[:space:]')
    PGID=$(printf '%s' "$PGID" | tr -d '[:space:]')

    # SECURITY: Use defaults if empty after whitespace removal
    # This prevents PUID=" " (whitespace only) from becoming root (0)
    [ -z "$PUID" ] && PUID="$DEFAULT_UID"
    [ -z "$PGID" ] && PGID="$DEFAULT_GID"

    # Sanitize: remove leading zeros to avoid octal interpretation issues
    # "0099" -> "99", "0000" -> "0", "0" -> "0"
    PUID=$(printf '%s' "$PUID" | sed 's/^0*//' | grep . || echo "0")
    PGID=$(printf '%s' "$PGID" | sed 's/^0*//' | grep . || echo "0")

    # Validate IDs before proceeding
    validate_ids "$PUID" "$PGID"

    # Check if we're running as root
    if [ "$(id -u)" = "0" ]; then
        log_info "Running as root, setting up environment..."
        log_info "Target: UID=$PUID, GID=$PGID"

        # Setup user/group if PUID/PGID differ from image defaults
        # Also setup if default user doesn't exist (handles corrupt/modified images)
        if [ "$PUID" != "$DEFAULT_UID" ] || [ "$PGID" != "$DEFAULT_GID" ] || ! user_exists "$APP_USER"; then
            if ! setup_user_and_group "$PUID" "$PGID"; then
                log_warn "User setup had issues, attempting to continue..."
            fi
        else
            log_info "Using default user (UID=$DEFAULT_UID, GID=$DEFAULT_GID)"
        fi

        # Setup docker socket access (always, even with default UID)
        setup_docker_socket_access

        # Create directories (if they don't exist)
        setup_directories

        # Fix permissions
        fix_permissions "$PUID" "$PGID"

        # Verify write access before dropping privileges
        if ! verify_write_access "$PUID" "$PGID"; then
            log_fatal "Cannot continue without write access to config directory"
        fi

        # Drop privileges and re-execute this script
        drop_privileges "$PUID" "$PGID" "$@"

    else
        # Already running as non-root
        # This happens after privilege drop OR when started with --user
        start_as_user
    fi
}

# ============================================================================ #
# ENTRY POINT
# ============================================================================ #

main "$@"
