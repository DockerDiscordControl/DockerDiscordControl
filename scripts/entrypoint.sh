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

# Check if a value is a positive integer
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

    # Check PUID range
    if [ "$puid" -lt "$MIN_UID" ] || [ "$puid" -gt "$MAX_UID" ]; then
        log_fatal "PUID must be between $MIN_UID and $MAX_UID, got: $puid"
    fi

    # Check PGID range
    if [ "$pgid" -lt "$MIN_UID" ] || [ "$pgid" -gt "$MAX_UID" ]; then
        log_fatal "PGID must be between $MIN_UID and $MAX_UID, got: $pgid"
    fi

    # Warn if running as root
    if [ "$puid" -eq 0 ]; then
        log_warn "PUID=0 will run the application as root - this is not recommended!"
        log_warn "Consider using a non-root user for better security."
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

    # Try GNU stat first, then busybox stat, then ls fallback
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

# Check if group exists
group_exists() {
    getent group "$1" >/dev/null 2>&1 || grep -q "^$1:" /etc/group 2>/dev/null
}

# Check if directory is writable
is_writable() {
    local dir="$1"
    [ -d "$dir" ] && [ -w "$dir" ]
}

# Check if directory is on a read-only filesystem
is_readonly_fs() {
    local dir="$1"
    local test_file="$dir/.ro_test_$$"

    # Try to create a file
    if touch "$test_file" 2>/dev/null; then
        rm -f "$test_file" 2>/dev/null
        return 1  # Not read-only
    fi
    return 0  # Read-only
}

# ============================================================================ #
# USER/GROUP MANAGEMENT
# ============================================================================ #

setup_user_and_group() {
    local target_uid="$1"
    local target_gid="$2"

    log_info "Setting up user $APP_USER with UID=$target_uid, GID=$target_gid"

    # Check for UID/GID conflicts
    local existing_user=$(get_user_name_by_uid "$target_uid")
    local existing_group=$(get_group_name_by_gid "$target_gid")

    # Handle GID - create or reuse existing group
    if [ -n "$existing_group" ]; then
        if [ "$existing_group" != "$APP_USER" ]; then
            log_info "GID $target_gid already used by group '$existing_group', will use it"
            # We'll add our user to this existing group
        fi
    else
        # Need to create group with this GID
        # First remove old ddc group if it exists with different GID
        if group_exists "$APP_USER"; then
            delgroup "$APP_USER" 2>/dev/null || true
        fi
        addgroup -g "$target_gid" -S "$APP_USER" 2>/dev/null || {
            log_warn "Could not create group $APP_USER with GID $target_gid"
            # Try without specific GID as fallback
            addgroup -S "$APP_USER" 2>/dev/null || true
        }
        existing_group="$APP_USER"
    fi

    # Handle UID - create or modify user
    if [ -n "$existing_user" ] && [ "$existing_user" != "$APP_USER" ]; then
        log_warn "UID $target_uid already used by user '$existing_user'"
        log_warn "This may cause permission issues. Consider using a different PUID."
    fi

    # Remove existing ddc user if present
    if user_exists "$APP_USER"; then
        deluser "$APP_USER" 2>/dev/null || true
    fi

    # Determine which group to use
    local primary_group="$APP_USER"
    if [ -n "$existing_group" ] && [ "$existing_group" != "$APP_USER" ]; then
        primary_group="$existing_group"
    fi

    # Create user with target UID
    adduser -u "$target_uid" -G "$primary_group" -D -H -s /sbin/nologin "$APP_USER" 2>/dev/null || {
        # Fallback: try without specific UID
        log_warn "Could not create user with UID $target_uid, trying without specific UID"
        adduser -G "$primary_group" -D -H -s /sbin/nologin "$APP_USER" 2>/dev/null || {
            log_error "Failed to create user $APP_USER"
            return 1
        }
    }

    # Verify user was created correctly
    if user_exists "$APP_USER"; then
        local actual_uid=$(id -u "$APP_USER" 2>/dev/null)
        local actual_gid=$(id -g "$APP_USER" 2>/dev/null)
        log_info "User $APP_USER created: UID=$actual_uid, GID=$actual_gid"

        if [ "$actual_uid" != "$target_uid" ]; then
            log_warn "Actual UID ($actual_uid) differs from requested ($target_uid)"
        fi
    else
        log_error "User $APP_USER does not exist after creation attempt"
        return 1
    fi

    return 0
}

