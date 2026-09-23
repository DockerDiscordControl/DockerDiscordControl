# -*- coding: utf-8 -*-
"""An auto-action rule the panel just saved is not lost when a rule fires.

THE FINDING (independent review of the web panel, 2026-09-23):
auto_actions.json is read, changed and written back in five places -
add_rule, update_rule, delete_rule, update_global_settings and
increment_trigger_count - and none of them held a lock. The write itself is
atomic; the CYCLE is not, which is exactly what utils/atomic_io says in its
own docstring.

    a rule fires  -> increment_trigger_count reads the file and holds the dict
    the operator  -> add_rule reads, appends the new rule, writes, answers
                     {"success": true}
    the firing    -> _save_config_file writes ITS copy, which never saw the
                     new rule

The panel says the rule was created. It is not on disk and it never runs. The
reverse order costs the trigger count instead, which nobody misses; this order
costs the operator's work.

Both sides run in ONE process - the bot's loop and a waitress worker thread -
so this is a thread race, not a process one. cross_process_lock covers both:
it opens a fresh descriptor each time, so flock serialises two threads as well
as two processes, and it also keeps out a `docker exec` or a host-side edit.

The author clearly knows this failure class: _load_config_file was hardened so
that nothing may write on top of a configuration it could not read. The
concurrent-writer half was missing.

HOW THIS TEST CAN FAIL: it starts a rule-firing write, holds it inside the
service, creates a rule from another thread, and then lets the first one
finish. If the new rule is not in the file afterwards, the test is red.

COUNTER-CHECK (2026-09-23): red before - the rule was gone and add_rule had
answered success. The last test keeps the other direction: the trigger count
must survive too.
"""

import json
import threading

import pytest

from services.automation.auto_action_config_service import AutoActionConfigService


@pytest.fixture
def service(tmp_path, monkeypatch):
    svc = AutoActionConfigService()
    svc.config_file = tmp_path / "auto_actions.json"
    svc.config_file.write_text(json.dumps({
        "auto_actions": [{
            "id": "old-rule",
            "name": "the rule that fires",
            "enabled": True,
            "metadata": {"trigger_count": 0},
        }],
        "global_settings": {},
    }), encoding="utf-8")
    return svc


def _rules_on_disk(service):
    return json.loads(service.config_file.read_text(encoding="utf-8"))["auto_actions"]


def _rule_data(name):
    return {
        "name": name,
        "enabled": True,
        "trigger": {"type": "container_state", "states": ["stopped"], "containers": ["nginx"]},
        "action": {"type": "RESTART", "containers": ["nginx"]},
    }


def test_a_rule_created_while_another_fires_survives(service):
    """THE FINDING: the firing wrote its own copy over the operator's rule."""
    inside = threading.Event()
    may_finish = threading.Event()
    real_save = service._save_config_file

    def slow_save(data):
        # Only the firing's write waits; the panel's own write must go through.
        if data["auto_actions"][0].get("metadata", {}).get("trigger_count") == 1 \
                and len(data["auto_actions"]) == 1:
            inside.set()
            may_finish.wait(5)
        return real_save(data)

    service._save_config_file = slow_save
    firing = threading.Thread(target=service.increment_trigger_count, args=("old-rule",))
    firing.start()
    assert inside.wait(5), "the firing never reached its write"

    def create():
        service._save_config_file = real_save
        return service.add_rule(_rule_data("the rule the operator just made"))

    result_box = []
    panel = threading.Thread(target=lambda: result_box.append(create()))
    panel.start()
    panel.join(10)
    may_finish.set()
    firing.join(10)

    assert result_box and result_box[0].success, "the panel could not create the rule at all"
    names = [rule["name"] for rule in _rules_on_disk(service)]
    assert "the rule the operator just made" in names, (
        f"the panel answered success and the rule is not on disk: {names}")


def test_the_trigger_count_is_not_lost_either(service):
    """Counter-check: the other order must not quietly drop the count."""
    service.increment_trigger_count("old-rule")
    service.add_rule(_rule_data("second"))

    rules = {rule["name"]: rule for rule in _rules_on_disk(service)}
    assert rules["the rule that fires"]["metadata"]["trigger_count"] == 1
    assert "second" in rules


def test_the_everyday_calls_still_work(service):
    """Counter-check: locking must not turn a normal call into a deadlock."""
    created = service.add_rule(_rule_data("plain"))
    assert created.success

    rules = service.get_rules()
    assert {rule.name for rule in rules} == {"the rule that fires", "plain"}

    assert service.update_global_settings({"enabled": False}).success
    rule_id = next(rule.id for rule in service.get_rules() if rule.name == "plain")
    assert service.delete_rule(rule_id).success
    assert {rule.name for rule in service.get_rules()} == {"the rule that fires"}
