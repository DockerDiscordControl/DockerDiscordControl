# -*- coding: utf-8 -*-
"""A silent game server, a newer image, and who joins - said, not hidden (v3.1.0).

Agreed with the operator on 2026-09-28, in this order:

1. A SILENT GAME SERVER IS SAID. Found live the same day: the Enshrouded server
   had stopped on 16 September - its log ends there, no process listens - while
   its container ran on (a `tail -f` keeps it alive) and stood 🟢 online for
   twelve days. The support check had marked it unreachable long before, and
   the info display stayed silent. It says so now, without asking again - and a
   server that answered once and fell silent is asked again every 30 minutes,
   so one that comes back is not called silent for good.
2. A NEWER IMAGE IS SAID in the info display. The registry check existed
   (Phase 4d) but ran only for operators with an image_update rule. The
   display asks through a six-hour cache and never says "up to date" on an
   unknown answer.
3. WHO JOINS is announced in the channels whose "Player joins" box is ticked -
   by name where the game names everyone, by count where it does not or sends
   only a sample; never on the first look after a start; a failed query keeps
   what was seen, so the next join is still noticed.

COUNTER-CHECK (2026-09-28): with the verdict check removed from player_list,
the silent-server case went red; with should_probe back to "final is final",
the comes-back case did; with cached_remote_digest asking every time,
the cache case did; with the first look announcing, the first-look case did;
with a Minecraft sample compared by name, the sample case did; with a failed
query forgetting what was seen, the hiccup case did - its first version, which
checked for a re-announcement, stayed green: forgetting makes the next cycle a
first look, which announces nobody; what it loses is the next join.
"""

import asyncio
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from cogs import info_extras, player_joins
from services.automation import image_updates
from services.infrastructure.container_facts_service import ContainerFacts, facts_from_attrs
from services.infrastructure.game_query_service import PlayerList

ROOT = Path(__file__).resolve().parents[2]


# --- 1. a silent game server ---------------------------------------------------

def _verdict(monkeypatch, supported):
    import services.infrastructure.game_query_support_service as support_mod
    monkeypatch.setattr(support_mod, "get_game_query_support_service",
                        lambda: SimpleNamespace(is_supported=lambda name: supported,
                                                get_protocol=lambda name: "source"))


def test_a_server_found_silent_is_said_at_once(monkeypatch):
    _verdict(monkeypatch, False)
    monkeypatch.setattr(info_extras, "_is_running", lambda name: True)

    async def _never(cfg):
        raise AssertionError("a server known to be silent was asked again")
    monkeypatch.setattr(info_extras, "_request_for", _never)
    started = time.monotonic()
    players = asyncio.run(info_extras.player_list({"docker_name": "Enshrouded_Proton", "query_enabled": True}))
    assert time.monotonic() - started < 0.5
    assert "does not answer" in info_extras.format_players(players)


def test_a_stopped_silent_server_is_not_called_silent(monkeypatch):
    _verdict(monkeypatch, False)
    monkeypatch.setattr(info_extras, "_is_running", lambda name: False)
    assert asyncio.run(info_extras.player_list({"docker_name": "V-Rising", "query_enabled": True})) is None


