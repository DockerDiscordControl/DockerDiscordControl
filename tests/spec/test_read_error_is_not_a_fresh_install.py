# -*- coding: utf-8 -*-
"""A read error on the configuration must not look like a fresh install.

NO ``@covers`` marker: that would be a new guarantee, and those are the
operator's decision.

THE FINDING (stage 4, item 5 - review with a second model, section 13
``services/config/``). The second model reported "swallowed PermissionError
opens the first-run login". The chain is real, but not the way it was
reported - and the differences are half the finding.

THE CHAIN, each link proven in the code:

1. ``services/config/config_service.py:714-717`` - ``_load_json_file`` catches
   ``(IOError, OSError, PermissionError)`` and returns ``default.copy()``.
   It **does not swallow the error**, it logs it with ``exc_info=True``. In
   that respect the second model was wrong. But: the return value is the same
   as if the file were empty. The same applies to ``json.JSONDecodeError``
   (:710-713) - a truncated config.json looks to the login like an unreadable
   one.
2. ``config_loader_service.py:119`` - the default for ``web_config.json``
   contains ``'web_ui_password_hash': None``.
3. ``config_loader_service.py:331`` (``_overlay_main_config``, real modular
   path) or ``:133-141`` (virtual path) - both substitute the default when the
   file cannot be read. The hash is then ``None``.
4. ``app/auth.py:176-183`` - ``if stored_hash is None`` opens the first-run
   login with ``admin`` / ``setup``.

WHAT THE FINDING IS NOT: "admin/setup is a back door". This branch is
intended, documented and tested -
``tests/unit/security/test_credential_cache.py:143`` explicitly guarantees it.
Removing it would destroy a guaranteed behaviour.

WHAT THE FINDING IS: a read error cannot be told apart from a fresh
installation. A permission problem on ``config/`` therefore opens the 70
routes behind ``@auth.login_required`` (``app/auth.py:27``) with a known
default login - unnoticed, because the login does work.

THAT THE DANGER WAS KNOWN is written in the code itself.
``config_service.py:385-386`` justifies the protection of critical fields on
SAVE literally with: "losing it drops the panel back into first-run setup
mode, where admin/setup is accepted on every route (app/auth.py)". The write
path is defended against exactly this case. The read path is not. So the
finding is not "nobody saw this", but "this was defended on one side and left
open on the other".

That the case is an everyday one is in the project rules: "always ``docker
exec -u ddc``" exists because root-owned files have broken the application
before. I do NOT claim that it happened - only that this would be the path.

THREE OWN MISTAKES ON THE WAY HERE. They are recorded here because they
explain the design of this test - each one of them would have carried a
worthless test into the commit:

*First*, the first version of the fix checked whether a configuration file
EXISTS on disk. For that it called ``get_config_service()`` - and its
constructor creates files itself via ``ensure_modular_structure`` (:242) and
``_fold_legacy_settings_once`` (:248). Measured, not assumed: in a test
directory that started empty there were afterwards ``config.json``,
``docker_config.json``, ``servers_config.json`` and a backup folder with the
timestamp of the same run. **The check created the condition it checked.**
The existing test ``test_first_time_setup_still_works_without_a_hash`` found
it by turning red - had I "made it fit", the bug would have gone into the
commit.

*Second*, "is there a file" was also the wrong question on the merits. The
right question is whether an error occurred while READING; on a fresh
installation none occurs.

*Third*, the second version of this fixture only redirected the service's
PATH ATTRIBUTES. But ``_loader_service`` had been built in the constructor
with the old paths and kept reading the real ``config/`` undeterred - the
tests ran against the production configuration instead of the throwaway
directory. The guard against that was itself blunt: it checked
``service.config_dir``, i.e. the value the fixture had just set itself.
Expectation and assertion from the same source - the same pattern as the
mirror test in ``test_app_factory_wiring.py``. That is why the guard now
checks the path that **the loader** uses.

HOW IT IS CHECKED HERE: the file is **really** made unreadable or genuinely
damaged, not simulated via monkeypatch; ``load_config`` is deliberately NOT
redirected. And before any damage it is proven that the hash WAS LOADED
beforehand - otherwise "hash is None" would already be the initial state, and
the test would get the right result for the wrong reason.

COUNTER-CHECK (done 2026-09-17) - three measurements, because three different
things had to be proven:

*1. The two finding tests were red BEFORE the fix* - and for the right reason,
proven by real tracebacks from the chain itself, not by a fitting error
message::

    unreadable -> config_service.py:715  PermissionError [Errno 13], traceback from
                  open() in line 703, then auth.py:179 "FIRST TIME SETUP:
                  Setup mode activated with temporary credentials"
    broken     -> config_service.py:711  JSONDecodeError ("Expecting ',' delimiter"),
                  traceback from json.load in line 704, then the same line 179

Before 3 green / 2 red, after 5 green.

*2. Four ways noted in advance in which this red would have been worthless*
all did NOT occur: the loader guard held, the hash was demonstrably loaded
before the damage ("Real modular config loaded: 1 servers"),
``pytest.raises(PermissionError)`` fired, and the damage propagated all the
way to the missing hash. The list was fixed BEFORE the run; otherwise I would
have picked afterwards what counts as proof.

*3. The guard ``test_real_first_install_still_works`` was green from the
start* - so until proven otherwise a test that cannot fail. It is the one that
protects the INTENDED behaviour; if it were blind, the first-run login could
be destroyed without anything turning red. Mutation: ``get_config`` always
reports a read error::

    with mutation -> 1 failed, 4 passed

Exactly it turned red, at the right line (:279, ``assert ... == "admin"``,
``assert None == 'admin'``), with the injected reason in the log
("could not be read (MUTATION)"). The two finding tests stayed green - they
want the door closed anyway. Mutation reverted, afterwards 5 green again.
"""

