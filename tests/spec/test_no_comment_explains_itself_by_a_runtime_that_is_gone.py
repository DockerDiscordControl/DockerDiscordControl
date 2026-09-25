# -*- coding: utf-8 -*-
"""Nothing in the source may give supervisord as the reason it does something.

THE ROADMAP has carried this item since 2026-09-22: modules whose comments
still describe a DDC that ran under supervisord. Two of them were reasons -
not history, but the "because" of a decision that is still in the code::

    services/infrastructure/action_logger.py
        # logger.error, not stderr: ... and under supervisord stderr does not
        # reach the log the panel shows

    services/docker_proxy/allowlist_proxy.py
        # socketserver then printed its own traceback to stderr, which under
        # supervisord is not the log the operator reads

BOTH DECISIONS ARE RIGHT AND BOTH REASONS ARE WRONG, twice over. The image has
no supervisord - the Dockerfile installs none and the entrypoint starts none,
which the first case below reads rather than assumes. And stderr DOES reach a
log the operator reads: the Application tab falls through to the live container
output when no file backs it, which services/web/container_log_service.py says
in as many words.

A WRONG REASON IS WORSE THAN NO REASON. The next reader checks whether the
reason still holds, finds it does not, and takes the decision with it - and
the decisions here are a missing audit line and a traceback for a client that
has already hung up.

THE PHRASE IS THE INSTRUMENT, and that is unusual enough to say out loud. This
repository's rule is to ask the syntax tree for the call, the field or the
assignment rather than to match a word. There is no syntax tree for English:
the subject here IS prose, so prose is what is read. What keeps it honest is
that the premise is measured - the image really has no supervisor - and that a
comment which says supervisord is GONE stays green, which two of them do.

HOW THIS TEST CAN FAIL: an image that starts a supervisor after all, or a
comment giving one as a present reason.

COUNTER-CHECK (2026-09-26): red before on both files.
"""

import re
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
SOURCE = ("services", "app", "cogs", "utils")

# "under supervisord X is Y" - a reason in the present tense. A comment about
# the era that ended reads differently and is meant to stay: see
# container_log_service.py ("supervisord.log ... written by nobody") and
# port_diagnostics.py ("the image has no supervisord to ask").
AS_A_REASON = re.compile(r"\b(?:under|with|because of|thanks to)\s+supervisor", re.I)

# A RETIRED REASON IS QUOTED, NOT GIVEN. Both corrections say what the comment
# USED TO READ, in quotation marks - and the first run of this file went red on
# them, which is this repository's oldest self-inflicted wound: my own
# explanation tripping my own scan, now nine times. So a double-quoted run is
# taken out before the text is read. The triple quote that opens a docstring is
# neutralised first, or its two leading quote characters would pair with a
# later one and swallow live prose.
QUOTE_MARK = "\x00TRIPLE\x00"
A_QUOTED_RUN = re.compile(r'"[^"]*"', re.S)


def _prose_of(path):
    """The file with everything it merely QUOTES taken out."""
    text = path.read_text(encoding="utf-8").replace('"""', QUOTE_MARK)
    return A_QUOTED_RUN.sub(" ", text).replace(QUOTE_MARK, '"""')


def _python_files():
    for folder in SOURCE:
        for path in sorted((PROJECT / folder).rglob("*.py")):
            yield path


def test_the_image_starts_no_supervisor():
    """THE PREMISE, read rather than remembered. If a later DDC did run one,
    the rule below would be the wrong rule and this says so first."""
    dockerfile = (PROJECT / "Dockerfile").read_text(encoding="utf-8")
    entrypoint = (PROJECT / "scripts" / "entrypoint.sh").read_text(encoding="utf-8")

    assert "supervisor" not in dockerfile.lower(), \
        "the image installs a supervisor after all - this file's premise is gone"
    assert "supervisor" not in entrypoint.lower(), \
        "the entrypoint starts a supervisor after all"


def test_no_comment_gives_supervisord_as_a_reason():
    """THE FINDING. Both decisions are right; both reasons name a runtime
    that is not there."""
    guilty = []
    for path in _python_files():
        for number, line in enumerate(_prose_of(path).splitlines(), 1):
            if AS_A_REASON.search(line):
                guilty.append(f"{path.relative_to(PROJECT)}:{number}: {line.strip()}")

    assert guilty == [], (
        "these explain a decision by a runtime the image does not contain:\n  "
        + "\n  ".join(guilty))


def test_the_history_is_allowed_to_stay():
    """THE OPPOSITE MISTAKE, and it is the likely one: deleting every mention
    would take with it the two comments that exist BECAUSE supervisord is
    gone - a 3.2 MB supervisord.log served under the Application tab as if it
    were today's, and a port check that must not ask supervisorctl."""
    still_told = [path for path in _python_files()
                  if "supervis" in path.read_text(encoding="utf-8").lower()]
    names = {path.name for path in still_told}

    assert "container_log_service.py" in names, sorted(names)
    assert "port_diagnostics.py" in names, sorted(names)


def test_the_scan_reads_something(tmp_path):
    """The counter-check twelve sabotages have walked past: the rule passes
    on an empty file list, and it passes on an expression that matches
    nothing."""
    assert len(list(_python_files())) > 200, len(list(_python_files()))
    assert AS_A_REASON.search("and under supervisord stderr does not reach")
    assert AS_A_REASON.search("which under Supervisor is not the log")
    # and it does not claim the two that are meant to stay
    assert not AS_A_REASON.search("the image has no supervisord to ask")
    assert not AS_A_REASON.search("bot.log, webui_error.log and supervisord.log used to be listed")

    # The quote-stripping keeps the docstring around it, and takes the quoted
    # reason out of the middle of it. Both halves matter: without the first,
    # every docstring in the repository would fall out of the scan.
    written = tmp_path / "sample.py"
    written.write_text('"""A docstring.\n\n'
                       'It used to say "which under supervisord is not the log".\n'
                       'But it runs under supervisord now.\n"""\n', encoding="utf-8")
    prose = _prose_of(written)

    assert "A docstring." in prose, prose
    assert len(AS_A_REASON.findall(prose)) == 1, prose


def test_the_decisions_those_comments_explain_are_still_there():
    """A reason may be corrected; the thing it explains may not quietly go
    with it. An action that could not be written still reaches the log, and a
    refusal to a client that has left is still not a crash."""
    logger_line = (PROJECT / "services" / "infrastructure" / "action_logger.py").read_text(
        encoding="utf-8")

    assert "logger.error(f\"Action was not written to the action log" in logger_line

    proxy = (PROJECT / "services" / "docker_proxy" / "allowlist_proxy.py").read_text(
        encoding="utf-8")

    assert "def _refuse(" in proxy
    assert "except" in proxy[proxy.index("def _refuse("):proxy.index("def _refuse(") + 1500]
