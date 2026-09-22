# -*- coding: utf-8 -*-
"""The migration helper must work on the path production takes.

NO ``@covers`` marker: that would be a new guarantee, and those are the
operator's decision.

THE FINDING (stage 4, item 5 - second review, section 37), explicitly
released for repair by the operator.

``TokenSecurityManager.__init__`` sets ``self.config_service`` (:51-59) - and
ONLY that. ``migrate_to_environment_variable`` however reads ``self.config_manager``.
The attribute exists nowhere; the ``AttributeError`` is caught at :247
and passed through as ``error``.

WHAT THE OPERATOR SEES OF IT: the button in the token window calls
``/api/migration-help`` (``_token_security_modal.html:272``), and because
``result.success`` is false, the response lands in the ``alert`` branch (:279).
The screen then shows the raw Python text
``'TokenSecurityManager' object has no attribute 'config_manager'``. Not a
buried log entry - a dialog.

It is EXACTLY ONE break, not two: a suspicion that the UI also checks the
wrong field (``result.token`` versus ``plaintext_token``) was not
confirmed - ``security_service.py:174-175`` renames cleanly.

WHY THE EXISTING TESTS DO NOT CATCH THIS - and this is the instructive part:

* ``test_crypto_cache.py:332-340`` calls the method and checks that it returns
  an error dictionary. The comment there explicitly says
  "config_manager attribute is never set, so the AttributeError path is
  exercised". So the defect is **pinned down as expected behaviour**.
* ``test_utils_completion.py:1125-1138`` sets ``mgr.config_manager`` FROM OUTSIDE
  and thereby checks a success path that does not exist in production. A
  mirror test: it cannot fail for the real code.

Someone saw the defect and built tests **around** it instead of fixing
it. With this fix both become real tests - one word per line.

HOW IT IS CHECKED HERE: exclusively via what production supplies.
``TokenSecurityManager(config_service=...)`` - this and only this is how the
manager comes into being in operation (``security_service.py:75,112,155,208``,
``token_security.py:259,288,292``). No attribute is supplied from outside;
exactly that distinguishes this test from the mirror test above.

BOUNDARY: what the method outputs in substance (the decrypted token over
HTTP) is a documented decision of the operator - see SPEC.md B5.
This test does not question it, it only checks that the path is reachable
at all.

COUNTER-CHECK (carried out 2026-09-18) - two measurements, because three tests
had to be proven. TEST NAMES are given instead of line numbers: the lines in
``test_utils_completion.py`` shifted by one during cleanup, a noted number
would already be wrong.

*1. Two tests were red BEFORE the fix*, both on their own
assertions::

    1 passed, 2 failed
    test_migration_helper_delivers_the_token_on_the_production_path
        -> assert False is True   (success)
    test_without_decrypted_token_it_stays_a_failure
        -> 'decrypt' in "'tokensecuritymanager' object has no attribute
           'config_manager'"

The second error text is the finding itself: where a decryption message
should have been, the raw attribute error was. After the fix: 3 green.

*2. The guard ``test_production_passes_only_config_service`` was green from
the start* and therefore unproven. It guarantees that production supplies
``config_service`` and does NOT supply a ``config_manager`` afterwards - were
it blind, the old attribute could return without anything firing.
Mutation: ``__init__`` additionally sets ``config_manager``::

    1 failed, 2 passed

It turned red on ITS OWN ``hasattr`` assertion; the other two
stayed green.

*Four ways in which these reds would have been worthless* were fixed before
every run and never occurred: the test stays green (would be hollow); it fails
on a different assertion than the relationship being checked; the mutation
turns more red than claimed; error instead of failure, or collection error.

A PREDICTION OF MINE DID NOT COME TRUE, and it belongs here: I had announced
TWO existing tests as victims of the fix. Measured, FOUR broke -
``test_migrate_to_environment_variable_no_manager`` (test_crypto_cache.py) as well
as ``..._success_with_decrypted_token``, ``..._no_decrypted_token`` and
``..._propagates_attr_error`` (test_utils_completion.py). All four referred to
``config_manager``; the fourth was unknown to me until the measurement. For
this group I had deliberately predicted NO number - that was the right
decision.

All four were adapted, not removed: three now use
``config_service`` instead of ``config_manager`` (one word per spot) and have
thereby turned from mirror tests into real tests; the fourth explicitly sets
up the "no configuration service" branch instead of relying on a defect.
Afterwards: ``tests/unit/utils`` back to 248 green (+1 skipped) -
the same state as before the fix, NO fifth test fell.

AFFECTED GROUPS, all measured green: spec 91, unit/utils 248 (+1
skipped), services/web 358.
"""

