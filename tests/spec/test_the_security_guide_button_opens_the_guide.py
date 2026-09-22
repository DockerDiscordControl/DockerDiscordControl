# -*- coding: utf-8 -*-
"""The "Security Guide" button in the token modal opens the guide, not a 404.

The button called ``window.open('/static/SECURITY.md')``. There is no
``app/static/SECURITY.md`` - the guide lives in ``docs/`` and is not served
by the panel - so both buttons that call it opened a 404, and nothing said
so. It now opens the guide in the repository.

COUNTER-CHECK (2026-09-22): red against the /static/ link, green after.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODAL = (ROOT / "app" / "templates" / "_token_security_modal.html").read_text(encoding="utf-8")
GUIDE = "https://github.com/DockerDiscordControl/DockerDiscordControl/blob/main/docs/SECURITY.md"


def test_the_button_opens_a_target_that_exists():
    body = re.search(r"function showSecurityGuideModal\(\) \{(.*?)\n\}", MODAL, re.S).group(1)
    targets = re.findall(r"window\.open\('([^']+)'", body)
    assert targets == [GUIDE], targets
    assert (ROOT / "docs" / "SECURITY.md").is_file()
