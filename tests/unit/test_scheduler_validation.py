from utils.scheduler import ScheduledTask, CYCLE_DAILY, CYCLE_WEEKLY, CYCLE_MONTHLY, CYCLE_ONCE, CYCLE_YEARLY


def test_scheduled_task_basic_validation():
    # Missing fields
    assert ScheduledTask(container_name=None, action="start", cycle=CYCLE_DAILY, hour=10, minute=0).is_valid() is False
    assert ScheduledTask(container_name="abc", action="noop", cycle=CYCLE_DAILY, hour=10, minute=0).is_valid() is False

    # Valid daily
    assert ScheduledTask(container_name="abc", action="start", cycle=CYCLE_DAILY, hour=10, minute=0).is_valid() is True


def test_scheduled_task_weekly_validation():
    # Weekly with weekday number
    t = ScheduledTask(container_name="abc", action="start", cycle=CYCLE_WEEKLY, hour=10, minute=0, weekday=2)
    assert t.is_valid() is True

    # Weekly with weekday name
    t2 = ScheduledTask(container_name="abc", action="start", cycle=CYCLE_WEEKLY, hour=10, minute=0, schedule_details={"day": "monday", "time": "10:00"})
    assert t2.is_valid() is True


def test_scheduled_task_monthly_validation():
    # Valid monthly day
    t = ScheduledTask(container_name="abc", action="restart", cycle=CYCLE_MONTHLY, hour=10, minute=0, schedule_details={"day": 15, "time": "10:00"})
    assert t.is_valid() is True

    # Invalid day
    t2 = ScheduledTask(container_name="abc", action="restart", cycle=CYCLE_MONTHLY, hour=10, minute=0, schedule_details={"day": 0})
    assert t2.is_valid() is False


def test_scheduled_task_once_and_yearly_validation():
    # Once needs full date
    t_once_bad = ScheduledTask(container_name="abc", action="stop", cycle=CYCLE_ONCE, hour=10, minute=0)
    assert t_once_bad.is_valid() is False

    t_once = ScheduledTask(container_name="abc", action="stop", cycle=CYCLE_ONCE, hour=10, minute=0, year=2030, month=12, day=31)
    assert t_once.is_valid() is True

    # Yearly needs month and day
    t_yearly_bad = ScheduledTask(container_name="abc", action="stop", cycle=CYCLE_YEARLY, hour=10, minute=0)
    assert t_yearly_bad.is_valid() is False

    t_yearly = ScheduledTask(container_name="abc", action="stop", cycle=CYCLE_YEARLY, hour=10, minute=0, schedule_details={"month": 12, "day": 31, "time": "10:00"})
    assert t_yearly.is_valid() is True


