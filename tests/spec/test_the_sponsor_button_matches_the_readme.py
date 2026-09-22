# -*- coding: utf-8 -*-
"""GitHub's Sponsor button offers the same donation links as the README.

Roadmap side task (operator decision 2026-09-22): a .github/FUNDING.yml so
GitHub shows a Sponsor button. It repeats links the README already has - two
places for the same thing - so this keeps them the same: every donation link
in FUNDING.yml appears in the README, and the README's Buy Me a Coffee and
PayPal links are both offered.

GitHub Sponsors itself (``github:``) is left out until the operator names the
account; a wrong or unenrolled name would show a broken entry.

COUNTER-CHECK (2026-09-22): red before the file existed.
"""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_funding_offers_the_readme_links():
    funding = yaml.safe_load((ROOT / ".github" / "FUNDING.yml").read_text(encoding="utf-8"))
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert funding["buy_me_a_coffee"] == "dockerdiscordcontrol"
    assert f"https://buymeacoffee.com/{funding['buy_me_a_coffee']}" in readme
    custom = funding["custom"] if isinstance(funding["custom"], list) else [funding["custom"]]
    paypal = [u for u in custom if "paypal.com" in u]
    assert paypal and all(u in readme for u in custom), custom
    readme_paypal = re.findall(r"https://www\.paypal\.com/donate/\?hosted_button_id=\w+", readme)
    assert set(readme_paypal) <= set(custom), readme_paypal
