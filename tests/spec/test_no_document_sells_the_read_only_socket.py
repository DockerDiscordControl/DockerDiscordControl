# -*- coding: utf-8 -*-
"""No user document presents the read-only socket mount as protection.

V3 §2 says it plainly: `:ro` makes the socket FILE unmodifiable and does
nothing to the API reached through it - DDC's own Stop button works through
that very mount. SECURITY.md was corrected in v3.0 and is guarded by
test_security_md_claims_only_what_holds.py. THE FINDING (audit 2026-09-26):
five other documents still sold it, as a best practice, a checklist item and a
"security feature" - and TROUBLESHOOTING.md told the operator the socket should
be reachable by the docker group, which is exactly how DDC would end up on the
raw socket again, and to run `docker ps` in an image that has no docker CLI.

HOW THIS TEST CAN FAIL: one of these sentences comes back into docs/.

COUNTER-CHECK (2026-09-26): red before the fix, one hit per phrase.
"""

from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parents[2] / "docs"

CLAIMS = (
    "Read-only Docker socket",
    "Use read-only Docker socket",
    "Docker socket mounted read-only",
    "# Read-only mount",
    "Should be accessible by docker group",
    "281(docker)",
    "docker exec ddc docker ps",
)


# These quote the old texts on purpose: the archive and the quality records
# as history, the V3 plan to say why the claim was false.
QUOTING = ("V3_ARCHITECTURE_PLAN.md",)


def _user_documents():
    return [path for path in sorted(DOCS.rglob("*.md"))
            if "archive" not in path.parts and "quality" not in path.parts
            and path.name not in QUOTING]


@pytest.mark.parametrize("claim", CLAIMS)
def test_the_claim_is_nowhere(claim):
    hits = [path.name for path in _user_documents() if claim in path.read_text(encoding="utf-8")]

    assert hits == [], f"{claim!r} is back in {hits}"


def test_the_documents_are_actually_read():
    """Counter-case: a scan that finds no files proves nothing."""
    names = {path.name for path in _user_documents()}

    assert {"SECURITY_WIKI.md", "CONFIGURATION.md", "TROUBLESHOOTING.md"} <= names
