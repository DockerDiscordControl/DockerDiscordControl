# Ultra-Minimal Alpine Build - Target <100MB
FROM alpine:3.22.1

WORKDIR /app

# Install Python, Docker CLI and essential packages in one layer
RUN apk add --no-cache --virtual .build-deps \
        gcc musl-dev libffi-dev openssl-dev binutils \
    && apk add --no-cache \
        python3 python3-dev py3-pip \
        supervisor ca-certificates tzdata \
        docker-cli \
    && python3 -m venv /venv \
    && /venv/bin/pip install --no-cache-dir --upgrade pip

# Copy and install production requirements only
COPY requirements.prod.txt ./
RUN /venv/bin/pip install --no-cache-dir -r requirements.prod.txt \
    && find /venv -type f -name "*.so" -exec strip --strip-unneeded {} + || true

# Clean up build dependencies and cache
RUN apk del .build-deps python3-dev \
    && rm -rf /root/.cache/pip \
    && rm -rf /tmp/* \
    && rm -rf /var/cache/apk/* \
    && rm -rf /usr/share/man \
    && rm -rf /usr/share/doc \
    && rm -rf /usr/lib/python*/ensurepip \
    && rm -rf /usr/lib/python*/idlelib \
    && rm -rf /usr/lib/python*/tkinter \
    && find /venv -name "*.pyc" -delete \
    && find /venv -name "__pycache__" -exec rm -rf {} + || true \
    && find /venv -name "test" -type d -exec rm -rf {} + || true \
    && find /venv -name "tests" -type d -exec rm -rf {} + || true \
    && find /venv -name "*.pyo" -delete || true

# Create non-root user 'ddc' with proper groups for container control
# Note: We create docker group with GID that matches common host systems
# The user needs docker group membership to control other containers via socket
RUN addgroup -g 1000 -S ddc \
    && adduser -u 1000 -S ddc -G ddc \
    && (addgroup -g 281 -S docker 2>/dev/null || addgroup -S docker) \
    && adduser ddc docker \
    && echo "User 'ddc' created with UID 1000 and added to docker group for container control"


# Copy only essential files with proper ownership
COPY --chown=ddc:ddc bot.py .
COPY --chown=ddc:ddc app/ app/
COPY --chown=ddc:ddc utils/ utils/
COPY --chown=ddc:ddc cogs/ cogs/
COPY --chown=ddc:ddc services/ services/
COPY --chown=ddc:ddc gunicorn_config.py .
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY --chown=ddc:ddc scripts/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh


# Setup directories and permissions for non-root operation
RUN mkdir -p /app/config /app/logs /app/scripts \
    && mkdir -p /app/config/info /app/config/tasks \
    && chown -R ddc:ddc /app \
    && chmod -R 755 /app \
    && chmod -R 775 /app/config /app/logs \
    && find /app -name "*.pyc" -delete \
    && find /app -name "__pycache__" -exec rm -rf {} + || true

# Set environment
ENV PATH="/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ="Europe/Berlin"

# Create a symlink for the timezone
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Switch to non-root user for security
USER ddc

EXPOSE 9374

# Use entrypoint script for proper initialization
ENTRYPOINT ["/app/entrypoint.sh"]