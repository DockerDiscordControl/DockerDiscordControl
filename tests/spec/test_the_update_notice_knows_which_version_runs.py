# -*- coding: utf-8 -*-
"""The update notice knows which version is running, and does not repeat itself.

Three in the update notifier, which posts "DDC has been updated" into the
control channels after an upgrade:

* the version it compares against is the literal "2025.01.07" in the source.
  The real version is DDC_VERSION, set by the Dockerfile and read by /health
  and the panel footer. So after the first installation the marker on disk
  already equals that literal and the notice never fires again - while its
  text still advertises the January 2025 feature set;
* a status file that cannot be written (the classic root-owned file) was
  ignored: the notice counted as shown, and on the next start it was posted
  again, into every channel, for ever;
* one successful channel marked the whole version done, so a channel that was
  unreachable at that moment never got it - and a crash before the mark sent
  it to everybody a second time. The channels that received it are recorded.

COUNTER-CHECK (2026-09-22): red before - the notifier reported the 2025
literal, a failed save still reported success, and the second run posted to
the channel that already had it.

THE TEXT, 2026-09-28. The first point above names it and it stayed: the notice
listed "new features" typed into the method in early 2025 - spam protection,
the /info command, the timezones - and would have announced them as new for
v3.1.0 in every control channel. It now names the version and links its release
notes, nothing that can go out of date. COUNTER-CHECK: with the old embed back,
the text case went red.

THE NOTES THEMSELVES, same day (operator: load them after the update, once per
version). The notice reads the installed version's release notes from GitHub
and shows them; without an answer - a build of develop, no internet - it links
them as above. The notes are hard-wrapped at ~95 characters, which GitHub joins
and Discord does not, so they are reflowed. COUNTER-CHECK: without the reflow
the paragraph case went red; with the notes ignored, the notes case did; with
the cut removed, the length case did.
"""

import json

import pytest

from services.infrastructure.update_notifier import UpdateNotifier


@pytest.fixture
def notifier(tmp_path, monkeypatch):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("DDC_VERSION", "3.0.0")
    return UpdateNotifier()


def test_the_running_version_is_the_image_version(notifier):
    assert notifier.current_version == "3.0.0"


def test_without_a_version_nothing_is_announced(tmp_path, monkeypatch):
    """Counter-check: guessing a version would post a notice about nothing."""
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("DDC_VERSION", raising=False)

    quiet = UpdateNotifier()

    assert quiet.should_show_update_notification() is False


def test_a_status_that_cannot_be_written_is_not_counted_as_shown(notifier, monkeypatch):
    monkeypatch.setattr(notifier, "save_update_status", lambda status: False)

    assert notifier.mark_notification_shown() is False
    assert notifier.should_show_update_notification() is True, (
        "the notice would be counted as delivered although nothing was written")


def test_a_channel_that_has_it_is_not_told_again(notifier):
    notifier.mark_notification_shown(channel_ids=[111])

    assert notifier.channels_still_to_tell([111, 222]) == [222]


def test_a_new_version_starts_again(notifier, monkeypatch):
    """Counter-check: the record is per version, not for ever."""
    notifier.mark_notification_shown(channel_ids=[111, 222])
    assert notifier.channels_still_to_tell([111, 222]) == []

    monkeypatch.setenv("DDC_VERSION", "3.1.0")
    later = UpdateNotifier()

    assert later.channels_still_to_tell([111, 222]) == [111, 222]


def test_the_notice_names_the_version_and_links_its_notes(notifier):
    embed = notifier.create_update_embed()
    link = "https://github.com/DockerDiscordControl/DockerDiscordControl/releases/tag/v3.0.0"
    assert "v3.0.0" in embed.title and link in embed.description and embed.url == link
    assert not embed.fields, "a list of features in the notice goes out of date"
    for stale in ("Spam Protection", "/info command", "Timezone"):
        assert stale not in embed.description, f"the notice still advertises {stale!r}"


NOTES = """# DDC v3.0.1: Security patch

When v3.0.0 reached `main`, GitHub's code scanner (CodeQL) read its code for the first time and
reported 25 places, and Docker Scout reported one package in the image.

---

## Security

- **A login link can no longer send the browser to another host.** After the login and the
  second factor, DDC returns to the page given in `next`.
- **The group list no longer shows a raw error text**, which could name a file path.

```
docker pull dockerdiscordcontrol/dockerdiscordcontrol:latest
```
"""


def test_the_notes_read_as_paragraphs_in_discord():
    from services.infrastructure.update_notifier import notes_for_discord
    text = notes_for_discord(NOTES)
    assert ("time and reported 25 places" in text), "a hard-wrapped paragraph stayed broken"
    assert "next`.\n- **The group list" in text, "two list items ran into one"
    assert "the page given in `next`" in text and "  second factor" not in text
    assert "---" not in text and "## Security" in text
    assert "```\ndocker pull dockerdiscordcontrol/dockerdiscordcontrol:latest\n```" in text


