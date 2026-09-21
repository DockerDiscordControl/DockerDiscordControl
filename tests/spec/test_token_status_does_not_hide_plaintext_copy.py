# -*- coding: utf-8 -*-
"""The token status display must not hide a plaintext copy on disk.

NO ``@covers`` marker: that would be a new guarantee, and guarantees are the
operator's decision. In substance this test belongs to Z9.

THE FINDING (stage 4, item 5 - second review, section 37), explicitly
released for correction by the operator.

``utils/token_security.py:153-157`` returns immediately as soon as
``DISCORD_BOT_TOKEN`` is set. ``token_exists`` and ``is_encrypted`` stay at
their defaults ``False`` - the file is never looked at. Consequence:

* ``services/web/security_service.py:265`` awards 40/40 and "Excellent"
* ``app/templates/_token_security_modal.html:74-79`` shows a green "Excellent"
* ``auto_encrypt_token_on_startup`` (wired in ``app/bootstrap/runtime.py:194``)
  requires ``token_exists`` and therefore never runs

and all this while a plaintext token may be sitting in ``bot_config.json``.

THE SYSTEM EQUATES "a secure source is used" WITH "no insecure copy exists".
That the environment variable is set says nothing about what is in the file.

WHAT THIS TEST DOES NOT DEMAND - and that is the operator's decision, not
mine: the score must NOT drop. The environment variable is right, it stays
40/40 and "Excellent". What is demanded is only that the display additionally
REPORTS the plaintext copy instead of hiding it. That is why
``test_the_good_news_remains`` explicitly checks that the good part is
preserved - a fix that tears it down has repaired the wrong thing.

THAT THE WARNING BECOMES VISIBLE is checked, not assumed:
``_token_security_modal.html:181-186`` renders the ``recommendations`` list
under its own heading. Without this check the test would have proven a
warning that nobody ever gets to see.

HOW IT IS REDIRECTED HERE: ``token_security.py:162`` builds
``Path(__file__).parents[1] / "config"`` INSIDE the function. So it is enough
to point the module's ``__file__`` to a fake file - the same technique as in
``tests/unit/services/configuration/test_config_full.py:964``. The existing
fixture ``fake_config_dir`` in ``tests/unit/utils/test_crypto_cache.py:59``
instead replaces the ``Path`` symbol with a stub class; it lives in a
different test group and cannot be imported over.

COUNTER-CHECK (performed 2026-09-18) - three measurements, because four tests
had to be proven. TEST NAMES are given instead of line numbers: twice in this
programme a noted line number did not survive the very write that noted it.

*1. Two tests were red BEFORE the fix*, both for the same cause::

    2 passed, 2 failed
    test_environment_variable_does_not_hide_the_plaintext_copy
        -> assert False is True   (token_exists)
    test_encrypted_token_triggers_no_warning
        -> assert False is True   (is_encrypted)

The early-returning code cannot look at the file - neither to find a
plaintext copy nor to recognise an encrypted one. After the fix: 4 green.

*2. The fixture guard was green from the start* and therefore unproven. It
ensures that the check happens in the throwaway directory at all; if the
redirection of ``__file__`` one day stopped working, the finding test would
run against the REAL configuration. Mutation: the path derivation ignores
``__file__``::

    1 passed, 3 failed

It turned red at ITS own ``token_exists`` assertion, with its own message.
``test_the_good_news_remains`` stayed green - the mutation does not reach into
the environment variable branch.

*3. ``test_the_good_news_remains`` was also green throughout.* It protects the
operator's explicit decision: the environment variable keeps its 40/40, the
warning comes ALONGSIDE the green. If it could not fail, the rating could one
day be destroyed without anything turning red. Mutation: the flag is not set,
the recommendation line deliberately stays::

    2 passed, 2 failed

It turned red at ITS own ``environment_token_used`` assertion. The finding
test failed as an announced knock-on effect (its warning depends on the
flag); guard and boundary test stayed green.

*Four ways in which these reds would have been worthless* were fixed before
each run and never occurred: the respective test stays green (would be
hollow); it fails on an assertion other than the relationship under test; the
mutation turns more red than claimed; collection or import error.

A PREDICTION THAT DID NOT COME TRUE, and it belongs here: I had announced two
deliberately written tests as casualties - ``test_crypto_cache.py:272-274``
("should remain False defaults") and ``test_utils_completion.py:530-534``.
Measured, BOTH stayed green: their fixtures create an empty configuration
directory, where the removed early return changes nothing. The announcement
was wrong; I only noticed during the run.

AFFECTED GROUPS, all measured green: spec 88, unit/utils 248 (+1
skipped), security 16 (+1), services/web 358, audit_2026_09 564,
blueprints 276, extended 731.
"""

import json

import pytest

from utils.token_security import TokenSecurityManager

