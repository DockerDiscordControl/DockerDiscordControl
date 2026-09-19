#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Unit tests for cogs/autocomplete_handlers.py (was 16.8% covered).

These functions run on every keystroke in a Discord slash command, and Discord
silently drops a response with more than 25 choices - so the cap is not cosmetic,
it decides whether the user sees any suggestions at all.

Covered here are the pure helpers and the two selectors that need no Docker or
config state: action and cycle selection.
"""

import time
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

import cogs.autocomplete_handlers as ac
import cogs.translation_manager as translation_manager
import services.scheduling.scheduler as scheduler_module
from cogs.autocomplete_handlers import (
    _filter_choices,
    _get_days_of_month,
    _get_time_suggestions,
    schedule_action_select,
    schedule_cycle_select,
    schedule_info_period_select,
    schedule_month_select,
    schedule_task_id_select,
    schedule_weekday_select,
    schedule_year_select,
)
from services.scheduling.scheduler import CYCLE_ONCE, VALID_ACTIONS, VALID_CYCLES

DISCORD_CHOICE_LIMIT = 25


def _ctx(value):
    """Stand-in for discord.AutocompleteContext: the handlers only read .value."""
    ctx = MagicMock()
    ctx.value = value
    return ctx


# ---------------------------------------------------------------------------
# _filter_choices
# ---------------------------------------------------------------------------

class TestFilterChoices:
    def test_empty_input_returns_the_first_25(self):
        choices = [f"item-{i:03d}" for i in range(100)]
        result = _filter_choices("", choices)
        assert result == choices[:DISCORD_CHOICE_LIMIT]

    def test_result_is_never_longer_than_the_discord_limit(self):
        """More than 25 choices makes Discord discard the whole response."""
        choices = [f"server-{i:03d}" for i in range(100)]
        assert len(_filter_choices("server", choices)) == DISCORD_CHOICE_LIMIT

    def test_matching_is_a_case_insensitive_substring(self):
        choices = ["Minecraft", "valheim", "TeamSpeak"]
        assert _filter_choices("CRAFT", choices) == ["Minecraft"]
        assert _filter_choices("team", choices) == ["TeamSpeak"]

    def test_match_anywhere_not_only_at_the_start(self):
        assert _filter_choices("heim", ["valheim"]) == ["valheim"]

    def test_no_match_returns_an_empty_list(self):
        assert _filter_choices("zzz", ["alpha", "beta"]) == []

    def test_empty_choice_list_is_handled(self):
        assert _filter_choices("anything", []) == []
        assert _filter_choices("", []) == []

    def test_order_of_the_input_is_preserved(self):
        choices = ["b-server", "a-server", "c-server"]
        assert _filter_choices("server", choices) == choices


# ---------------------------------------------------------------------------
# Time and day suggestions
# ---------------------------------------------------------------------------

class TestTimeSuggestions:
    def test_covers_every_full_hour_and_quarter(self):
        suggestions = _get_time_suggestions()
        # 24 full hours + 24 * 3 quarter-hour entries
        assert len(suggestions) == 24 + 24 * 3

    def test_sorted_and_zero_padded(self):
        suggestions = _get_time_suggestions()
        assert suggestions == sorted(suggestions)
        assert suggestions[0] == "00:00"
        assert suggestions[-1] == "23:45"

    def test_every_entry_is_a_valid_clock_time(self):
        for entry in _get_time_suggestions():
            hours, minutes = entry.split(":")
            assert len(hours) == 2 and len(minutes) == 2
            assert 0 <= int(hours) <= 23
            assert int(minutes) in (0, 15, 30, 45)

    def test_no_duplicates(self):
        suggestions = _get_time_suggestions()
        assert len(set(suggestions)) == len(suggestions)

    def test_result_is_cached(self):
        """Decorated with lru_cache; it is rebuilt on every keystroke otherwise."""
        assert _get_time_suggestions() is _get_time_suggestions()


class TestDaysOfMonth:
    def test_covers_1_to_31_zero_padded(self):
        days = _get_days_of_month()
        assert len(days) == 31
        assert days[0] == "01"
        assert days[-1] == "31"

    def test_all_entries_are_two_digits(self):
        assert all(len(d) == 2 and d.isdigit() for d in _get_days_of_month())


# ---------------------------------------------------------------------------
# Action and cycle selectors
# ---------------------------------------------------------------------------

class TestActionSelect:
    async def test_empty_input_offers_all_valid_actions(self):
        result = await schedule_action_select(_ctx(""))
        assert sorted(result) == sorted(VALID_ACTIONS)

    async def test_typing_narrows_the_list(self):
        result = await schedule_action_select(_ctx("st"))
        assert result, "expected at least one action containing 'st'"
        assert all("st" in action.lower() for action in result)

    async def test_only_scheduleable_actions_are_offered(self):
        """Never offer an action the scheduler cannot execute."""
        result = await schedule_action_select(_ctx(""))
        assert set(result) <= set(VALID_ACTIONS)

    async def test_unknown_input_yields_nothing(self):
        assert await schedule_action_select(_ctx("teleport")) == []


class TestCycleSelect:
    async def test_empty_input_offers_all_valid_cycles(self):
        result = await schedule_cycle_select(_ctx(""))
        assert sorted(result) == sorted(VALID_CYCLES)

    async def test_typing_narrows_the_list(self):
        result = await schedule_cycle_select(_ctx("dai"))
        assert all("dai" in cycle.lower() for cycle in result)

    @pytest.mark.parametrize("cycle", sorted(VALID_CYCLES))
    async def test_every_cycle_can_be_found_by_typing_it(self, cycle):
        """A user typing the exact cycle name must see it offered."""
        assert cycle in await schedule_cycle_select(_ctx(cycle))


# ---------------------------------------------------------------------------
# Year selection
# ---------------------------------------------------------------------------

class TestYearSelect:
    async def test_offers_the_current_year_and_the_next_five(self):
        current = datetime.now(timezone.utc).year
        result = await schedule_year_select(_ctx(""))
        assert result == [str(current + i) for i in range(6)]

    async def test_typing_narrows_to_matching_years(self):
        current = datetime.now(timezone.utc).year
        result = await schedule_year_select(_ctx(str(current)))
        assert result == [str(current)]

    async def test_past_years_are_not_offered(self):
        """Scheduling into the past is pointless, so it must not be suggested."""
        last_year = str(datetime.now(timezone.utc).year - 1)
        assert last_year not in await schedule_year_select(_ctx(""))


# ---------------------------------------------------------------------------
# Weekday and period selection (both match English *and* translated text,
# but always return the English value the parser understands)
# ---------------------------------------------------------------------------

@pytest.fixture
def german_translations(monkeypatch):
    """Patch the translation helper the handlers import at call time."""
    table = {
        "Monday": "Montag", "Tuesday": "Dienstag", "Wednesday": "Mittwoch",
        "Thursday": "Donnerstag", "Friday": "Freitag", "Saturday": "Samstag",
        "Sunday": "Sonntag",
        "today": "heute", "tomorrow": "morgen", "all": "alle",  # language data
        "next_week": "nächste_woche", "next_month": "nächster_monat",
    }
    monkeypatch.setattr(translation_manager, "_", lambda text: table.get(text, text))
    return table


class TestWeekdaySelect:
    async def test_empty_input_offers_all_seven_days(self, german_translations):
        result = await schedule_weekday_select(_ctx(""))
        assert result == ["Monday", "Tuesday", "Wednesday", "Thursday",
                          "Friday", "Saturday", "Sunday"]

    async def test_english_input_narrows(self, german_translations):
        assert await schedule_weekday_select(_ctx("mon")) == ["Monday"]

    async def test_translated_input_still_returns_the_english_value(self, german_translations):
        """The scheduler only understands English weekdays, so the value must stay English."""
        assert await schedule_weekday_select(_ctx("dienstag")) == ["Tuesday"]

    async def test_unknown_input_yields_nothing(self, german_translations):
        assert await schedule_weekday_select(_ctx("caturday")) == []


class TestInfoPeriodSelect:
    async def test_empty_input_offers_every_period(self, german_translations):
        result = await schedule_info_period_select(_ctx(""))
        assert result == ["all", "next_week", "next_month", "today", "tomorrow"]

    async def test_english_input_narrows(self, german_translations):
        assert await schedule_info_period_select(_ctx("tomo")) == ["tomorrow"]

    async def test_translated_input_returns_the_english_value(self, german_translations):
        assert await schedule_info_period_select(_ctx("heute")) == ["today"]


# ---------------------------------------------------------------------------
# Month selection
# ---------------------------------------------------------------------------

@pytest.fixture
def month_config(monkeypatch, german_translations):
    monkeypatch.setattr(ac, "load_config", lambda: {"language": "de"})


class TestMonthSelect:
    async def test_empty_input_offers_twelve_sorted_months(self, month_config):
        result = await schedule_month_select(_ctx(""))
        assert result == [f"{m:02d}" for m in range(1, 13)]

    async def test_typing_a_month_name_narrows(self, month_config):
        assert await schedule_month_select(_ctx("March")) == ["03"]

    async def test_typing_a_padded_number_matches(self, month_config):
        assert "07" in await schedule_month_select(_ctx("07"))

    async def test_typing_a_single_digit_is_padded(self, month_config):
        """Users type "3", not "03"."""
        assert "03" in await schedule_month_select(_ctx("3"))

    async def test_number_outside_1_to_12_is_not_offered(self, month_config):
        assert await schedule_month_select(_ctx("13")) == []


# ---------------------------------------------------------------------------
# Task id selection for /schedule_delete
# ---------------------------------------------------------------------------

def _task(task_id="t1", container="alpha", action="restart", cycle="daily",
          is_active=True, next_run_ts=None, status=None):
    task = MagicMock()
    task.task_id = task_id
    task.container_name = container
    task.action = action
    task.cycle = cycle
    task.is_active = is_active
    task.next_run_ts = next_run_ts if next_run_ts is not None else time.time() + 3600
    task.status = status
    return task


@pytest.fixture
def tasks(monkeypatch):
    """Patch load_tasks where the handler imports it from."""
    holder = {"tasks": []}
    monkeypatch.setattr(scheduler_module, "load_tasks", lambda: holder["tasks"])
    return holder


class TestTaskIdSelect:
    async def test_no_tasks_yields_nothing(self, tasks):
        assert await schedule_task_id_select(_ctx("")) == []

    async def test_active_task_is_offered(self, tasks):
        tasks["tasks"] = [_task(task_id="abc123")]
        assert await schedule_task_id_select(_ctx("")) == ["abc123"]

    async def test_inactive_task_is_skipped(self, tasks):
        """Deleting an already paused task via autocomplete would be confusing."""
        tasks["tasks"] = [_task(is_active=False)]
        assert await schedule_task_id_select(_ctx("")) == []

    async def test_expired_one_time_task_is_skipped(self, tasks):
        tasks["tasks"] = [_task(cycle=CYCLE_ONCE, next_run_ts=time.time() - 60)]
        assert await schedule_task_id_select(_ctx("")) == []

    async def test_one_time_task_without_a_run_time_is_skipped(self, tasks):
        tasks["tasks"] = [_task(cycle=CYCLE_ONCE, next_run_ts=None)]
        # _task() replaces None with a future timestamp, so set it explicitly here
        tasks["tasks"][0].next_run_ts = None
        assert await schedule_task_id_select(_ctx("")) == []

    async def test_completed_one_time_task_is_skipped(self, tasks):
        tasks["tasks"] = [_task(cycle=CYCLE_ONCE, status="completed")]
        assert await schedule_task_id_select(_ctx("")) == []

    async def test_future_one_time_task_is_offered(self, tasks):
        tasks["tasks"] = [_task(task_id="once1", cycle=CYCLE_ONCE)]
        assert await schedule_task_id_select(_ctx("")) == ["once1"]

    async def test_typing_the_container_name_matches_via_the_display_text(self, tasks):
        tasks["tasks"] = [_task(task_id="t1", container="minecraft"),
                          _task(task_id="t2", container="valheim")]
        assert await schedule_task_id_select(_ctx("valheim")) == ["t2"]

    async def test_typing_the_action_matches(self, tasks):
        tasks["tasks"] = [_task(task_id="t1", action="restart"),
                          _task(task_id="t2", action="stop")]
        assert await schedule_task_id_select(_ctx("stop")) == ["t2"]

    async def test_result_respects_the_discord_limit(self, tasks):
        tasks["tasks"] = [_task(task_id=f"task{i:03d}") for i in range(40)]
        assert len(await schedule_task_id_select(_ctx(""))) == DISCORD_CHOICE_LIMIT

    async def test_a_failing_task_load_returns_no_choices(self, tasks, monkeypatch):
        """Autocomplete must never raise into Discord's callback."""
        def boom():
            raise RuntimeError("tasks file unreadable")

        monkeypatch.setattr(scheduler_module, "load_tasks", boom)
        assert await schedule_task_id_select(_ctx("")) == []
