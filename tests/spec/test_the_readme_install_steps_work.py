# -*- coding: utf-8 -*-
"""The README's installation steps work as written.

THE FINDING (operator's question, 2026-10-11: "is the installation guide
current?"):
* "Bot Setup Guide" and eight more wiki links held U+2010 instead of a plain
  hyphen; GitHub sends such a link to the wiki's home page without a word.
  One named "Status-Watchdog", a page that no longer exists.
* docker-compose.yml named the image "dockerdiscordcontrol", the local tag
  only a build from the source creates, so "docker compose pull" fetched
  nothing and Method 1 built the image from the source.
* Method 2 passed a new random FLASK_SECRET_KEY to every new container, which
  logged everybody out at each update; DDC keeps its own in config/.

THE CONTRACT: every wiki link in the README is plain ASCII and names a page
of today's wiki; the compose file names the published image; the README's
direct Docker Hub example carries no FLASK_SECRET_KEY, mounts the socket
read-only and caps its log.

HOW THIS TEST CAN FAIL: any of the above back.

COUNTER-CHECK (2026-10-11): all three cases red on the files before the change.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
README = (ROOT / "README.md").read_text(encoding="utf-8")

# The wiki's pages (github.com/DockerDiscordControl/DockerDiscordControl/wiki), 2026-10-11.
WIKI_PAGES = {
    "Home", "Admin-Users", "Alpine-Linux-Migration", "Architecture", "Auto-Action-System",
    "Backup-and-Restore", "Channel-Translation", "Configuration", "Container-Groups",
    "Container-Watchdog", "Development", "Discord-Bot-Setup", "Docker-Socket-Proxy",
    "HTTPS-and-Reverse-Proxy", "Info-Display-and-Player-Counts", "Installation-Guide",
    "Mech_System", "Memory-Optimization", "Performance-and-Architecture", "Security",
    "Task-System", "Troubleshooting", "Two-Factor-Authentication", "Upgrading-to-v3",
    "WebUI_Settings",
}


def test_every_wiki_link_names_a_real_page():
    links = re.findall(r"\]\(\.\./\.\./wiki/([^)#\s]+)", README)
    assert links, "premise: the README links the wiki"
    wrong = sorted({link for link in links if not link.isascii() or link not in WIKI_PAGES})
    assert not wrong, f"these wiki links land on the home page or nowhere: {wrong}"


def test_the_compose_file_names_the_published_image():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert re.search(r"^\s*image:\s*dockerdiscordcontrol/dockerdiscordcontrol:latest\s*$", compose, re.M)


def test_the_direct_docker_hub_example():
    section = README[README.index("**Method 2: Docker Hub (Direct)**"):README.index("**Method 3:")]
    command = section.split("```")[1]
    assert "FLASK_SECRET_KEY" not in command, "a new key per container logs everybody out"
    assert "/var/run/docker.sock:/var/run/docker.sock:ro" in command
    assert "--log-opt max-size=10m" in command
