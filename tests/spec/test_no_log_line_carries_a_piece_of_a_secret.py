# -*- coding: utf-8 -*-
"""A log line never carries part of a token, a password or a key.

THE OPERATOR (2026-09-25): "does every message make sense now?" This one did
not, and it is the only finding of the six that is a security matter:

    Starting bot with token ending in: ...3HlM      (bot.py:322)

Four characters of the Discord bot token, in the file people attach to bug
reports and paste into issues. It buys nothing an operator needs: which token
is in use is already answered, safely, one line earlier - "Using bot token from
environment variable" or "Using bot token from initial config loading".

AND FIXING ONLY THAT LINE WOULD HAVE BEEN FIXING THE SYMPTOM, which is the
mistake this whole week has been about. A scan for the pattern found a second:

    Attempting to decrypt token: <first ten characters>...
                                            (config_service.py:353, DEBUG)

Ten characters, not four - and DEBUG is no longer a safe hiding place, because
the debug switch was moved into the log page two days ago and now takes effect
without a restart. It is one click from an operator wanting to see what is
happening to a third of his bot token sitting in the file.

WHY A SLICE IS NOT SAFE. The instinct behind both lines is that a fragment
cannot be used. It does not have to be: a fragment confirms a guess, and it
tells anybody reading two logs whether they are looking at the same token.
Neither line needs to exist, so neither does.

THE RULE, and the scan behind it had to be narrowed twice before it flagged a
DECISION rather than an OCCURRENCE. Reading the whole logged expression as text
reported 35 sites, nearly all of them f-strings whose PROSE says "token" while
the value interpolated is an exception ("Token encryption failed: {e}"). What
matters is the VALUE: only the expressions actually substituted into the
message are read, and only an identifier that IS a secret - token, bot_token,
web_ui_password_hash, api_key - counts. TOKEN_RECHECK_INTERVAL and token_source
do not: they say something ABOUT a secret, which is exactly what a log should
say. And a bare `key` is a dictionary key here, not a secret - putting it in
the word set reported 37 innocent sites in one run, and a scan that cries wolf
teaches its reader to skip it, which is how the lying version line survived ten
months.

HOW THIS TEST CAN FAIL: any logger call that interpolates a value read out of
a token, a password, a key or a credential - sliced, hashed or whole.

COUNTER-CHECK (2026-09-25): red before - two sites, 4 and 10 characters.
"""

import ast
import re
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
SKIP = {"tests", ".git", "node_modules", "htmlcov", "venv", ".venv", "docs"}

A_LOG_CALL = re.compile(r"log(ger)?\.(debug|info|warning|error|critical|exception)$")

# BY NAME COMPONENT, not by whole name. The first version anchored the entire
# identifier - `^(\w+_)?(token|password|...)$` - and a sabotage that logged
# config['web_ui_password_hash'] sailed through GREEN on the `_hash` suffix. A
# password hash in a log file is a leak worth having: it is what an attacker
# takes away to crack offline. That was the seventh sabotage to survive one of
# my own cases, and the third by a pattern that was too literal about spelling.
SECRET_WORDS = {"token", "tokens", "secret", "secrets", "password", "passwords",
                "passwd", "credential", "credentials"}

# "key" ON ITS OWN IS NOT A SECRET, and putting it in the set above cried wolf
# 37 times in one run: cache_key, config_key, idempotency_key, form_data.keys().
# A scanner that reports those teaches its reader to skip it, which is how the
# lying regeneration line survived ten months. A key is only a secret in
# company, so the compound names are matched whole.
SECRET_PHRASES = ("apikey", "privatekey", "secretkey", "encryptionkey",
                  "signingkey", "sessionkey", "accesskey", "masterkey")

# ...and the words that mean the name holds something ABOUT a secret rather
# than the secret: an interval, a length, a source, a yes/no. Logging those is
# useful and safe, and flagging them would teach the reader to skip this scan.
ABOUT_A_SECRET = {"interval", "timeout", "length", "size", "count", "min", "max",
                  "path", "file", "dir", "url", "status", "enabled", "disabled",
                  "required", "error", "attempt", "source", "age", "expiry", "ttl",
                  "id", "name", "type", "mode", "version", "at", "since"}
A_QUESTION = ("has_", "is_", "should_", "can_", "was_", "needs_")


