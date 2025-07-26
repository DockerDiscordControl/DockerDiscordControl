# Ultra-Minimal Alpine Build - Target <100MB
FROM alpine:3.22.1

WORKDIR /app

# Install Python and essential packages in one layer
RUN apk add --no-cache --virtual .build-deps \
        gcc musl-dev libffi-dev openssl-dev rust cargo \
    && apk add --no-cache \
        python3 python3-dev py3-pip \
        supervisor docker-cli ca-certificates \
    && python3 -m venv /venv \
    && /venv/bin/pip install --no-cache-dir --upgrade pip \
    && /venv/bin/pip install --no-cache-dir \
        Flask==3.1.1 \
        Werkzeug==3.1.3 \
        py-cord==2.6.1 \
        gunicorn==23.0.0 \
        gevent==24.11.1 \
        docker==7.1.0 \
        cryptography>=45.0.5 \
        APScheduler==3.10.4 \
        python-dotenv==1.0.1 \
        PyYAML==6.0.1 \
        requests==2.32.4 \
        aiohttp>=3.12.14 \
        Flask-HTTPAuth==4.8.0 \
        Jinja2>=3.1.4 \
        python-json-logger==2.0.7 \
        pytz==2024.2 \
        cachetools==5.3.2 \
        itsdangerous>=2.2.0 \
        click>=8.1.7 \
        blinker>=1.8.2 \
        MarkupSafe>=2.1.5 \
        flask-limiter>=3.5.0 \
        limits>=3.9.0 \
        greenlet>=3.0.3 \
        zope.event>=5.0 \
        zope.interface>=6.2 \
    && apk del .build-deps python3-dev \
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
COPY supervisord-optimized.conf /etc/supervisor/conf.d/supervisord.conf

# Final cleanup and permissions
RUN mkdir -p /app/config /app/logs \
    && chown -R ddcuser:ddcuser /app \
    && find /app -name "*.pyc" -delete \
    && find /app -name "__pycache__" -exec rm -rf {} + || true

# Set environment
ENV PATH="/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

USER ddcuser
EXPOSE 9374
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]