# ============================================================================ #
# DOCKER SOCKET HANDLING
# ============================================================================ #

setup_docker_socket_access() {
    local docker_sock="/var/run/docker.sock"

    if [ ! -S "$docker_sock" ]; then
        log_warn "Docker socket not found at $docker_sock"
        log_warn "Docker operations will not work. Mount the socket with:"
        log_warn "  -v /var/run/docker.sock:/var/run/docker.sock"
        return 0  # Not fatal - user might be testing without Docker
    fi

    local sock_gid=$(get_file_gid "$docker_sock")

    if [ -z "$sock_gid" ]; then
        log_warn "Could not determine Docker socket GID"
        return 0
    fi

    log_info "Docker socket GID: $sock_gid"

    # Don't add to root group (GID 0) - that's a security risk
    if [ "$sock_gid" = "0" ]; then
        log_warn "Docker socket is owned by root group (GID 0)"
        log_warn "Consider running Docker with a dedicated docker group"
        return 0
    fi

    # Find or create a group with the socket's GID
    local sock_group=$(get_group_name_by_gid "$sock_gid")

    if [ -z "$sock_group" ]; then
        # Create a new group for the socket
        sock_group="dockersock"
        addgroup -g "$sock_gid" -S "$sock_group" 2>/dev/null || {
            # GID might be taken, try with auto GID
            log_warn "Could not create group with GID $sock_gid"
            return 0
        }
        log_info "Created group $sock_group with GID $sock_gid"
    fi

    # Add user to the socket group
    addgroup "$APP_USER" "$sock_group" 2>/dev/null || {
        log_warn "Could not add $APP_USER to group $sock_group"
        return 0
    }

    log_info "Added $APP_USER to docker group ($sock_group)"
    return 0
}

# ============================================================================ #
# PERMISSION HANDLING
# ============================================================================ #

setup_directories() {
    log_info "Setting up data directories..."

    # Create main data directories
    for dir in $DATA_DIRS; do
        if [ ! -d "$dir" ]; then
            mkdir -p "$dir" 2>/dev/null || {
                log_warn "Could not create directory $dir"
            }
        fi
    done

    # Create config subdirectories
    for subdir in $CONFIG_SUBDIRS; do
        local full_path="/app/config/$subdir"
        if [ ! -d "$full_path" ]; then
            mkdir -p "$full_path" 2>/dev/null || true
        fi
    done
}

fix_permissions() {
    local target_uid="$1"
    local target_gid="$2"

    log_info "Fixing ownership of data directories..."

    # Check if permissions are already correct (optimization for restarts)
    local config_uid=$(get_file_uid "/app/config")
    local config_gid=$(get_file_gid "/app/config")

    if [ "$config_uid" = "$target_uid" ] && [ "$config_gid" = "$target_gid" ]; then
        log_info "Permissions already correct, skipping chown"
        return 0
    fi

    # Try to fix permissions
    local chown_failed=0

    for dir in $DATA_DIRS; do
        if [ -d "$dir" ]; then
            chown -R "$target_uid:$target_gid" "$dir" 2>/dev/null || {
                log_warn "chown failed for $dir (might be NFS/SMB with restrictions)"
                chown_failed=1
            }
        fi
    done

    # Also try to chown /app itself for any temp files
    chown "$target_uid:$target_gid" /app 2>/dev/null || true

    if [ "$chown_failed" = "1" ]; then
        log_warn "Some chown operations failed - will verify with write test"
    fi

    return 0
}