import json
import os
import stat

import pytest
from flask import Flask
from werkzeug.security import generate_password_hash

from app import auth as auth_module
from services.config.config_cache_service import ConfigCacheService
from services.config.config_loader_service import LEGACY_FOLD_MARKER, ConfigLoaderService
from services.config.config_migration_service import ConfigMigrationService
from services.config.config_service import get_config_service

PASSWORD = "correct-horse-battery"


def _hash(password):
    # Cheap derivation: this test cares about the path of the value, not about
    # the cost of the derivation. The production number (600,000 rounds) is
    # pinned in tests/security/test_security_sast.py.
    return generate_password_hash(password, method="pbkdf2:sha256:1")


@pytest.fixture
def auth_environment(tmp_path):
    """Flask context + ConfigService singleton on a throwaway directory.

    Pattern taken from ``tests/unit/audit_2026_09/test_pkg_c2_config.py:54``
    - INCLUDING the rebuild of the sub-services (:77-85). Without it
    ``_loader_service`` keeps reading at the paths it was built with in the
    constructor; that is exactly where the second version of this test failed.

    ``containers/`` and ``channels/`` are created so that
    ``has_real_modular_structure()`` applies: in this layout ``config.json`` is
    the authoritative file, and only then does the test prove anything about it
    at all.

    The fold marker is written so that the one-time conversion
    (``_fold_legacy_settings_once``) does not rewrite files in the middle of
    the test.
    """
    app = Flask(__name__)
    # The first-run branch writes session['setup_mode']; without a key Flask
    # refuses ("The session is unavailable because no secret key was set").
    # Only the test application needs it.
    app.secret_key = "test-secret-lesefehler"

    service = get_config_service()
    saved_state = dict(service.__dict__)

    config_dir = tmp_path / "config"
    (config_dir / "containers").mkdir(parents=True)
    (config_dir / "channels").mkdir()
    (config_dir / "containers" / "web.json").write_text(
        json.dumps({"docker_name": "web", "active": True}), encoding="utf-8"
    )
    (config_dir / LEGACY_FOLD_MARKER).write_text("{}", encoding="utf-8")

    service.config_dir = config_dir
    service.channels_dir = config_dir / "channels"
    service.containers_dir = config_dir / "containers"
    service.main_config_file = config_dir / "config.json"
    service.auth_config_file = config_dir / "auth.json"
    service.heartbeat_config_file = config_dir / "heartbeat.json"
    service.web_ui_config_file = config_dir / "web_ui.json"
    service.docker_settings_file = config_dir / "docker_settings.json"
    service.bot_config_file = config_dir / "bot_config.json"
    service.docker_config_file = config_dir / "docker_config.json"
    service.web_config_file = config_dir / "web_config.json"
    service.channels_config_file = config_dir / "channels_config.json"
    service._migration_service = ConfigMigrationService(
        config_dir, service.channels_dir, service.containers_dir
    )
    service._cache_service = ConfigCacheService()
    service._loader_service = ConfigLoaderService(
        config_dir, service.channels_dir, service.containers_dir,
        service.main_config_file, service.auth_config_file, service.heartbeat_config_file,
        service.web_ui_config_file, service.docker_settings_file, service.bot_config_file,
        service.docker_config_file, service.web_config_file, service.channels_config_file,
        service._load_json_file, service._validation_service,
    )

    auth_module.clear_credential_cache()
    try:
        with app.app_context():
            yield type("Environment", (), {
                "app": app,
                "config_dir": config_dir,
                "service": service,
            })
    finally:
        auth_module.clear_credential_cache()
        # Reset permissions, otherwise pytest cannot clean up tmp_path.
        for path in config_dir.rglob("*"):
            try:
                path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
            except OSError:
                pass
        service.__dict__.clear()
        service.__dict__.update(saved_state)


