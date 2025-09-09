#!/bin/bash
# Quick environment test for Unraid

echo "=== DDC Environment Test ==="
echo

echo "Testing Python availability:"
echo "which python3: $(which python3 2>/dev/null || echo 'NOT FOUND')"
echo "which python: $(which python 2>/dev/null || echo 'NOT FOUND')"
echo "/usr/bin/python3: $(test -f /usr/bin/python3 && echo 'FOUND' || echo 'NOT FOUND')"
echo

echo "Testing pip availability:"
echo "which pip3: $(which pip3 2>/dev/null || echo 'NOT FOUND')"
echo "which pip: $(which pip 2>/dev/null || echo 'NOT FOUND')"
echo

echo "Testing direct Python execution:"
if /usr/bin/python3 --version 2>/dev/null; then
    echo "✓ /usr/bin/python3 works"
    echo "Testing pip module:"
    if /usr/bin/python3 -m pip --version 2>/dev/null; then
        echo "✓ /usr/bin/python3 -m pip works"
    else
        echo "✗ pip module not available"
    fi
else
    echo "✗ /usr/bin/python3 not working"
fi

echo
echo "Current working directory: $(pwd)"
echo "PATH: $PATH"
echo

echo "Testing pytest availability:"
if /usr/bin/python3 -c "import pytest; print('✓ pytest available')" 2>/dev/null; then
    echo "pytest is already installed"
else
    echo "pytest needs to be installed"
fi