def _silent_for_good(tmp_path):
    """A server that answered, then fell silent through the whole 15-minute window."""
    from services.infrastructure import game_query_support_service as mod
    service = mod.GameQuerySupportService(path=tmp_path / "query_support.json")
    service.record_result("Enshrouded", True, protocol="source")
    for _ in range(mod.QUERY_FAILURE_DEMOTE_THRESHOLD):
        service.note_query_failure("Enshrouded")
    since = service._state["Enshrouded"]["probing_since"]
    # A probe a minute through the window, as the status cycle makes them
    for minute in range(1, int(mod.PROBE_WINDOW_SECONDS // 60) + 2):
        service._state["Enshrouded"]["updated"] = since + (minute - 1) * 60
        service.record_result("Enshrouded", False, now_wall=since + minute * 60)
    assert service.is_final("Enshrouded") and service.is_supported("Enshrouded") is False
    return mod, service


def test_a_server_that_comes_back_is_seen_again(tmp_path):
    """FOUND BY THE RESTART of the operator's Enshrouded server (2026-09-28): a
    server that answered once, died and stayed silent for 15 minutes became a
    FINAL "unreachable" - never asked again. It recovered that day only because
    the day's rebuilds kept restarting its window. With the warning above, a
    recovered server would have been called silent to everyone, for good."""
    mod, service = _silent_for_good(tmp_path)
    service.mark_probed("Enshrouded", 1000.0)
    assert not service.should_probe("Enshrouded", 1000.0 + 60)
    assert service.should_probe("Enshrouded", 1000.0 + mod.DEMOTED_RETRY_SECONDS)
    service._state["Enshrouded"]["final"] = True  # a failed re-probe leaves it as it is
    service.record_result("Enshrouded", True, protocol="source")
    assert service.is_supported("Enshrouded") is True


def test_a_container_that_never_answered_is_not_asked_again(tmp_path):
    """The counter-case: an ordinary app must not cost a probe every 30 minutes."""
    from services.infrastructure import game_query_support_service as mod
    service = mod.GameQuerySupportService(path=tmp_path / "query_support.json")
    service.record_result("plex", False, now_wall=1000.0)
    service.record_result("plex", False, now_wall=1000.0 + mod.PROBE_WINDOW_SECONDS + 1)
    assert service.is_final("plex")
    assert not service.should_probe("plex", 10 ** 9)


# --- 2. a newer image ----------------------------------------------------------

REF = image_updates.parse_image_reference("lscr.io/linuxserver/plex:latest")


def test_the_running_images_digests_are_read():
    facts = facts_from_attrs(
        {"Config": {"Image": "lscr.io/linuxserver/plex:latest"}, "Image": "sha256:abc"},
        {"RepoDigests": ["lscr.io/linuxserver/plex@sha256:old", "other/repo@sha256:else"]})
    assert facts.running_digests == frozenset({"sha256:old"})


def test_the_registry_is_asked_once_per_six_hours(monkeypatch):
    asked = []

    async def _remote(ref, *args, **kwargs):
        asked.append(ref)
        return "sha256:new"
    monkeypatch.setattr(image_updates, "remote_digest", _remote)
    monkeypatch.setattr(image_updates, "_REMOTE_CACHE", {})

    async def _twice():
        return [await image_updates.cached_remote_digest(REF, 1.0) for _ in range(2)]
    assert asyncio.run(_twice()) == ["sha256:new", "sha256:new"]
    assert len(asked) == 1, "every opening asked the registry"


def test_a_slow_registry_is_known_next_time(monkeypatch):
    async def _slow(ref, *args, **kwargs):
        await asyncio.sleep(0.2)
        return "sha256:new"
    monkeypatch.setattr(image_updates, "remote_digest", _slow)
    monkeypatch.setattr(image_updates, "_REMOTE_CACHE", {})

    async def _open_twice():
        first = await image_updates.cached_remote_digest(REF, 0.05)
        await asyncio.sleep(0.3)
        return first, await image_updates.cached_remote_digest(REF, 0.05)
    assert asyncio.run(_open_twice()) == (None, "sha256:new")


def test_the_update_line_needs_a_known_newer_image_and_the_details():
    facts = ContainerFacts(running=True, version="1.43.4", image_created=datetime(2026, 9, 21, tzinfo=timezone.utc))
    assert any("newer image" in line for line in info_extras.format_facts(facts, details=True, update=True))
    for details, update in ((False, True), (True, False), (True, None)):
        assert not any("newer image" in line for line in info_extras.format_facts(facts, details, update))


def test_an_unknown_remote_is_not_an_update(monkeypatch):
    async def _unknown(ref, wait):
        return None
    monkeypatch.setattr(image_updates, "cached_remote_digest", _unknown)
    facts = ContainerFacts(image_reference="lscr.io/linuxserver/plex:latest", running_digests=frozenset({"sha256:old"}))
    assert asyncio.run(info_extras.image_update(facts, 1.0)) is None


# --- 3. who joins -------------------------------------------------------------

VALHEIM = {"Valheim": {"docker_name": "Valheim", "name": "Valheim", "query_enabled": True}}


def _run(watcher, counts, answers, servers=VALHEIM):
    """One cycle. answers: name -> PlayerList (or None / a failed one)."""
    async def _players(cfg):
        return answers[cfg["docker_name"]]

    async def _cycle():
        original = info_extras.player_list
        info_extras.player_list = _players
        try:
            return await watcher.check(None, [1], counts, servers)
        finally:
            info_extras.player_list = original
    return asyncio.run(_cycle())


def _named(*names, max_players=10):
    return PlayerList(success=True, players_online=len(names), max_players=max_players,
                      names=[(n, 60.0) for n in names])


def test_the_first_look_only_remembers():
    watcher = player_joins.JoinWatcher()
    assert _run(watcher, {"Valheim": 2}, {"Valheim": _named("Anna", "Bob")}) == []


def test_a_named_join_is_announced_by_name():
    watcher = player_joins.JoinWatcher()
    _run(watcher, {"Valheim": 0}, {})
    notices = _run(watcher, {"Valheim": 1}, {"Valheim": _named("An*na")})
    assert notices == ["👋 **An\\*na** joined **Valheim** (1/10)"]
    assert _run(watcher, {"Valheim": 1}, {"Valheim": _named("An*na")}) == [], "announced twice"


def test_a_game_without_names_is_announced_by_count():
    watcher = player_joins.JoinWatcher()
    icarus = {"Icarus": {"docker_name": "Icarus", "name": "Icarus", "query_enabled": True}}
    silent = lambda n: PlayerList(success=True, players_online=n, max_players=8, names_given=False)
    _run(watcher, {"Icarus": 1}, {"Icarus": silent(1)}, icarus)
    assert _run(watcher, {"Icarus": 2}, {"Icarus": silent(2)}, icarus) == ["👋 A player joined **Icarus** (2/8)"]
    assert _run(watcher, {"Icarus": 4}, {"Icarus": silent(4)}, icarus) == ["👋 2 players joined **Icarus** (4/8)"]


def test_a_minecraft_sample_is_not_compared_by_name():
    """Fifteen online, a different twelve each time: nobody joined."""
    watcher = player_joins.JoinWatcher()
    mc = {"MC": {"docker_name": "MC", "name": "Minecraft", "query_enabled": True}}
    sample = lambda start: PlayerList(success=True, players_online=15, max_players=20,
                                      names=[(f"p{i}", None) for i in range(start, start + 12)])
    _run(watcher, {"MC": 15}, {"MC": sample(0)}, mc)
    assert _run(watcher, {"MC": 15}, {"MC": sample(3)}, mc) == []


def test_a_failed_query_keeps_what_was_seen():
    """Forgetting on a hiccup would make the next cycle a first look again -
    which announces nobody, so whoever joined right then was swallowed."""
    watcher = player_joins.JoinWatcher()
    _run(watcher, {"Valheim": 1}, {"Valheim": _named("Anna")})
    assert _run(watcher, {"Valheim": 1}, {"Valheim": PlayerList(success=False)}) == []
    assert _run(watcher, {"Valheim": 2}, {"Valheim": _named("Anna", "Bob")}) == \
        ["👋 **Bob** joined **Valheim** (2/10)"], "the join after a failed query was swallowed"


def test_nothing_runs_while_no_channel_asks():
    cog = SimpleNamespace(config={"channel_permissions": {"123456789012345678": {"commands": {}}}}, bot=None)
    cog.__dict__["_join_watcher"] = watcher = player_joins.JoinWatcher()
    watcher.known["Valheim"] = player_joins.Seen(count=1)
    player_joins.schedule_join_check(cog, {}, VALHEIM)
    assert watcher.task is None and watcher.known == {}


def test_the_notice_reaches_every_ticked_channel_and_goes_again():
    sent = []

    class _Channel:
        def __init__(self, cid):
            self.cid = cid

        async def send(self, text, delete_after=None):
            sent.append((self.cid, text, delete_after))
    bot = SimpleNamespace(get_channel=lambda cid: _Channel(cid))
    config = {"channel_permissions": {"111111111111111111": {"player_joins": True},
                                      "222222222222222222": {"player_joins": False},
                                      "333333333333333333": {"player_joins": True}}}
    ids = player_joins.join_channel_ids(config)
    asyncio.run(player_joins._post(bot, ids, "👋 hi"))
    assert sorted(cid for cid, _, _ in sent) == [111111111111111111, 333333333333333333]
    assert all(stay == player_joins.JOIN_NOTICE_STAYS_FOR for _, _, stay in sent)


def test_the_box_is_in_both_tables_and_saved():
    from services.config.config_form_parser_service import ConfigFormParserService
    parsed = ConfigFormParserService.parse_channel_permissions_from_form({
        "status_channel_id_1": "111111111111111111", "status_player_joins_1": "1",
        "control_channel_id_1": "222222222222222222"})
    assert parsed["111111111111111111"]["player_joins"] is True
    assert parsed["222222222222222222"]["player_joins"] is False
    html = (ROOT / "app" / "templates" / "_permissions_table.html").read_text(encoding="utf-8")
    js = (ROOT / "app" / "static" / "js" / "config-ui.js").read_text(encoding="utf-8")
    for prefix in ("status", "control"):
        assert html.count(f'name="{prefix}_player_joins_') == 2, prefix  # saved rows and the empty first row
        assert f'name="{prefix}_player_joins_${{rowCount}}"' in js, prefix
