# -*- coding: utf-8 -*-
"""An image pinned to a digest does not show a piece of the hash as its version.

THE FINDING (stage 4 review before v3.1.0, section 19b, both passes,
verified 2026-09-29). version_of took everything after the last ':' of the
image reference's last path segment as the tag. For a digest-pinned
reference - 'redis@sha256:<64 hex>', 'redis:7-alpine@sha256:<hex>' - or a
bare image id 'sha256:<hex>', that is the tail of the hash, which holds
digits and is not 'latest': the info display showed a hex fragment as the
app's version.

THE CONTRACT: the digest is not a tag; a tag before it ('7-alpine') still
counts.

HOW THIS TEST CAN FAIL: the digest's tail is taken for a tag again.

COUNTER-CHECK (2026-09-29): written before the fix and red then.
"""

from services.infrastructure.container_facts_service import version_of

DIGEST = "sha256:" + "a1" * 32


def test_a_pinned_reference_has_no_version_from_its_hash():
    assert version_of({}, f"redis@{DIGEST}") is None
    assert version_of({}, DIGEST) is None


def test_a_tag_before_the_digest_still_counts():
    assert version_of({}, f"redis:7-alpine@{DIGEST}") == "7-alpine"


def test_a_plain_tag_still_counts():
    """Counter-check."""
    assert version_of({}, "ghcr.io/x/valheim:1.2.3") == "1.2.3"
    assert version_of({}, "localhost:5000/app:latest") is None
