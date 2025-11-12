# Multi-stage build for ultra-small production image
FROM alpine:3.22.1 AS builder

WORKDIR /build

# Install build dependencies only
RUN apk add --no-cache \
    python3 python3-dev py3-pip \
    gcc musl-dev libffi-dev openssl-dev \
    jpeg-dev zlib-dev freetype-dev

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
for script in ('pip', 'pip3', 'pip3.12'):
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
FROM alpine:3.22.1

WORKDIR /app

# Install ONLY runtime dependencies
RUN apk add --no-cache \
    python3 \
    supervisor \
    ca-certificates \
    tzdata \
    docker-cli \
    jpeg \
    zlib \
    freetype

# Copy cleaned venv from builder
COPY --from=builder /runtime/site-packages /opt/runtime/site-packages

# Strip CPython test suite and ensurepip to reduce the base image size further
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
):
    target = stdlib / relative
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)

dynload = stdlib / 'lib-dynload'
for module in ('_tkinter', '_tkinter_impl', 'tkinter'):  # defensive clean-up
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
    find /usr/lib/python3.12/lib-dynload -type f -name "*.so" -exec strip --strip-unneeded {} + && \
    apk del .strip-deps

# Create user
RUN addgroup -g 1000 -S ddc && \
    adduser -u 1000 -S ddc -G ddc && \
    (addgroup -g 281 -S docker 2>/dev/null || addgroup -S docker) && \
    adduser ddc docker

# Copy application code
COPY --chown=ddc:ddc bot.py .
COPY --chown=ddc:ddc app/ app/
COPY --chown=ddc:ddc utils/ utils/
COPY --chown=ddc:ddc cogs/ cogs/
COPY --chown=ddc:ddc services/ services/
COPY --chown=ddc:ddc encrypted_assets/ encrypted_assets/
# V2.0 Cache-Only: Only copy cached animations, PNG sources excluded via .dockerignore
COPY --chown=ddc:ddc cached_animations/ cached_animations/
COPY --chown=ddc:ddc cached_displays/ cached_displays/
COPY --chown=ddc:ddc gunicorn_config.py .
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY --chown=ddc:ddc scripts/entrypoint.sh /app/entrypoint.sh

# Setup permissions
RUN chmod +x /app/entrypoint.sh && \
    mkdir -p /app/config /app/logs /app/scripts && \
    mkdir -p /app/config/info /app/config/tasks && \
    mkdir -p /app/cached_displays && \
    chown -R ddc:ddc /app && \
    chmod -R 755 /app && \
    chmod -R 775 /app/config /app/logs /app/cached_displays && \
    find /app -type d -name '__pycache__' -prune -exec rm -rf {} +

# Environment
ENV PYTHONPATH="/opt/runtime/site-packages" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONOPTIMIZE=1 \
    TZ="Europe/Berlin"

RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

USER ddc
EXPOSE 9374
ENTRYPOINT ["/app/entrypoint.sh"]