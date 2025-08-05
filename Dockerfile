# Ultra-Minimal Alpine Build - Target <100MB
FROM alpine:3.22.1

WORKDIR /app

# Install Python and essential packages in one layer
RUN apk add --no-cache --virtual .build-deps \
        gcc musl-dev libffi-dev openssl-dev rust cargo \
    && apk add --no-cache \
        python3 python3-dev py3-pip \
        supervisor docker-cli ca-certificates tzdata \
    && python3 -m venv /venv \
    && /venv/bin/pip install --no-cache-dir --upgrade pip

# Copy and install requirements  
COPY requirements.txt .
RUN /venv/bin/pip install --no-cache-dir -r requirements.txt

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

# Create user and groups
RUN addgroup -g 281 -S docker \
    && addgroup -g 1000 -S ddcuser \
    && adduser -u 1000 -S ddcuser -G ddcuser \
    && adduser ddcuser docker


# Copy only essential files
COPY --chown=ddcuser:ddcuser bot.py .
COPY --chown=ddcuser:ddcuser app/ app/
COPY --chown=ddcuser:ddcuser utils/ utils/
COPY --chown=ddcuser:ddcuser cogs/ cogs/
COPY --chown=ddcuser:ddcuser gunicorn_config.py .
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf


# Final cleanup and permissions
RUN mkdir -p /app/config /app/logs /app/scripts \
    && chown -R ddcuser:ddcuser /app \
    && find /app -name "*.pyc" -delete \
    && find /app -name "__pycache__" -exec rm -rf {} + || true \
    && chmod 644 /etc/supervisor/conf.d/supervisord.conf \
    && mkdir -p /app/config/info /app/config/tasks \
    && chmod -R 777 /app/config \
    && chmod -R 777 /app/logs

# Set environment
ENV PATH="/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ="Europe/Berlin"

# Create a symlink for the timezone
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

EXPOSE 9374
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]