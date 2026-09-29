# -*- coding: utf-8 -*-
"""The status poll's 45-second timeout cap says that it is fixed.

THE FINDING (stage 4 review before v3.1.0, section 17 pass 4 F8): the
adaptive/emergency timeout cap of the status polls is a literal 45 s, but
its comment said the values "come from DDC_FAST_STATS_TIMEOUT and
DDC_FAST_INFO_TIMEOUT", and the start-up log said "aligned with Docker
timeouts" - an operator who raised those settings read that the polls
follow them. They do not.

THE OPERATOR (2026-09-29): the cap stays fixed at 45 s, so that it cannot
be set too small by accident; only the comment and the log are corrected.

HOW THIS TEST CAN FAIL: the log claims the settings again, or the cap moves.

COUNTER-CHECK (2026-09-29): red before the change (the log said "aligned").
"""

import logging

from services.docker_status.performance_service import PerformanceProfileService


def test_the_log_names_the_fixed_cap(caplog):
    with caplog.at_level(logging.INFO):
        service = PerformanceProfileService()
    assert service._config.max_timeout == 45000
    lines = " ".join(r.getMessage() for r in caplog.records if "timeout" in r.getMessage().lower())
    assert "aligned with Docker" not in lines, f"the log claims the Docker settings: {lines}"
    assert "fixed" in lines and "45" in lines, f"the log does not say the cap is fixed: {lines}"
