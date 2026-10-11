# -*- coding: utf-8 -*-
"""The monthly donation appeal says in the log where it went.

THE FINDING (operator, 2026-10-11, the first appeal of v3.1: "nothing came
in"): the task ran at 13:37 and the log showed only the scheduler's
"completed successfully". donation_message_service used a plain
logging.getLogger('ddc.donation_message_service'), which inherits WARNING from
the root, so its INFO lines ("Donation message sent to N channels") were
dropped and nobody could tell whether the appeal reached a channel.

THE CONTRACT: the module's logger lets INFO through, so "sent to N channels"
reaches the log.

HOW THIS TEST CAN FAIL: the module back on a logger that drops INFO.

COUNTER-CHECK (2026-10-11): red with the plain getLogger put back.
"""

import logging


def test_the_appeal_logs_at_info():
    import services.scheduling.donation_message_service as service

    assert service.logger.getEffectiveLevel() <= logging.INFO
    assert service.logger.handlers or service.logger.propagate and logging.getLogger("ddc").handlers, \
        "INFO lines of the appeal go nowhere"
