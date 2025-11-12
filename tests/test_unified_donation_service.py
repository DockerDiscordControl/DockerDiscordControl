from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.donation.unified import models, validation
from services.donation.unified import reset as reset_module
from services.donation.unified import service as service_module
from services.mech.progress_paths import ProgressPaths


class FakeState(SimpleNamespace):
    pass


class FakeMechService:
    def __init__(self):
        self.state = FakeState(level=1, Power=100)

    def get_state(self):
        return self.state

    def add_donation(self, amount, donor, channel_id=None):  # noqa: ARG002
        self.state = FakeState(level=self.state.level + 1, Power=self.state.Power + amount)
        return self.state

    async def add_donation_async(self, **kwargs):
        return self.add_donation(kwargs["amount"], kwargs["donor"], kwargs.get("channel_id"))


class FakeEventManager:
    def __init__(self):
        self.events = []

    def emit_event(self, **payload):  # noqa: D401
        self.events.append(payload)


@pytest.fixture(autouse=True)
def clear_singleton():
    service_module._unified_donation_service = None
    yield
    service_module._unified_donation_service = None


def test_validate_request_rejects_invalid_amount():
    request = models.DonationRequest(donor_name="Test", amount=0, source="web")

    with pytest.raises(validation.DonationValidationError):
        validation.validate_request(request)


def test_process_donation_emits_event(monkeypatch):
    fake_mech = FakeMechService()
    fake_events = FakeEventManager()

    monkeypatch.setattr(service_module, "get_mech_service", lambda: fake_mech, raising=False)
    monkeypatch.setattr(service_module, "get_event_manager", lambda: fake_events, raising=False)
    monkeypatch.setattr(service_module, "clear_mech_cache", lambda: None, raising=False)

    service = service_module.UnifiedDonationService()
    request = models.DonationRequest(donor_name="Tester", amount=5, source="web")

    result = service.process_donation(request)

    assert result.success
    assert result.event_emitted
    assert fake_events.events, "expected an emitted event"
    payload = fake_events.events[0]
    assert payload["event_type"] == "donation_completed"


@pytest.mark.asyncio
async def test_process_donation_async_uses_member_context(monkeypatch):
    fake_mech = FakeMechService()
    fake_events = FakeEventManager()

    monkeypatch.setattr(service_module, "get_mech_service", lambda: fake_mech, raising=False)
    monkeypatch.setattr(service_module, "get_event_manager", lambda: fake_events, raising=False)
    monkeypatch.setattr(service_module, "clear_mech_cache", lambda: None, raising=False)
    async def fake_resolve(*args, **kwargs):  # noqa: ARG001
        return object(), 42

    monkeypatch.setattr(service_module, "resolve_member_context", fake_resolve, raising=False)

    service = service_module.UnifiedDonationService()
    request = models.DonationRequest(
        donor_name="AsyncTester",
        amount=7.5,
        source="discord",
        discord_guild_id="123",
        bot_instance=object(),
        use_member_count=True,
    )

    result = await service.process_donation_async(request)

    assert result.success
    assert result.event_emitted
    assert fake_events.events, "expected an emitted event"


def test_reset_donations_resets_files(monkeypatch, tmp_path):
    fake_mech = FakeMechService()
    fake_events = FakeEventManager()

    paths = ProgressPaths.from_base_dir(tmp_path / "progress")
    monkeypatch.setattr(reset_module, "clear_mech_cache", lambda: None, raising=False)

    result = reset_module.reset_donations(fake_mech, fake_events, source="test", paths=paths)

    assert result.success
    assert result.event_emitted
    assert fake_events.events, "expected reset event emission"

    snapshot = paths.snapshot_for("main")
    assert snapshot.exists()
    assert paths.event_log.exists()
    assert paths.seq_file.read_text(encoding="utf-8").strip() == "0"

