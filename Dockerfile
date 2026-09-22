# Multi-stage build for ultra-small production image
FROM alpine:3.24@sha256:28bd5fe8b56d1bd048e5babf5b10710ebe0bae67db86916198a6eec434943f8b AS builder

WORKDIR /build

# Install build dependencies only
# Note: freetype-dev removed - pulls vulnerable libpng, we don't use fonts
RUN apk add --no-cache \
    python3 python3-dev py3-pip \
    gcc musl-dev libffi-dev openssl-dev \
    jpeg-dev zlib-dev

# Create venv and install Python packages
RUN python3 -m venv /venv
COPY requirements.prod.txt ./
RUN /venv/bin/pip install --no-cache-dir --upgrade pip && \
    /venv/bin/pip install --no-cache-dir -r requirements.prod.txt

# Drop build-only Python packaging helpers to reduce the virtualenv footprint
RUN python3 - <<'PY'
from __future__ import annotations

import shutil
import sys
from pathlib import Path

site_packages = Path('/venv/lib') / f"python{sys.version_info.major}.{sys.version_info.minor}" / 'site-packages'
for package in ('pip', 'setuptools', 'wheel'):
    package_dir = site_packages / package
    if package_dir.exists():
        shutil.rmtree(package_dir, ignore_errors=True)

    module_path = site_packages / f'{package}.py'
    if module_path.exists():
        module_path.unlink()

    for metadata in site_packages.glob(f"{package.replace('-', '_')}*-info"):
        shutil.rmtree(metadata, ignore_errors=True)

bin_dir = Path('/venv/bin')
for script in ('pip', 'pip3', 'pip3.12', 'pip3.13'):
    target = bin_dir / script
    if target.exists():
        target.unlink()
PY

# Strip binaries and clean up
RUN find /venv -type f -name "*.so" -exec strip --strip-unneeded {} + && \
    find /venv -name "*.pyc" -delete && \
    find /venv -name "__pycache__" -exec rm -rf {} + && \
    find /venv -name "test" -type d -exec rm -rf {} + && \
    find /venv -name "tests" -type d -exec rm -rf {} + && \
    find /venv -name "*.egg-info" -type d -exec rm -rf {} +

# Extract the cleaned site-packages tree so the runtime image can extend the
# system interpreter without copying the full virtualenv hierarchy.
RUN PY_MINOR=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")') && \
    mkdir -p /runtime/site-packages && \
    cp -a "/venv/lib/python${PY_MINOR}/site-packages/." /runtime/site-packages/ && \
    python3 - <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

runtime = Path('/runtime/site-packages')
source = f"/venv/lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages"

for pth_file in runtime.glob('*.pth'):
    try:
        content = pth_file.read_text()
    except OSError:
        continue
    updated = content.replace(source, str(runtime))
    if updated != content:
        pth_file.write_text(updated)
PY

# Production stage - minimal runtime
FROM alpine:3.24@sha256:28bd5fe8b56d1bd048e5babf5b10710ebe0bae67db86916198a6eec434943f8b

WORKDIR /app

# Install ONLY runtime dependencies
# Added back: tzdata (required for timezone selection support)
# Note: docker-cli removed - we use Docker Python SDK (docker-py)
# Note: freetype removed - pulls vulnerable libpng, we don't use fonts
# Note: su-exec added for permission handling on Unraid/NAS systems
RUN apk update && \
    apk add --no-cache \
    python3 \
    ca-certificates \
    jpeg \
    zlib \
    tzdata \
    su-exec \
    expat && \
    apk upgrade --no-cache && \
    rm -rf /var/cache/apk/*

# Copy cleaned venv from builder
COPY --from=builder /runtime/site-packages /opt/runtime/site-packages

# Strip CPython test suite and ensurepip to reduce the base image size further
# Aggressive stripping: Added pydoc_data, unittest, distutils
RUN python3 - <<'PY'
from __future__ import annotations

import shutil
import sysconfig
from pathlib import Path

stdlib = Path(sysconfig.get_path('stdlib'))
for relative in (
    'test',
    'ensurepip',
    'idlelib',
    'tkinter',
    'turtledemo',
    'lib2to3',
    'pydoc_data',
    'unittest',
    'distutils',
    # NOTE: 'xmlrpc' is intentionally KEPT - opengsq's protocols package eagerly
    # imports every protocol incl. 'nadeo', which imports xmlrpc.client at module load.
    'email/test',
    'ctypes/test',
    'sqlite3/test'
):
    target = stdlib / relative
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)

dynload = stdlib / 'lib-dynload'
for module in ('_tkinter', '_tkinter_impl', 'tkinter', 'readline'):  # defensive clean-up
    for candidate in dynload.glob(f'{module}*.so'):
        candidate.unlink(missing_ok=True)

for root in (stdlib, Path(sysconfig.get_path('platlib'))):
    for pycache in root.rglob('__pycache__'):
        shutil.rmtree(pycache, ignore_errors=True)
    for compiled in root.rglob('*.pyc'):
        compiled.unlink(missing_ok=True)
PY

# Ensure stripped stdlib binaries without keeping binutils around
RUN apk add --no-cache --virtual .strip-deps binutils && \
    strip --strip-unneeded /usr/bin/python3 && \
    strip --strip-unneeded /usr/lib/libpython3.* && \
    find /usr/lib/python3.*/lib-dynload -type f -name "*.so" -exec strip --strip-unneeded {} + && \
    apk del .strip-deps && \
    # Remove busybox wget applet AFTER all apk operations
    # (CVE-2025-60876 - HTTP header injection, not needed by DDC)
    rm -f /usr/bin/wget