verify_write_access() {
    local target_uid="$1"
    local target_gid="$2"
    local test_file="/app/config/.permission_test_$$"

    log_info "Verifying write access..."

    # Clean up any stale test files from previous runs
    rm -f /app/config/.permission_test_* 2>/dev/null || true

    # Check if su-exec is available
    if ! command_exists su-exec; then
        log_error "su-exec not found - cannot verify permissions safely"
        log_error "The container image may be corrupted. Please pull a fresh image."
        return 1
    fi

    # Try to write as the target user
    if su-exec "$target_uid:$target_gid" touch "$test_file" 2>/dev/null; then
        rm -f "$test_file" 2>/dev/null || true
        log_info "Write access verified successfully"
        return 0
    fi

    # Write test failed - provide detailed help
    echo ""
    echo "==============================================================="
    echo "   PERMISSION ERROR - CANNOT WRITE TO CONFIG                   "
    echo "==============================================================="
    echo ""
    echo "The container cannot write to /app/config as UID $target_uid."
    echo ""
    echo "Current volume permissions:"
    ls -ld /app/config 2>/dev/null || echo "  (could not read)"
    echo ""
    echo "This commonly happens on NAS systems (Unraid, Synology, QNAP)"
    echo "where volumes are owned by a specific user."
    echo ""
    echo "SOLUTIONS (try in order):"
    echo ""
    echo "  1. Match PUID/PGID to your volume owner:"
    echo "     Check owner: ls -ln /path/to/your/appdata/ddc"
    echo "     Then set environment variables:"
    echo "       PUID=<owner_uid>  (e.g., 99 for Unraid nobody)"
    echo "       PGID=<owner_gid>  (e.g., 100 for Unraid users)"
    echo ""
    echo "  2. Fix permissions on the host:"
    echo "     chown -R $target_uid:$target_gid /path/to/your/appdata/ddc"
    echo ""
    echo "  3. Last resort - permissive mode (less secure):"
    echo "     chmod -R 777 /path/to/your/appdata/ddc"
    echo ""
    echo "Common NAS defaults:"
    echo "  Unraid:   PUID=99   PGID=100"
    echo "  Synology: PUID=1026 PGID=100"
    echo "  TrueNAS:  PUID=568  PGID=568"
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

    log_info "Dropping privileges to $APP_USER (UID=$target_uid)..."

    if ! command_exists su-exec; then
        log_fatal "su-exec not found - cannot drop privileges safely.
Please ensure the container image includes su-exec.
As a workaround, you can run with --user $target_uid:$target_gid"
    fi

    # Re-execute this script as the target user
    exec su-exec "$target_uid:$target_gid" "$0" "$@"
}

# ============================================================================ #
# NON-ROOT STARTUP
# ============================================================================ #

start_as_user() {
    log_info "Running as: $(id)"

    # Verify docker socket access
    local docker_sock="/var/run/docker.sock"
    if [ -S "$docker_sock" ]; then
        if [ -r "$docker_sock" ] && [ -w "$docker_sock" ]; then
            log_info "Docker socket: read/write access OK"
        elif [ -r "$docker_sock" ]; then
            log_warn "Docker socket: read-only access (some operations may fail)"
        else
            log_warn "Docker socket: NO ACCESS"
            log_warn "Container operations will fail!"
            log_warn "Check that the socket is mounted and has correct permissions"
        fi
    fi

    # Final write test
    if ! is_writable "/app/config"; then
        echo ""
        echo "==============================================================="
        echo "   PERMISSION ERROR                                            "
        echo "==============================================================="
        echo "Cannot write to /app/config as $(id)"
        echo ""
        echo "Try setting PUID/PGID environment variables."
        echo "On Unraid: PUID=99 PGID=100"
        echo "==============================================================="
        exit 1
    fi

    # Warn about logs if not writable
    if ! is_writable "/app/logs"; then
        log_warn "Cannot write to /app/logs - logging to file will fail"
    fi

    # Start the application
    log_info "Starting DDC application..."
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

    # Trim whitespace (handles "PUID= 1000" edge case)
    PUID=$(echo "$PUID" | tr -d '[:space:]')
    PGID=$(echo "$PGID" | tr -d '[:space:]')

    # Use defaults if empty after trimming
    [ -z "$PUID" ] && PUID="$DEFAULT_UID"
    [ -z "$PGID" ] && PGID="$DEFAULT_GID"

    # Validate IDs
    validate_ids "$PUID" "$PGID"

    # Check if we're running as root
    if [ "$(id -u)" = "0" ]; then
        log_info "Running as root, setting up environment..."
        log_info "Target UID: $PUID, Target GID: $PGID"

        # Only modify user if PUID/PGID differ from defaults
        if [ "$PUID" != "$DEFAULT_UID" ] || [ "$PGID" != "$DEFAULT_GID" ]; then
            setup_user_and_group "$PUID" "$PGID" || {
                log_warn "User setup had issues, continuing anyway..."
            }
        fi

        # Setup docker socket access
        setup_docker_socket_access

        # Create and fix directories
        setup_directories
        fix_permissions "$PUID" "$PGID"

        # Verify we can actually write
        if ! verify_write_access "$PUID" "$PGID"; then
            exit 1
        fi

        # Drop privileges and re-run this script
        drop_privileges "$PUID" "$PGID" "$@"

    else
        # Already running as non-root (after privilege drop or started with --user)
        start_as_user
    fi
}

# Run main function
main "$@"
