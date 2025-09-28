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

# Strip binaries and clean up
RUN find /venv -type f -name "*.so" -exec strip --strip-unneeded {} + && \
    find /venv -name "*.pyc" -delete && \
    find /venv -name "__pycache__" -exec rm -rf {} + && \
    find /venv -name "test" -type d -exec rm -rf {} + && \
    find /venv -name "tests" -type d -exec rm -rf {} + && \
    find /venv -name "*.dist-info" -type d -exec rm -rf {} + && \
    find /venv -name "*.egg-info" -type d -exec rm -rf {} +

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
COPY --from=builder /venv /venv

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
COPY --chown=ddc:ddc assets/ assets/
COPY --chown=ddc:ddc cached_animations/ cached_animations/
COPY --chown=ddc:ddc gunicorn_config.py .
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY --chown=ddc:ddc scripts/entrypoint.sh /app/entrypoint.sh

# Setup permissions
RUN chmod +x /app/entrypoint.sh && \
    mkdir -p /app/config /app/logs /app/scripts && \
    mkdir -p /app/config/info /app/config/tasks && \
    chown -R ddc:ddc /app && \
    chmod -R 755 /app && \
    chmod -R 775 /app/config /app/logs

# Environment
ENV PATH="/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ="Europe/Berlin"

RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

USER ddc
EXPOSE 9374
ENTRYPOINT ["/app/entrypoint.sh"]