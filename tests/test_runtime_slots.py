from __future__ import annotations

import inspect

import pytest

from app.bot.runtime import BotRuntime
from services.donation.unified.models import DonationRequest, DonationResult
from services.docker_service.status_cache_runtime import DockerStatusCacheRuntime
from services.member_count.service import _ChannelPermissionsCache
from services.mech.progress.runtime import ProgressRuntime
from services.mech.progress_paths import ProgressPaths
from services.scheduling.runtime import _SchedulerRuntimeState


@pytest.mark.parametrize(
    "cls",
    [
        BotRuntime,
        DonationRequest,
        DonationResult,
        ProgressPaths,
        ProgressRuntime,
        DockerStatusCacheRuntime,
        _ChannelPermissionsCache,
        _SchedulerRuntimeState,
    ],
)
def test_dataclasses_use_slots(cls) -> None:
    assert hasattr(cls, "__slots__"), f"{cls.__name__} should define __slots__"

    # Slots should be a tuple/list of attribute names rather than a single string
    slots = cls.__slots__
    if isinstance(slots, str):
        pytest.fail(f"{cls.__name__}.__slots__ should not be a string")

    for slot in slots:
        assert isinstance(slot, str)
        assert slot.isidentifier()


def test_progress_runtime_is_still_mutable() -> None:
    runtime = ProgressRuntime()
    runtime.invalidate_cache()
    assert inspect.isdatadescriptor(ProgressRuntime.paths)
