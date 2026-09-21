# -*- coding: utf-8 -*-
"""Changing a protected password must take effect at once, not at the next refresh.

THE FINDING (review E27, cogs/enhanced_info_modal_simple.py):
``PasswordValidationModal`` compares the entered password against
``self.container_info``, a dict handed to it when the **button** was created -
and that button lives on ``StatusInfoView``, which reads the container's info
once in its ``__init__`` and is a persistent view (``timeout=None``).

So the password being checked is a snapshot taken when the status message was
last generated. Between two refreshes - 5 minutes by default, up to an hour if
the operator has set ``update_interval_minutes`` that high - an operator can
change a protected password in the web panel and:

* the **old** password still opens the protected information, and
* the **old** protected content is what gets shown, because
  ``protected_content`` comes out of the same snapshot.

Nothing anywhere says so. The operator changes a secret, sees it saved, and
the secret they replaced keeps being handed out.

This is the same sentence as review B3 / SPEC.md Z5 - *"a view still open after
a revocation kept creating tasks for up to ~890 s"* - and it has the same
answer: **ask at the moment of the action, not at the moment of the button.**
Reading one small JSON file per password submission is not a cost worth
trading a stale secret for.

The snapshot stays as the fallback: if the info cannot be read at submit time,
refusing outright would lock the operator out of their own data over a
transient error, and a read failure is not a reason to hand out the secret
either - so it falls back and says so in the log.
"""

import pytest


OLD = {"protected_password": "old-secret", "protected_content": "the old content",
       "protected_enabled": True}
NEW = {"protected_password": "new-secret", "protected_content": "the new content",
       "protected_enabled": True}


class _Response:
    def __init__(self):
        self.messages = []
        self.embeds = []

    async def send_message(self, content=None, *, embed=None, **_kw):
        if content:
            self.messages.append(content)
        if embed is not None:
            self.embeds.append(embed)


class _Interaction:
    def __init__(self, user_id=4242):
        self.response = _Response()
        self.user = type("U", (), {"id": user_id, "display_name": "someone",
                                   "__str__": lambda self: "someone"})()
        self.guild = None


@pytest.fixture
def modal_with_a_stale_snapshot(monkeypatch):
    """The button was built when the password was still 'old-secret'."""
    import cogs.enhanced_info_modal_simple as modal_module

    class _Data:
        @staticmethod
        def to_dict():
            return dict(NEW)

    class _Service:
        @staticmethod
        def get_container_info(_name):
            return type("R", (), {"success": True, "data": _Data})

    monkeypatch.setattr(modal_module, "get_container_info_service", lambda: _Service())
    monkeypatch.setattr(modal_module, "_PASSWORD_ATTEMPTS", {})

    instance = modal_module.PasswordValidationModal.__new__(
        modal_module.PasswordValidationModal)
    instance.cog = None
    instance.container_name = "minecraft"
    instance.display_name = "Minecraft"
    instance.container_info = dict(OLD)          # the stale snapshot
    return instance


def _enter(instance, password):
    instance.password_input = type("I", (), {"value": password})()


@pytest.mark.asyncio
async def test_the_old_password_no_longer_opens_it(modal_with_a_stale_snapshot):
    instance = modal_with_a_stale_snapshot
    _enter(instance, "old-secret")
    interaction = _Interaction()

    await instance.callback(interaction)

    assert not interaction.response.embeds, (
        "the protected information was handed out for a password the operator "
        "had already replaced"
    )


@pytest.mark.asyncio
async def test_the_new_password_opens_it_immediately(modal_with_a_stale_snapshot):
    instance = modal_with_a_stale_snapshot
    _enter(instance, "new-secret")
    interaction = _Interaction()

    await instance.callback(interaction)

    assert interaction.response.embeds, (
        "the operator's new password was refused until the next status refresh"
    )


@pytest.mark.asyncio
async def test_the_content_shown_is_the_current_one(modal_with_a_stale_snapshot):
    instance = modal_with_a_stale_snapshot
    _enter(instance, "new-secret")
    interaction = _Interaction()

    await instance.callback(interaction)

    assert interaction.response.embeds, "nothing was shown at all"
    assert interaction.response.embeds[0].description == "the new content", (
        "the password was current but the secret shown was the replaced one"
    )


@pytest.mark.asyncio
async def test_an_unreadable_info_falls_back_to_the_snapshot(monkeypatch):
    """Counter-check: a transient read error must not lock the operator out."""
    import cogs.enhanced_info_modal_simple as modal_module

    class _Service:
        @staticmethod
        def get_container_info(_name):
            raise OSError(13, "Permission denied")

    monkeypatch.setattr(modal_module, "get_container_info_service", lambda: _Service())
    monkeypatch.setattr(modal_module, "_PASSWORD_ATTEMPTS", {})

    instance = modal_module.PasswordValidationModal.__new__(
        modal_module.PasswordValidationModal)
    instance.cog = None
    instance.container_name = "minecraft"
    instance.display_name = "Minecraft"
    instance.container_info = dict(OLD)
    _enter(instance, "old-secret")
    interaction = _Interaction()

    await instance.callback(interaction)

    assert interaction.response.embeds, (
        "a transient read error locked the operator out of their own data"
    )