# Create users. ddc runs the app; ddcproxy runs the Docker allowlist proxy and is
# the only one that gets the socket's group (the entrypoint adds it at start, by
# the socket's real gid). ddc joins ddcproxy's group so it can reach the proxy
# socket - and nothing else of the proxy's. Until v2.4.1 ddc itself was in the
# docker group, so it could talk to the socket directly (V3 §4.3).
RUN addgroup -g 1000 -S ddc && \
    adduser -u 1000 -S ddc -G ddc && \
    addgroup -g 2375 -S ddcproxy && \
    adduser -u 2375 -S -D -H -s /sbin/nologin -G ddcproxy ddcproxy && \
    adduser ddc ddcproxy

# Copy application code - owned by root. The entrypoint runs as root at every
# start; code ddc could rewrite would be code root runs next time (V3 §4.3,
# measured on v2.4.1: ddc could write /app/entrypoint.sh). Only the data
# directories below belong to ddc.
COPY run.py .
COPY bot.py .
COPY app/ app/
COPY utils/ utils/
COPY cogs/ cogs/
COPY locales/ locales/
COPY services/ services/
COPY encrypted_assets/ encrypted_assets/
# V2.0 Cache-Only: Only copy cached animations
COPY cached_animations/ cached_animations/
COPY cached_displays/ cached_displays/
COPY scripts/entrypoint.sh /app/entrypoint.sh
# Password reset utility (docs: docker exec -it -u ddc <container> python3 scripts/reset_password.py)
COPY scripts/reset_password.py /app/scripts/reset_password.py
# Break-glass for a lost second factor (docs: docker exec -it -u ddc <container> python3 scripts/disable_2fa.py)
COPY scripts/disable_2fa.py /app/scripts/disable_2fa.py
# The Docker allowlist proxy, a root-owned copy outside every path ddc can write.
COPY services/docker_proxy/allowlist_proxy.py /opt/ddc-proxy/allowlist_proxy.py

# Setup permissions: code root-owned and read-only for everyone else; data to ddc.
RUN mkdir -p /app/config /app/logs /app/scripts && \
    mkdir -p /app/config/info /app/config/tasks && \
    mkdir -p /app/cached_displays && \
    chown -R root:root /app /opt/ddc-proxy && \
    chmod -R u=rwX,go=rX /app /opt/ddc-proxy && \
    chmod 755 /app/entrypoint.sh && \
    chown -R ddc:ddc /app/config /app/logs /app/cached_displays /app/cached_animations && \
    chmod -R 750 /app/config /app/logs /app/cached_displays && \
    find /app -type d -name '__pycache__' -prune -exec rm -rf {} +

# Environment
# DDC_VERSION: single source for the version shown by the entrypoint banner and /health
# (bump together with README.md / docs/CHANGELOG.md on release).
# DOCKER_HOST: the allowlist proxy the entrypoint starts (v3.0). Set for the whole
# image, not only exported by the entrypoint, so docker exec sessions and
# diagnostics take the same way as DDC instead of the raw socket.
ENV DDC_VERSION="2.4.1" \
    DOCKER_HOST="unix:///run/ddc-proxy/docker.sock" \
    PYTHONPATH="/app:/opt/runtime/site-packages" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONOPTIMIZE=1 \
    TZ="Europe/Berlin"

# Set default timezone
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Note: We start as root to fix volume permissions on Unraid/NAS systems
# The entrypoint.sh will drop privileges to 'ddc' user after fixing permissions
EXPOSE 9374

# Health check against the unauthenticated /health endpoint of the web UI.
# No curl/wget in the image (busybox wget is removed above), so use python3.
# ProxyHandler({}) ignores HTTP(S)_PROXY (urlopen would send 127.0.0.1 to the proxy);
# the port follows DDC_WEB_PORT with the same fallback to 9374 as run.py.
# With DDC_TLS_MODE=self-signed DDC answers only HTTPS; the check then uses https
# without verifying the certificate - it talks to its own loopback, not a peer.
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python3 -c "import os, ssl, urllib.request as u; p = os.environ.get('DDC_WEB_PORT', '').strip(); p = p if p.isdigit() and 0 < int(p) < 65536 else '9374'; t = os.environ.get('DDC_TLS_MODE', '').strip().lower() == 'self-signed'; s = 'https' if t else 'http'; h = [u.ProxyHandler({})] + ([u.HTTPSHandler(context=ssl._create_unverified_context())] if t else []); u.build_opener(*h).open(s + '://127.0.0.1:' + p + '/health', timeout=8)" || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]