# Multi-Stage Build - Alpine Version for DDC
FROM python:3.12-alpine AS builder
WORKDIR /build

# Install build dependencies with security updates and C++ compiler
RUN apk update && apk upgrade && \
    apk add --no-cache --virtual .build-deps gcc g++ musl-dev python3-dev libffi-dev make && \
    apk add --no-cache openssl=3.5.1-r0 openssl-dev=3.5.1-r0

# Copy requirements and install Python packages with latest setuptools
COPY requirements.txt .
RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --no-cache-dir --upgrade pip setuptools && \
    /opt/venv/bin/pip install --no-cache-dir -r requirements.txt && \
    /opt/venv/bin/pip install --no-cache-dir --force-reinstall --upgrade "aiohttp>=3.12.14" "setuptools>=78.1.1" && \
    /opt/venv/bin/pip install --no-cache-dir --force-reinstall --upgrade "setuptools>=78.1.1" && \
    /opt/venv/bin/pip wheel --wheel-dir=/wheels -r requirements.txt

# Copy source code and compile (suppress git warnings)
COPY . /build/
RUN python -m compileall -b /build 2>/dev/null || python -m compileall -b /build

# Clean up build dependencies
RUN apk del .build-deps

# Final stage
FROM python:3.12-alpine
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    VIRTUAL_ENV="/opt/venv"

# Install runtime dependencies
RUN apk update && apk upgrade && \
    apk add --no-cache supervisor docker openssl=3.5.1-r0 tzdata && \
    rm -rf /var/cache/apk/*

# Copy virtual environment and application
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /build /app

# Copy supervisor configuration
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Create necessary directories
RUN mkdir -p /app/config /app/logs

# Add health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:9374/ || exit 1

# Expose port
EXPOSE 9374

# Start supervisor
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"] 