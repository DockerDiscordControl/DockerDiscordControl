# -*- coding: utf-8 -*-
"""CPU or RAM above a threshold for a while is reported once, with hysteresis (Phase 4b).

The same watchdog path as a stopped container: a condition, one message, the
same rules. The rules the resource watcher keeps, each checked below:

* above the threshold for the whole duration -> "high_cpu" / "high_memory", once;
* a spike shorter than the duration -> nothing;
* while it stays high -> nothing more;
* it re-arms only after dropping below the threshold minus the hysteresis
  margin - a value hovering at the line does not report every minute;
* no measurement (None, e.g. a stopped container) resets the timer.

COUNTER-CHECK (2026-09-22): written before the watcher existed; then the
hysteresis margin was set to zero and the "hovering" test went red.
"""

import pytest

from services.automation.container_watch import ResourceWatcher


@pytest.fixture
def cpu():
    return ResourceWatcher(metric="cpu", threshold_percent=80, minutes=5, hysteresis_percent=10)


def test_high_for_the_whole_duration_is_reported_once(cpu):
    assert cpu.observe({"web": 90}, now=0) == []
    assert cpu.observe({"web": 95}, now=240) == []
    events = cpu.observe({"web": 91}, now=300)
    assert [(e.container, e.kind) for e in events] == [("web", "high_cpu")]
    assert "web" in events[0].reason and "80" in events[0].reason and "5 min" in events[0].reason
    assert (events[0].threshold, events[0].window_minutes) == (80, 5)
    assert cpu.observe({"web": 99}, now=600) == []


def test_a_short_spike_is_nothing(cpu):
    cpu.observe({"web": 95}, now=0)
    cpu.observe({"web": 20}, now=120)
    assert cpu.observe({"web": 95}, now=300) == []


def test_hovering_at_the_line_does_not_report_every_minute(cpu):
    cpu.observe({"web": 90}, now=0)
    assert len(cpu.observe({"web": 90}, now=300)) == 1
    # A dip just under 80 but not under 70 (80 minus the 10-point margin), then
    # high again for longer than the duration: still the same episode, no second
    # message. (The first version of this test never stayed high long enough
    # after a dip, and passed with the margin set to zero.)
    assert cpu.observe({"web": 78}, now=360) == []
    for step in range(1, 8):
        assert cpu.observe({"web": 90}, now=360 + step * 60) == []
    # a real drop re-arms, and a new sustained high is a new event
    cpu.observe({"web": 50}, now=800)
    cpu.observe({"web": 90}, now=860)
    assert len(cpu.observe({"web": 92}, now=1160)) == 1


def test_no_measurement_resets_the_timer(cpu):
    cpu.observe({"web": 95}, now=0)
    cpu.observe({"web": None}, now=120)
    assert cpu.observe({"web": 95}, now=300) == []


def test_memory_has_its_own_kind():
    ram = ResourceWatcher(metric="memory", threshold_percent=90, minutes=1, hysteresis_percent=5)
    ram.observe({"db": 95}, now=0)
    assert [e.kind for e in ram.observe({"db": 96}, now=60)] == ["high_memory"]
