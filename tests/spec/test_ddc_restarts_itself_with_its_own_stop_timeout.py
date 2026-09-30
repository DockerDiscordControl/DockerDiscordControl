# -*- coding: utf-8 -*-
"""DDC's restart of itself honours its container's StopTimeout.

THE FINDING (stage 4 review before v3.1.0, section 14 pass 4 F5): the
panel's self-restart called container.restart() without a timeout, so
docker-py sent t=10 and Docker killed DDC after ten seconds even when the
operator had given the DDC container a longer StopTimeout. Every other
stop/restart honours it through get_stop_timeout_kwargs.

THE CONTRACT: the self-restart passes the container's StopTimeout.

HOW THIS TEST CAN FAIL: restart() is called without it again.

COUNTER-CHECK (2026-09-30): red before the change.
"""

from types import SimpleNamespace

from services.docker_service import self_restart


def test_the_stop_timeout_is_passed(monkeypatch):
    monkeypatch.setenv("HOSTNAME", "abcdef123456")
    calls = []
    container = SimpleNamespace(name="dockerdiscordcontrol", attrs={"Config": {"StopTimeout": 60}},
                                restart=lambda **kw: calls.append(kw))
    client = SimpleNamespace(containers=SimpleNamespace(get=lambda cid: container))

    class _Now:
        def __init__(self, delay, function):
            self.function = function
            self.daemon = False

        def start(self):
            self.function()

    ok, _name = self_restart.restart_myself(client=client, delay=0, timer=_Now)

    assert ok and calls == [{"timeout": 60}], calls