def test_the_test_does_not_run_as_root():
    """Safeguard against a blunt tool.

    root ignores file permissions. If this test ran as root, the "unreadable"
    file would be happily readable, the finding test below would turn green -
    and would prove nothing. ``scripts/ddc_test.sh:81`` starts the container
    with ``-u ddc``; this test makes sure it stays that way.
    """
    assert hasattr(os, "geteuid"), "Not a POSIX system - the permission test does not hold here."
    assert os.geteuid() != 0, (
        "This test runs as root. root ignores file permissions, the 'unreadable' "
        "file would be readable and the finding test would turn green without "
        "proving anything. The test runner must start with -u ddc."
    )


def test_the_loader_really_points_to_the_throwaway_directory(auth_environment):
    """Safeguard against a blunt tool - and at the right place.

    The previous version checked ``service.config_dir``: the value the fixture
    had set itself. It is always right and proves nothing. Reading goes through
    ``_loader_service``, and its paths come from ITS constructor. Only checking
    them rules out that the tests below run against the real configuration.
    """
    loader = auth_environment.service._loader_service
    assert loader.config_dir == auth_environment.config_dir, (
        "The LOADER does not point to the throwaway directory - the tests below "
        "would run against the real configuration."
    )
    assert loader.main_config_file == auth_environment.config_dir / "config.json"
    assert loader.has_real_modular_structure(), (
        "Without a real modular layout config.json is not the authoritative "
        "file - then damage to it proves nothing."
    )


def test_real_first_install_still_works(auth_environment):
    """The intended branch. Must be green before AND after the fix.

    No config.json, no read error: a missing hash is then exactly what it looks
    like - a fresh installation. ``admin`` / ``setup`` is the intended path,
    guaranteed in ``tests/unit/security/test_credential_cache.py:143``. A fix
    that turns this test red has repaired the wrong thing.
    """
    assert not auth_environment.service.main_config_file.exists(), (
        "The initial state is wrong - there must not be a config.json here yet."
    )
    configuration = auth_environment.service.get_config(force_reload=True)
    assert configuration.get('web_ui_password_hash') is None

    with auth_environment.app.test_request_context():
        assert auth_module.verify_password("admin", "setup") == "admin", (
            "The first-run login without a password and without a read error is "
            "intended, guaranteed behaviour and must not be fixed along with it."
        )


def _plant_hash_and_prove_it(environment):
    """Set the hash AND prove that it is loaded.

    Without this proof "hash is None" would already be the initial state: the
    tests below would get the right result without the damage to the file
    having anything to do with it.
    """
    hash_value = _hash(PASSWORD)
    environment.service.main_config_file.write_text(
        json.dumps({"web_ui_user": "admin", "web_ui_password_hash": hash_value}),
        encoding="utf-8",
    )
    loaded = environment.service.get_config(force_reload=True)
    assert loaded.get('web_ui_password_hash') == hash_value, (
        "The hash from config.json is not loaded at all - then damage to this "
        "file proves nothing about the login."
    )
    return hash_value


def test_unreadable_configuration_does_not_open_first_run_login(auth_environment):
    """THE FINDING: the configuration is unreadable - that is not a fresh install.

    The file is really made unreadable (``chmod 000``), not simulated.
    Then the chain from the module docstring runs: ``_load_json_file`` returns
    the default, the hash is ``None``, and ``verify_password`` takes that for a
    fresh setup.
    """
    _plant_hash_and_prove_it(auth_environment)

    auth_environment.service.main_config_file.chmod(0)
    with pytest.raises(PermissionError):
        auth_environment.service.main_config_file.read_text(encoding="utf-8")

    configuration = auth_environment.service.get_config(force_reload=True)
    assert configuration.get('web_ui_password_hash') is None, (
        "A vanished hash was expected - otherwise the test below does not "
        "check the finding."
    )

    with auth_environment.app.test_request_context():
        result = auth_module.verify_password("admin", "setup")

    assert result is None, (
        "config.json was NOT READABLE, so the hash came back as None - "
        "that is a read error, not a fresh install. admin/setup must not get "
        "through here: 70 routes with @auth.login_required hang behind it, "
        "and nobody would notice, because the login does work."
    )


def test_broken_configuration_does_not_open_first_run_login(auth_environment):
    """The same damage from the other direction: readable, but not valid JSON.

    ``_load_json_file:710-713`` catches ``JSONDecodeError`` and likewise returns
    the default. For the login the result is identical. A fix that only looks
    at permission errors would leave this path open - a half fix that looks
    complete.
    """
    _plant_hash_and_prove_it(auth_environment)

    auth_environment.service.main_config_file.write_text(
        '{"web_ui_password_hash": "abc"', encoding="utf-8"
    )

    configuration = auth_environment.service.get_config(force_reload=True)
    assert configuration.get('web_ui_password_hash') is None, (
        "A vanished hash was expected - otherwise the test below does not "
        "check the finding."
    )

    with auth_environment.app.test_request_context():
        result = auth_module.verify_password("admin", "setup")

    assert result is None, (
        "config.json is truncated and therefore cannot be parsed. The missing "
        "hash is the consequence of a read error, not a fresh install - "
        "admin/setup must not get through."
    )
