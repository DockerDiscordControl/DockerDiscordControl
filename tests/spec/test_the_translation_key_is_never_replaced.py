# -*- coding: utf-8 -*-
"""
THE FINDING (review C27, section 27 F2): a transient read error destroys the
stored translation API key for good.

`_get_encryption_key()` reads `config/.translation_key`. Both the fast path and
the locked double-check swallow every exception from that read -

    except Exception as e:
        logger.warning("Could not load translation encryption key, generating new one: %s", e)
    ...
    except Exception:
        pass

- and then fall through to `Fernet.generate_key()`, which is written and
RENAMED OVER the existing key file. The DeepL or Google key stored in
`channel_translations.json` was encrypted with the key that has just been
thrown away; it can never be decrypted again. The only trace is one WARNING.

The path that does this is a READ path: `translation_service._get_api_key()`
calls it to decrypt. So a permission mismatch - the file written by one user,
the app now running as another, which is an everyday situation on Unraid - is
enough to turn "I cannot read the key right now" into "the key is gone
forever".

A key is generated only when the file genuinely does not exist. A file that is
there but unreadable is a configuration problem to report, never a reason to
mint a replacement.

Because the overwrite is gone, `save_api_key` would otherwise fall through to
its "store the key WITHOUT encryption" fallback whenever the key file is
broken - a plaintext secret produced by a transient error. It now refuses that
one case and says so instead.

The counter-check (test_a_missing_key_file_is_still_created) keeps the normal
first-run behaviour.
"""

import threading
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from services.translation.translation_config_service import (
    TranslationConfigService,
    TranslationKeyUnreadable,
)


@pytest.fixture
def service(tmp_path):
    instance = TranslationConfigService.__new__(TranslationConfigService)
    instance.base_dir = tmp_path
    instance.config_file = tmp_path / "channel_translations.json"
    instance.config_file.write_text('{"pairs": [], "settings": {}}', encoding="utf-8")
    instance._file_lock = threading.Lock()
    instance._key_lock = threading.Lock()
    return instance


def _key_file(service) -> Path:
    return service.config_file.parent / ".translation_key"


def test_an_unreadable_key_file_is_not_replaced(service):
    """THE FINDING: the key file must survive a read that fails."""
    _key_file(service).write_bytes(b"this is not a valid fernet key")

    with pytest.raises(TranslationKeyUnreadable):
        service._get_encryption_key()

    assert _key_file(service).read_bytes() == b"this is not a valid fernet key"


def test_a_secret_stays_decryptable_after_a_failed_read(service, monkeypatch):
    """The damage, stated as the operator would meet it: the key file cannot be
    read once, and afterwards the stored secret is still readable."""
    real_key = Fernet.generate_key()
    _key_file(service).write_bytes(real_key)
    secret = Fernet(real_key).encrypt(b"deepl-api-key-12345").decode()

    original_read = Path.read_bytes

    def _refuse(self):
        if self.name == ".translation_key":
            raise PermissionError("owned by another user")
        return original_read(self)

    monkeypatch.setattr(Path, "read_bytes", _refuse)
    with pytest.raises(TranslationKeyUnreadable):
        service._get_encryption_key()
    monkeypatch.setattr(Path, "read_bytes", original_read)

    recovered = service._get_encryption_key().decrypt(secret.encode()).decode()
    assert recovered == "deepl-api-key-12345"


def test_saving_does_not_fall_back_to_plaintext_on_a_broken_key_file(service):
    """A transient failure must not turn the secret into plaintext on disk."""
    _key_file(service).write_bytes(b"broken")

    result = service.save_api_key("deepl-api-key-12345")

    assert result.success is False
    assert "deepl-api-key-12345" not in service.config_file.read_text(encoding="utf-8")


def test_a_missing_key_file_is_still_created(service):
    """COUNTER-CHECK: first run still works - no key file, one is made, and a
    round trip through it succeeds."""
    assert not _key_file(service).exists()

    fernet = service._get_encryption_key()

    assert _key_file(service).exists()
    assert fernet.decrypt(fernet.encrypt(b"secret")) == b"secret"
