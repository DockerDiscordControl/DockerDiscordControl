# -*- coding: utf-8 -*-
"""
THE FINDING (review C37, section 36 F9): a traced operation that fails is
exported as one that succeeded.

`TracingManager.trace` wraps the yielded span with

    except (RuntimeError) as e:
        span.set_status(Status(StatusCode.ERROR))
        span.record_exception(e)
        raise

Any other exception type leaves the block without the span being marked. The
operation correctly fails - the exception propagates - but the trace shows that
span as successful. `services/donation/unified/service.py` wraps the whole
donation in `tracing.trace("donation.process", ...)`, and the errors that can
come out of it are ValueError, KeyError and the DDC exception hierarchy, none
of which is a RuntimeError.

WHAT IS TRUE ABOUT THE REACH: the global `tracing` is constructed with
`enabled=False` and `enable_tracing()` is never called anywhere in the project.
So this branch does not run today - it is a trap that springs the moment
someone switches tracing on to find out why donations are failing, which is
precisely when a trace that says "fine" is most expensive.

The counter-check (test_a_span_that_succeeded_is_not_marked_failed) keeps the
marking from becoming unconditional.
"""

import pytest

from utils import observability as obs


class _Span:
    def __init__(self):
        self.status = None
        self.recorded = []
        self.attributes = {}

    def set_status(self, status):
        self.status = status

    def record_exception(self, exception):
        self.recorded.append(exception)

    def set_attribute(self, key, value):
        self.attributes[key] = value


class _Tracer:
    def __init__(self, span):
        self._span = span

    def start_as_current_span(self, name):
        span = self._span

        class _CM:
            def __enter__(self):
                return span

            def __exit__(self, *exc):
                return False

        return _CM()


@pytest.fixture
def traced(monkeypatch):
    """A manager that is switched on, with a span we can look at."""
    span = _Span()
    manager = obs.TracingManager.__new__(obs.TracingManager)
    manager.enabled = True
    manager.tracer = _Tracer(span)
    monkeypatch.setattr(obs, "Status", lambda code: ("status", code), raising=False)
    monkeypatch.setattr(obs, "StatusCode",
                        type("SC", (), {"ERROR": "ERROR", "OK": "OK"}), raising=False)
    return manager, span


@pytest.mark.parametrize("failure", [
    ValueError("bad amount"),
    KeyError("donor"),
    OSError("socket gone"),
])
def test_a_failing_span_is_marked_failed(traced, failure):
    """THE FINDING: not only RuntimeError ends an operation."""
    manager, span = traced

    with pytest.raises(type(failure)):
        with manager.trace("donation.process"):
            raise failure

    assert span.status is not None, "the trace shows this span as successful"
    assert span.recorded, "the exception was not recorded on the span"


def test_a_runtime_error_is_still_marked(traced):
    """What already worked keeps working."""
    manager, span = traced

    with pytest.raises(RuntimeError):
        with manager.trace("donation.process"):
            raise RuntimeError("boom")

    assert span.status is not None


def test_a_span_that_succeeded_is_not_marked_failed(traced):
    """COUNTER-CHECK: marking everything is not marking failures."""
    manager, span = traced

    with manager.trace("donation.process", attributes={"source": "web"}):
        pass

    assert span.status is None
    assert span.attributes == {"source": "web"}
