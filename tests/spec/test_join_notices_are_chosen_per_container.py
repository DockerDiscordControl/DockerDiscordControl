# -*- coding: utf-8 -*-
"""Join notices are switched per container as well as per channel.

THE OPERATOR (2026-10-04): join notices should be settable per container,
in the web panel. The channel's "Player joins" box keeps deciding WHERE the
notices appear; the new setting in the container's info dialog decides FOR
WHICH game servers. It is on by default, so an installation that announces
today goes on doing so after the update.

THE CONTRACT:
- the info dialog's "announce player joins" box travels through the hidden
  field query_joins_<container> and is saved as announce_joins;
- a container saved before this setting existed (no field, no key) counts
  as on;
- the join check announces nothing for a container switched off, and still
  for one switched on.

HOW THIS TEST CAN FAIL: the setting is lost on save, a missing value reads
as off, or a switched-off container is announced.

COUNTER-CHECK (2026-10-04): red before the change (no field, every
container announced).
"""

from pathlib import Path

import pytest

from cogs import player_joins
from services.config.config_form_parser_service import ConfigFormParserService
from tests.spec.test_joins_updates_and_a_silent_server_are_said import VALHEIM, _named, _run

PROJECT = Path(__file__).resolve().parents[2]


def _saved(form_extra):
    form = {"selected_servers": ["Valheim"], "query_enabled_Valheim": "1", **form_extra}
    servers = ConfigFormParserService.parse_servers_from_form(form)
    return servers[0]


@pytest.mark.parametrize("sent, stored", [({"query_joins_Valheim": "0"}, False),
                                          ({"query_joins_Valheim": "1"}, True),
                                          ({}, True)])
def test_the_setting_is_saved(sent, stored):
    assert _saved(sent)["announce_joins"] is stored


def test_a_switched_off_container_is_not_announced():
    quiet = {"Valheim": dict(VALHEIM["Valheim"], announce_joins=False)}
    watcher = player_joins.JoinWatcher()
    _run(watcher, {"Valheim": 0}, {}, quiet)
    assert _run(watcher, {"Valheim": 1}, {"Valheim": _named("Anna")}, quiet) == []


def test_a_container_saved_before_the_setting_is_still_announced():
    watcher = player_joins.JoinWatcher()
    _run(watcher, {"Valheim": 0}, {})
    assert _run(watcher, {"Valheim": 1}, {"Valheim": _named("Anna")}) != []


def test_the_page_carries_the_field_and_the_box():
    template = (PROJECT / "app/templates/_server_selection.html").read_text(encoding="utf-8")
    assert 'name="query_joins_{{ container.name }}"' in template
    assert "server_config.get('announce_joins', True)" in template
    assert 'id="modal-query-joins"' in template
