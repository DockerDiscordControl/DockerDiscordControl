# -*- coding: utf-8 -*-
"""
THE FINDING (review C34, section 36 F5): `StructuredLogger.process` merges the
wrong way round and edits the caller's dictionary while doing it.

    extra = kwargs.get('extra', {})
    extra.update(self.extra)
    kwargs['extra'] = extra

`self.extra` is the adapter's FIXED context - the same values on every line.
Applying it last means it wins over whatever this one call said. A logger built
with `context={'donor': 'unknown'}` and then called as
`logger.info(msg, extra={'donor': 'Jane'})` logs `donor='unknown'`: the specific
value loses to the general one, silently.

The second half is live no matter what the keys are: `extra.update(...)` writes
into the dictionary the CALLER passed in. A caller that keeps that dict around -
to log twice, or to return it - finds the adapter's context added to it.

This one is not a trap in switched-off code. `services/donation/unified/service.py`
builds a structured logger and logs `donation_processed` with a dict of donor,
amount, source and event id on every successful donation.

The counter-check (test_the_context_still_reaches_the_record) keeps the point
of the adapter: what the call does NOT say still comes from the context.
"""

import logging

import pytest

from utils.observability import StructuredLogger


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


@pytest.fixture
def captured():
    logger = logging.getLogger("ddc.spec.c34")
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = _Capture()
    logger.addHandler(handler)
    yield logger, handler.records
    logger.handlers.clear()
    logging.root.manager.loggerDict.pop("ddc.spec.c34", None)


def test_the_call_wins_over_the_adapters_context(captured):
    """THE FINDING: the specific value must beat the general one."""
    logger, records = captured
    structured = StructuredLogger(logger, {"donor": "unknown", "service": "donations"})

    structured.info("donation_processed", extra={"donor": "Jane"})

    assert records[0].donor == "Jane"


def test_the_callers_dictionary_is_left_alone(captured):
    """The caller's own dict must come back the way it went in."""
    logger, _records = captured
    structured = StructuredLogger(logger, {"service": "donations"})
    fields = {"donor": "Jane", "amount": 5.0}

    structured.info("donation_processed", extra=fields)

    assert fields == {"donor": "Jane", "amount": 5.0}


def test_the_context_still_reaches_the_record(captured):
    """COUNTER-CHECK: the adapter is still an adapter - what the call does not
    say comes from the context."""
    logger, records = captured
    structured = StructuredLogger(logger, {"service": "donations", "component": "processor"})

    structured.info("donation_processed", extra={"donor": "Jane"})

    record = records[0]
    assert record.service == "donations"
    assert record.component == "processor"
    assert record.donor == "Jane"
