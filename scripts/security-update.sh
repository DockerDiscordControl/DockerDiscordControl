#!/bin/bash
# Security Update Script for DockerDiscordControl
# Addresses potential vulnerabilities including CVE-2025-54388

echo "🔒 Starting security update for DockerDiscordControl..."

# Update base image to latest Alpine
sed -i 's/FROM alpine:3.22.1/FROM alpine:3.22.2/' Dockerfile

# Update critical Python packages
echo "📦 Updating Python dependencies..."

# Update requirements.txt with latest security patches
cat > requirements-security-update.txt << 'EOF'
# Security-patched dependencies
Flask==3.1.2
Werkzeug==3.1.4
py-cord==2.6.1
gunicorn==23.0.0
gevent==24.11.1
docker==7.1.0
cryptography>=45.0.5
APScheduler==3.10.4
python-dotenv==1.0.1
PyYAML==6.0.2
requests==2.32.5
aiohttp>=3.12.15
Flask-HTTPAuth==4.8.0
Jinja2>=3.1.5
python-json-logger==2.0.7
pytz==2024.2
cachetools==5.3.2
itsdangerous>=2.2.0
click>=8.1.7
blinker>=1.8.2
MarkupSafe>=2.1.5
flask-limiter>=3.5.0
limits>=3.9.0
greenlet>=3.0.3
zope.event>=5.0
zope.interface>=6.2
superlance==2.0.0
EOF

# Backup current files
cp Dockerfile Dockerfile.backup
cp requirements.txt requirements.txt.backup

echo "✅ Security update script created. Review and apply changes manually."
echo ""
echo "To apply updates:"
echo "1. Review the changes in requirements-security-update.txt"
echo "2. Update Dockerfile base image version"
echo "3. Run: ./rebuild.sh"
echo ""
echo "⚠️  Always test in a development environment first!"