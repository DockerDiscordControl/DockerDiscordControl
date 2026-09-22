# -*- coding: utf-8 -*-
"""Only the trust list decides whether a forwarded address is believed.

Two ways that do the same thing drift apart. ``app/web/extensions.py`` now
believes ``X-Forwarded-For`` only from the proxies in ``DDC_TRUSTED_PROXIES``
and hands the result on as ``request.remote_addr``. But
``services/web/donation_tracking_service.py`` read the header itself, raw, and
preferred it over ``remote_addr`` - so the address recorded for a donation
click was whatever the client claimed, trust list or not.

The fix is to have one place: app code uses ``request.remote_addr`` and never
reads the forwarded headers itself. The source scan below keeps a second
reader from coming back.

COUNTER-CHECK (2026-09-22): both tests red before the change - the identifier
was "IP: 192.0.2.99" (the forged header), and the scan named
donation_tracking_service.py - green after.
"""

from pathlib import Path
from types import SimpleNamespace

PROJECT = Path(__file__).resolve().parents[2]
NOT_APP_CODE = {".git", "tests", "config", "logs", "node_modules", "__pycache__", ".pytest_cache", "docs"}
FORWARDED = ("x-forwarded-for", "x-forwarded-proto", "x-forwarded-host", "x-real-ip", "access_route")


def test_the_donation_log_records_the_peer_not_the_claim():
    from services.web.donation_tracking_service import DonationTrackingService

    request = SimpleNamespace(remote_addr="203.0.113.5", headers={"X-Forwarded-For": "192.0.2.99"})
    service = DonationTrackingService.__new__(DonationTrackingService)
    assert service._get_ip_identifier(request) == "IP: 203.0.113.5"


def test_no_app_code_reads_forwarded_headers_itself():
    readers = []
    for path in sorted(PROJECT.rglob("*.py")):
        relative = path.relative_to(PROJECT)
        if relative.parts[0] in NOT_APP_CODE:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0].lower()
            if any(marker in code for marker in FORWARDED):
                readers.append(f"{relative}:{lineno}")
    assert not readers, "Only app/web/extensions.py (via ProxyFix) may decide: " + ", ".join(readers)
