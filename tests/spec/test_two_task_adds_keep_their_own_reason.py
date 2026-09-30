# -*- coding: utf-8 -*-
"""Two task adds at the same moment keep their own refusal reason.

THE FINDING (stage 4 review before v3.1.0, section 31 pass 4 F5): the
reason an unreadable cron string was refused lived on the shared service
instance (self.cron_error), and waitress serves requests on several
threads. A second add_task running between the reason being set and read
cleared it, and the first refusal fell back to the generic "Task
validation failed". The route logs result.error, so the logged reason
was wrong or missing.

THE CONTRACT: the reason is kept per call.

HOW THIS TEST CAN FAIL: the second call's reset reaches the first again.
It plays the second request inside the first one, from the log line
written between setting the reason and reading it.

COUNTER-CHECK (2026-09-30): red before the change (the generic message).
"""

from services.web.task_management_service import AddTaskRequest, TaskManagementService


def test_a_second_add_does_not_clear_the_first_reason(monkeypatch):
    service = TaskManagementService()
    monkeypatch.setattr(service, "_save_task_via_scheduler", lambda task: {"success": True})
    monkeypatch.setattr(service, "_log_task_creation", lambda task: None)
    monkeypatch.setattr(service, "_determine_timezone", lambda tz: "UTC")

    other = []
    real_error = service.logger.error

    def error_with_a_second_request_meanwhile(message, *args, **kwargs):
        # Logged right after the reason is set and before add_task reads it
        if "*/5 * * *" in str(message) and not other:
            other.append(None)
            other[0] = service.add_task(AddTaskRequest(
                container="nginx", action="restart", cycle="daily",
                schedule_details={"time": "04:00"}))
        return real_error(message, *args, **kwargs)
    monkeypatch.setattr(service.logger, "error", error_with_a_second_request_meanwhile)

    result = service.add_task(AddTaskRequest(container="nginx", action="restart", cycle="cron",
                                             schedule_details={"cron_string": "*/5 * * *"}))

    assert other and other[0].success, "the second request did not run - the test proves nothing"
    assert result.success is False
    assert "*/5 * * *" in (result.error or ""), f"the reason was lost: {result.error!r}"
