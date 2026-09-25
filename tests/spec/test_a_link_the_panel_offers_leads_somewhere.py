# -*- coding: utf-8 -*-
"""A button that opens a web page must open one that exists.

THE OPERATOR, 2026-09-26, on the System diagnostics dialog: "check this one
too, whether it works at all."

IT DID NOT. The footer's "View documentation" opened::

    https://docs.ddc.bot/troubleshooting

and that host does not exist - NXDOMAIN, measured from the Mac on
2026-09-26. Not moved, not renamed: there has never been a docs subdomain.
The button opened a blank tab and the browser's own error page.

THE PROJECT'S SITE ANSWERS ANY PATH WITH ITS FRONT PAGE, so a soft 404 is
what ddc.bot/troubleshooting gives as well - the same <title> as
ddc.bot/zzz-not-a-page. Checking a link by its status code would have called
that one healthy, which is why the rule below is about the HOST, not the
response.

TWO RULES, AND BOTH BUILD THEIR FACTS FROM THE TREE - a hand-kept list of
allowed addresses would go stale exactly like the line it guards:

1. The project's own address is the one its files carry in their banner
   comment, hundreds of times over. Any link in the panel to a host under
   ddc.bot has to BE that host.
2. A link into this repository has to name a file this repository has.

WHAT IS NOT CHECKED HERE: whether a third-party address answers. The suite
runs inside a container with no promise of a network, and a case that fails
when GitHub is slow is a case that gets switched off. Every outbound address
in the panel was fetched by hand on 2026-09-26 and all of them answered
except the one above.

HOW THIS TEST CAN FAIL: the panel offering a link to a host the project does
not have, or to a repository file that is not there.

COUNTER-CHECK (2026-09-26): red before - docs.ddc.bot/troubleshooting.
"""

import re
from collections import Counter
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
WHERE_THE_PANEL_IS = (PROJECT / "app" / "templates", PROJECT / "app" / "static" / "js")

URL = re.compile(r"https?://[A-Za-z0-9._~:/?#@!$&'()*+,;=%-]+")
REPO_FILE = re.compile(
    r"https://github\.com/DockerDiscordControl/DockerDiscordControl/blob/[^/]+/([^\s'\"<>)]+)")


def _pages():
    for root in WHERE_THE_PANEL_IS:
        for path in sorted(root.rglob("*")):
            if path.suffix in (".html", ".js"):
                yield path


def _links():
    """Every absolute address the panel hands to a browser, with its file."""
    found = []
    for path in _pages():
        for match in URL.finditer(path.read_text(encoding="utf-8")):
            # Trailing punctuation belongs to the markup, not to the address.
            found.append((path.relative_to(PROJECT), match.group(0).rstrip("\"'.,;)}>")))
    return found


def _the_projects_own_host():
    """Read out of the source banners rather than written down here.

    Nearly every file in this repository carries the project's address in its
    header comment. The one that appears most often is the project's site,
    and it cannot drift away from the code the way a constant in a test can.
    """
    seen = Counter()
    for path in sorted(PROJECT.glob("*/*.py")):
        head = path.read_text(encoding="utf-8", errors="ignore")[:800]
        for match in URL.finditer(head):
            host = match.group(0).split("//", 1)[1].split("/")[0]
            if host.endswith("ddc.bot"):
                seen[host] += 1
    return seen.most_common(1)[0][0] if seen else None


def test_the_projects_own_host_was_really_found():
    """The counter-check the sabotages keep walking past: a rule measured
    against nothing passes while proving nothing."""
    host = _the_projects_own_host()

    assert host == "ddc.bot", host


def test_every_link_to_the_project_uses_the_host_it_has(tmp_path):
    """THE FINDING: a documentation button aimed at a subdomain that has
    never existed."""
    ours = _the_projects_own_host()
    wrong = [(where, link) for where, link in _links()
             if re.match(r"https?://[^/]*ddc\.bot", link)
             and link.split("//", 1)[1].split("/")[0] != ours]

    assert wrong == [], (
        f"the panel offers links to a host the project does not have "
        f"(its own is {ours!r}): {wrong}")


def test_every_link_into_this_repository_names_a_file_that_is_here():
    """The other way the same defect arrives: the address stays valid and
    the file it names is renamed or deleted, and GitHub answers 404 in a
    tab the operator opened from the panel."""
    missing = []
    for where, link in _links():
        match = REPO_FILE.match(link)
        if match and not (PROJECT / match.group(1)).exists():
            missing.append((where, match.group(1)))

    assert missing == [], f"the panel links to repository files that are not here: {missing}"


def test_the_scan_reads_the_panel_and_not_an_empty_room():
    """Both rules above pass on zero links. These are the addresses the
    panel is known to carry, so an empty scan cannot look like a clean
    one."""
    links = _links()

    assert len(links) > 10, len(links)
    assert any("github.com/DockerDiscordControl" in link for _w, link in links)
    assert any("ddc.bot" in link for _w, link in links)
    assert any(REPO_FILE.match(link) for _w, link in links), \
        "no link into the repository was found, so that rule measured nothing"


def test_the_diagnostics_dialog_still_offers_its_documentation():
    """THE OPPOSITE MISTAKE. Deleting the button would also make the two
    rules above pass, and the operator would have lost the one thing that
    dialog offers besides the report."""
    dialog = (PROJECT / "app" / "templates" / "_diagnostics_modal.html").read_text(encoding="utf-8")

    assert "web.diagnostics.view_docs" in dialog, "the documentation button is gone"
    assert URL.search(dialog), "the documentation button points nowhere at all"