import pytest

from utils.token_security import TokenSecurityManager

DECRYPTED = "DECRYPTED-TOKEN-4711"


class _ConfigServiceStub:
    """Behaves like ConfigService, as far as the method uses it.

    Deliberately NOT a MagicMock: a MagicMock returns something for every
    attribute - including ``config_manager``. It would then be impossible to
    tell whether the code uses the right attribute. This stub has exactly
    what ConfigService has too.
    """

    def __init__(self, config):
        self._config = config
        self.calls = 0

    def get_config(self):
        self.calls += 1
        return self._config


def test_production_passes_only_config_service():
    """Safeguard against a blunt tool.

    If ``config_manager`` did exist somewhere after all, the test below would
    check something other than claimed. In operation the manager is built
    exclusively as ``TokenSecurityManager()`` or with ``config_service=`` - a
    ``config_manager`` is never supplied afterwards.
    """
    manager = TokenSecurityManager(config_service=_ConfigServiceStub({}))

    assert hasattr(manager, "config_service"), (
        "The manager has no config_service - then this test's assumption "
        "about the production path is wrong."
    )
    assert not hasattr(manager, "config_manager"), (
        "The manager does have a config_manager - then the finding is "
        "different from the one described."
    )


def test_migration_helper_delivers_the_token_on_the_production_path():
    """THE FINDING: on the path production takes, nothing comes back.

    It is built exclusively with ``config_service`` - just as
    security_service.py and the module functions in token_security.py do. No
    attribute is supplied afterwards.
    """
    service = _ConfigServiceStub(
        {"bot_token_decrypted_for_usage": DECRYPTED}
    )
    manager = TokenSecurityManager(config_service=service)

    result = manager.migrate_to_environment_variable()

    assert result["success"] is True, (
        "The migration helper reports failure although the configuration service "
        "supplies a decrypted token. The method reads "
        "self.config_manager, but only self.config_service is set "
        "(token_security.py:51-59) - the AttributeError is caught at :247 "
        f"and passed through as error text: {result.get('error')!r}. The "
        "operator sees this raw Python text as a dialog in the token window."
    )
    assert result["plaintext_token"] == DECRYPTED
    assert any("DISCORD_BOT_TOKEN" in line for line in result["instructions"]), (
        "The instructions must name the environment variable - otherwise "
        "they are worthless as a migration aid."
    )
    assert service.calls == 1, (
        "get_config was not called exactly once - then the method takes "
        "a different path than assumed."
    )


def test_without_decrypted_token_it_stays_a_failure():
    """Boundary: the error path must be preserved.

    If the configuration service supplies no decrypted token, failure is
    correct - with a message that points to decryption and not to a missing
    attribute. Without this boundary a fix could drag the error path along
    with it.
    """
    manager = TokenSecurityManager(
        config_service=_ConfigServiceStub({"bot_token": "still-encrypted"})
    )

    result = manager.migrate_to_environment_variable()

    assert result["success"] is False
    assert "decrypt" in result["error"].lower(), (
        "The error message must point to decryption. If it shows an "
        "AttributeError, the path is still not reachable at all."
    )
    assert len(result["instructions"]) > 0