# Long enough and dotted, which is all looks_like_discord_token asks - but
# deliberately not shaped like a real Discord token. The previous value was,
# and GitHub's push protection blocks that pattern; it stopped a push of
# mine on 2026-09-21 over a different file with the same habit.
PLAINTEXT_TOKEN = "NOT-A-REAL-TOKEN.for-tests-only.padded-past-fifty-characters"
ENCRYPTED = "gAAAAABmZ2VyeXRoaW5nSXNFbmNyeXB0ZWRIZXJlAAAA"


@pytest.fixture
def setup(tmp_path, monkeypatch):
    """Point TokenSecurityManager at a throwaway directory.

    Via ``DDC_CONFIG_DIR``. Until 2026-09-19 the module's ``__file__`` was
    redirected here, because the service derived the directory itself; since
    then it reads utils.config_paths.get_config_dir() (test_config_dir_token.py).
    When the trick stopped working, test_the_good_news_remains stayed GREEN
    without checking anything - the environment variable alone satisfies it.
    """
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setenv("DDC_CONFIG_DIR", str(config_dir))

    def write_bot_config(token):
        (config_dir / "bot_config.json").write_text(
            json.dumps({"bot_token": token}), encoding="utf-8")

    (config_dir / "web_config.json").write_text(
        json.dumps({"web_ui_password_hash": "pbkdf2:sha256:1$abc$def"}), encoding="utf-8")

    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)

    return type("Setup", (), {
        "config_dir": config_dir,
        "write_bot_config": staticmethod(write_bot_config),
        "monkeypatch": monkeypatch,
    })


def test_the_fixture_points_to_the_throwaway_directory(setup):
    """Safeguard against a blunt tool.

    If the redirection of ``__file__`` does not take effect, the service looks
    into the REAL ``config/`` - then the tests below would say nothing, and in
    the worst case they would have read the production configuration. Exactly
    this kind of construction has already made a detector worthless twice in
    this programme.
    """
    setup.write_bot_config(PLAINTEXT_TOKEN)

    status = TokenSecurityManager(config_service=object()).verify_token_encryption_status()

    assert status["token_exists"] is True, (
        "The service does not see the throwaway bot_config.json - the redirection of "
        "__file__ does not take effect, and the tests below prove nothing."
    )
    assert status["is_encrypted"] is False, (
        "A plaintext token must not count as encrypted."
    )


def test_the_good_news_remains(setup):
    """The intended part. Must be green before AND after the fix.

    The operator's decision is explicit: the score must NOT drop. If the
    environment variable is set, it stays reported - the full rating in
    ``security_service.py:265`` depends on that. A fix that turns this test
    red has repaired the wrong thing.
    """
    setup.monkeypatch.setenv("DISCORD_BOT_TOKEN", "env-token-xyz")
    setup.write_bot_config(PLAINTEXT_TOKEN)

    status = TokenSecurityManager(config_service=object()).verify_token_encryption_status()

    assert status["environment_token_used"] is True, (
        "The environment variable must still be reported as used - "
        "otherwise the rating in security_service.py:265 drops from 40 to 0."
    )
    assert any("environment variable" in r for r in status["recommendations"]), (
        "The confirming recommendation about the environment variable must not disappear."
    )


def test_environment_variable_does_not_hide_the_plaintext_copy(setup):
    """THE FINDING: environment variable set AND plaintext token in the file.

    Both at once is the case the display cannot see today: it returns before
    it looks at the file.
    """
    setup.monkeypatch.setenv("DISCORD_BOT_TOKEN", "env-token-xyz")
    setup.write_bot_config(PLAINTEXT_TOKEN)

    status = TokenSecurityManager(config_service=object()).verify_token_encryption_status()

    assert status["token_exists"] is True, (
        "The display reports there is no token in the file - although a "
        "PLAINTEXT token is there. It returns at token_security.py:153-157 "
        "before looking. Consequence: security_service.py:265 awards 40/40 and "
        "'Excellent', the panel shows green, and auto_encrypt_token_on_startup "
        "never runs."
    )
    assert status["is_encrypted"] is False, (
        "The token in the file is plaintext and must not count as encrypted."
    )
    assert any("bot_config" in r.lower() or "plaintext" in r.lower() or "klartext" in r.lower()  # language data
               for r in status["recommendations"]), (
        "There is no recommendation pointing to the plaintext copy. The "
        "UI renders the recommendations list "
        "(_token_security_modal.html:181-186) - so a warning there is "
        "seen. Without it the green display remains the only thing the "
        "operator gets to see."
    )


def test_encrypted_token_triggers_no_warning(setup):
    """Boundary: only a PLAINTEXT copy is the finding.

    If the file holds an encrypted token, that is the documented normal case
    and not worth a warning. Without this boundary the new message would
    appear on every normal installation - and a warning that always comes is
    ignored.
    """
    setup.monkeypatch.setenv("DISCORD_BOT_TOKEN", "env-token-xyz")
    setup.write_bot_config(ENCRYPTED)

    status = TokenSecurityManager(config_service=object()).verify_token_encryption_status()

    assert status["is_encrypted"] is True
    assert not any("klartext" in r.lower() or "plaintext" in r.lower()  # language data
                   for r in status["recommendations"]), (
        "An encrypted token must not trigger a plaintext warning."
    )