def _is_a_secret(identifier):
    """True when this name holds secret material itself."""
    lowered = identifier.lower()
    if lowered.startswith(A_QUESTION):
        return False                      # has_token is a yes/no, not a token
    parts = {part for part in re.split(r"[_\W]+", lowered) if part}
    if parts & ABOUT_A_SECRET:
        return False                      # TOKEN_RECHECK_INTERVAL, token_source
    if parts & SECRET_WORDS:
        return True                       # token, bot_token, web_ui_password_hash
    squashed = re.sub(r"[_\W]+", "", lowered)
    return any(phrase in squashed for phrase in SECRET_PHRASES)


def _names_in(node):
    """Every identifier this expression reads - including a string key, so
    config['bot_token'] is seen as reading bot_token."""
    for piece in ast.walk(node):
        if isinstance(piece, ast.Name):
            yield piece.id
        elif isinstance(piece, ast.Attribute):
            yield piece.attr
        elif isinstance(piece, ast.Subscript) and isinstance(piece.slice, ast.Constant) \
                and isinstance(piece.slice.value, str):
            yield piece.slice.value


def _values_logged(call):
    """The expressions SUBSTITUTED into the message, not its prose.

    This distinction is the whole scan. Reading the unparsed argument as text
    reported 35 sites, nearly all of them innocent f-strings that merely
    mention a token while interpolating an exception.
    """
    for argument in call.args + [keyword.value for keyword in call.keywords]:
        if isinstance(argument, ast.JoinedStr):
            for piece in argument.values:
                if isinstance(piece, ast.FormattedValue):
                    yield piece.value
        elif not isinstance(argument, ast.Constant):
            yield argument


def _leaks():
    for path in sorted(PROJECT.rglob("*.py")):
        if SKIP & set(path.relative_to(PROJECT).parts):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not A_LOG_CALL.search(ast.unparse(node.func)):
                continue
            for value in _values_logged(node):
                secrets = [name for name in _names_in(value) if _is_a_secret(name)]
                if secrets:
                    yield (f"{path.relative_to(PROJECT)}:{node.lineno} logs "
                           f"{ast.unparse(value)[:40]} (reads {secrets})")


def test_nothing_logs_a_piece_of_a_secret():
    """THE FINDING: four characters of the bot token at INFO, ten at DEBUG."""
    offenders = sorted(_leaks())

    assert offenders == [], (
        "a fragment still confirms a guess and still tells two logs apart - "
        f"say where the secret came from, never what it looks like: {offenders}")


def _found_in(source):
    """Run the scan over a snippet, the way it runs over the repository."""
    call = next(node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Call))
    return [name for value in _values_logged(call)
            for name in _names_in(value) if _is_a_secret(name)]


def test_the_scan_finds_the_lines_as_they_stood():
    """Counter-check, the one six earlier sabotages slipped past: a scan that
    matches nothing passes the case above while proving nothing."""

    assert _found_in('logger.info("token ending in: ...%s", token[-4:])') == ["token"]
    assert _found_in('logger.debug(f"decrypt: {config[\'bot_token\'][:10]}")') == ["bot_token"]
    assert _found_in('logger.info(f"pw {self.web_ui_password}")') == ["web_ui_password"]
    # The one that slipped through when the pattern anchored the whole name.
    assert _found_in('logger.debug(f"{config[\'web_ui_password_hash\']}")') == ["web_ui_password_hash"]


def test_prose_about_a_token_is_not_a_leak():
    """Counter-check the other way, and the reason the first version of this
    scan was useless. A scanner must flag a DECISION, not an occurrence."""
    for innocent in ('logger.error(f"Token encryption failed: {e}")',
                     'logger.warning(f"retrying in {TOKEN_RECHECK_INTERVAL}s")',
                     'logger.info(f"Password validation attempt for {self.container_name}")',
                     'logger.info("Using bot token from environment variable")',
                     # A key on its own is a dictionary key. Putting "key" in the
                     # word set reported 37 of these in one run.
                     'logger.debug(f"cache {cache_key} expired")',
                     'logger.info(f"fields: {list(form_data.keys())}")',
                     'logger.debug(f"unknown config_key {config_key}")',
                     'logger.info(f"api call took {api_time}ms")',
                     'logger.debug(f"token came from {token_source}")',
                     'logger.info(f"has a token: {has_token}")'):

        assert _found_in(innocent) == [], f"{innocent} would be reported"


def test_where_the_token_came_from_is_still_said():
    """The point is not silence about the token. An operator debugging a login
    needs to know WHICH source was used - that answer is safe and must stay."""
    said = (PROJECT / "app" / "bot" / "token.py").read_text(encoding="utf-8")

    assert "environment variable" in said and "config" in said, (
        "nothing says where the token was read from any more")