def test_the_notice_shows_the_notes_and_links_them(notifier):
    embed = notifier.create_update_embed(NOTES)
    assert "## Security" in embed.description
    assert embed.description.rstrip().endswith("releases/tag/v3.0.0")
    assert "Full release notes:" in embed.description


def test_long_notes_are_cut_at_a_paragraph(notifier):
    long_notes = "\n\n".join(f"Paragraph {i}. " + "word " * 60 for i in range(40))
    embed = notifier.create_update_embed(long_notes)
    assert len(embed.description) <= 4096, "Discord refuses a description this long"
    assert "…" in embed.description and "releases/tag/v3.0.0" in embed.description
    last = embed.description.split("…")[0].rstrip().rsplit("\n", 1)[-1]
    assert last.endswith("word"), f"cut inside a paragraph: {last[-40:]!r}"


async def test_without_an_answer_from_github_the_notice_links_the_notes(notifier, monkeypatch):
    import services.infrastructure.update_notifier as module
    posted = []

    class _Channel:
        async def send(self, embed):
            posted.append(embed)

    async def _no_notes(version, timeout=10.0):
        return None
    monkeypatch.setattr(module, "fetch_release_notes", _no_notes)
    monkeypatch.setattr(module, "load_config", lambda: {"channel_permissions": {
        "111111111111111111": {"commands": {"control": True}}}})
    bot = type("Bot", (), {"get_channel": lambda self, cid: _Channel()})()
    assert await notifier.send_update_notification(bot) is True
    assert "What is new is in the release notes" in posted[0].description

    async def _notes(version, timeout=10.0):
        return NOTES
    monkeypatch.setattr(module, "fetch_release_notes", _notes)
    monkeypatch.setenv("DDC_VERSION", "3.0.1")
    fresh = module.UpdateNotifier()
    assert await fresh.send_update_notification(bot) is True
    assert "## Security" in posted[1].description
    assert await fresh.send_update_notification(bot) is False, "shown twice for one version"


# ---------------------------------------------------------------------------
# Final check before v3.1.0 (2026-09-29).
#
# A CHANNEL THAT MISSED IT. channels_still_to_tell() records who has had the
# notice, but the version mark was the first gate: once one channel had it,
# should_show_update_notification() said no on every later start and the
# channel that was unreachable then never heard of the version.
#
# A CUT INSIDE A CODE BLOCK left the fence open, and the rest of the notice -
# the link to the full notes included - was drawn as code.
#
# COUNTER-CHECK (2026-09-29): with the gate back on the version mark alone the
# missed-channel test goes red; without the closing fence the code test does.
# ---------------------------------------------------------------------------

async def test_a_channel_that_missed_the_notice_gets_it_on_the_next_start(notifier, monkeypatch):
    import services.infrastructure.update_notifier as module
    posted = []

    class _Channel:
        def __init__(self, cid):
            self.cid = cid

        async def send(self, embed):
            posted.append(self.cid)

    async def _no_notes(version, timeout=10.0):
        return None
    monkeypatch.setattr(module, "fetch_release_notes", _no_notes)
    monkeypatch.setattr(module, "load_config", lambda: {"channel_permissions": {
        "111": {"commands": {"control": True}}, "222": {"commands": {"control": True}}}})
    reachable = {111}
    bot = type("Bot", (), {"get_channel": lambda self, cid: _Channel(cid) if cid in reachable else None})()

    assert await notifier.send_update_notification(bot) is True
    assert posted == [111]

    reachable.add(222)                              # the next start
    assert await module.UpdateNotifier().send_update_notification(bot) is True
    assert posted == [111, 222]
    assert await module.UpdateNotifier().send_update_notification(bot) is False, (
        "a channel that has it was told again")


def test_an_old_mark_without_channels_stays_done(notifier):
    """Counter-check: a version marked before the per-channel list is not re-sent."""
    status = notifier.get_update_status()
    status["last_notified_version"] = notifier.current_version
    status.pop("channels_notified", None)
    notifier.save_update_status(status)

    assert notifier.should_show_update_notification() is False


def test_a_cut_inside_a_code_block_closes_it(notifier):
    notes = "Intro.\n\n```\n" + "\n".join(f"line {i} " + "x" * 80 for i in range(80)) + "\n```\n\nEnd."
    embed = notifier.create_update_embed(notes)

    body = embed.description.split("Full release notes:")[0]
    assert body.count("```") % 2 == 0, "the link after the notes would be drawn as code"
