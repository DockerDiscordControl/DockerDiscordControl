# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""The web panel's second factor: TOTP (RFC 6238) and recovery codes.

v3.0 step 9 (docs/V3_ARCHITECTURE_PLAN.md §5). Operator decision 2026-09-22:
offered and strongly recommended, never forced, and only over TLS.

Deliberately stdlib-only: RFC 6238 is a few lines of HMAC, and a security
component a sceptical user can read end to end is worth more than a
dependency.

Storage is ``two_factor.json`` in the config directory, mode 0600 - a file
v2.4.1 never reads or writes. A downgrade therefore cannot drop the secret on
its first save, and a later upgrade does not find 2FA silently switched off
(V3 §5.5). An unreadable file raises instead of reading as "off": a damaged
file must not open the panel without the second factor.

Break-glass for a lost phone and lost recovery codes: whoever owns the host
deletes the file (see scripts/disable_2fa.py). The host owner is outside the
security boundary by design (V3 §5.2).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import struct
import threading
import time
from pathlib import Path
from typing import List, Optional

from utils.config_paths import get_config_dir

STEP_SECONDS = 30
DRIFT_STEPS = 1
TRUSTED_DEVICE_DAYS = 90  # the operator's number, 2026-09-25
RECOVERY_CODE_COUNT = 10
FILE_NAME = "two_factor.json"


class TwoFactorUnreadable(RuntimeError):
    """two_factor.json exists but cannot be read - never treated as "2FA off"."""


def totp(secret: bytes, unix_time: float, digits: int = 6, step: int = STEP_SECONDS) -> str:
    """RFC 6238 TOTP with HMAC-SHA1 (the algorithm authenticator apps default to)."""
    counter = int(unix_time) // step
    digest = hmac.new(secret, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % (10 ** digits)).zfill(digits)


def secret_bytes(secret_b32: str) -> bytes:
    padding = "=" * (-len(secret_b32) % 8)
    return base64.b32decode(secret_b32 + padding, casefold=True)


def new_secret() -> str:
    """160 random bits, base32 without padding - what authenticator apps expect."""
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _hash_recovery_code(code: str) -> str:
    return hashlib.sha256(code.replace("-", "").strip().lower().encode()).hexdigest()


def _hash_device_token(token: str) -> str:
    return hashlib.sha256(token.strip().encode()).hexdigest()


def _new_recovery_code() -> str:
    raw = secrets.token_hex(5)  # 40 bits, shown as xxxxx-xxxxx
    return f"{raw[:5]}-{raw[5:]}"


def default_path() -> Path:
    return Path(get_config_dir()) / FILE_NAME


class TwoFactorStore:
    """two_factor.json: the state of the second factor, read fresh on every access."""

    _lock = threading.Lock()

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else default_path()

    # -- file --------------------------------------------------------------
    def _read(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as error:
            raise TwoFactorUnreadable(f"{self.path} cannot be read: {error}") from error
        if not isinstance(data, dict):
            raise TwoFactorUnreadable(f"{self.path} does not hold an object")
        return data

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        # 0600 from the first byte: the secret is never readable in between.
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    # -- state -------------------------------------------------------------
    @property
    def enabled(self) -> bool:
        return bool(self._read().get("enabled"))

    def pending_or_active_secret(self) -> Optional[str]:
        data = self._read()
        return data.get("secret") if data.get("enabled") else data.get("pending_secret")

    def remaining_recovery_codes(self) -> int:
        return len(self._read().get("recovery_hashes", []))

    def prompt_dismissed(self) -> bool:
        return bool(self._read().get("prompt_dismissed"))

    def dismiss_prompt(self) -> None:
        with self._lock:
            data = self._read()
            data["prompt_dismissed"] = True
            self._write(data)

    # -- setup -------------------------------------------------------------
    def begin_setup(self) -> str:
        """Create a pending secret. 2FA stays off until a code confirms it."""
        with self._lock:
            data = self._read()
            if data.get("enabled"):
                raise RuntimeError("2FA is already on - disable it first")
            data["pending_secret"] = new_secret()
            self._write(data)
            return data["pending_secret"]

    def confirm_setup(self, code: str, now: Optional[float] = None) -> List[str]:
        """Switch 2FA on if ``code`` matches the pending secret. Returns the
        recovery codes - the only time they exist in clear - or [] on a wrong code."""
        now = time.time() if now is None else now
        with self._lock:
            data = self._read()
            pending = data.get("pending_secret")
            if not pending or data.get("enabled"):
                return []
            step = self._matching_step(pending, code, now, last_used=None)
            if step is None:
                return []
            codes = [_new_recovery_code() for _ in range(RECOVERY_CODE_COUNT)]
            data.update({
                "enabled": True,
                "secret": pending,
                "last_step": step,
                "recovery_hashes": [_hash_recovery_code(c) for c in codes],
                "enabled_at": int(now),
            })
            data.pop("pending_secret", None)
            self._write(data)
            return codes

    # -- verification ------------------------------------------------------
    @staticmethod
    def _matching_step(secret_b32: str, code: str, now: float, last_used: Optional[int]) -> Optional[int]:
        code = (code or "").strip().replace(" ", "")
        if not (code.isdigit() and len(code) == 6):
            return None
        key = secret_bytes(secret_b32)
        current = int(now) // STEP_SECONDS
        for step in range(current - DRIFT_STEPS, current + DRIFT_STEPS + 1):
            # A step at or before the last one used is spent: a code read off the
            # wire or over a shoulder does not work a second time.
            if last_used is not None and step <= last_used:
                continue
            if hmac.compare_digest(totp(key, step * STEP_SECONDS), code):
                return step
        return None

    # -- remembered devices ------------------------------------------------
    #
    # A device the operator told the panel to remember skips the SECOND
    # FACTOR only: the panel password is still asked every time. So this is
    # not a way in, it is a record that this browser has already proved it
    # holds the phone.
    #
    # THE TOKEN IS KEPT AS A HASH, for the same reason the recovery codes
    # are: this file is readable by anything running as this user, and a
    # credential written down in it IS the credential. The browser holds the
    # token; this holds sha256 of it.
    #
    # BOUND TO THE PASSWORD, by the same binding the session marker uses, so
    # a changed password forgets every device - otherwise whoever knew the
    # old one would keep a way past the second factor.

    def remember_device(self, token: str, binding: str, now: Optional[float] = None) -> None:
        """Write down that this browser has answered, until it expires."""
        moment = time.time() if now is None else now
        with self._lock:
            data = self._read()
            devices = [d for d in data.get("devices", [])
                       if d.get("expires", 0) > moment and d.get("binding") == binding]
            devices.append({
                "hash": _hash_device_token(token),
                "binding": binding,
                "expires": moment + TRUSTED_DEVICE_DAYS * 86400,
            })
            data["devices"] = devices
            self._write(data)

    def knows_device(self, token: str, binding: str, now: Optional[float] = None) -> bool:
        """Whether this browser answered within the last ninety days.

        Every one of the three has to hold: the hash, the password it was
        bound to, and the expiry. A token we never issued matches none of
        them, which is the answer to bringing your own cookie.
        """
        if not token:
            return False
        moment = time.time() if now is None else now
        wanted = _hash_device_token(token)
        return any(d.get("hash") == wanted and d.get("binding") == binding
                   and d.get("expires", 0) > moment
                   for d in self._read().get("devices", []))

    def forget_expired_devices(self, now: Optional[float] = None) -> None:
        moment = time.time() if now is None else now
        with self._lock:
            data = self._read()
            kept = [d for d in data.get("devices", []) if d.get("expires", 0) > moment]
            if len(kept) != len(data.get("devices", [])):
                data["devices"] = kept
                self._write(data)

    def forget_every_device(self) -> None:
        with self._lock:
            data = self._read()
            if data.pop("devices", None) is not None:
                self._write(data)

    def remembered_devices(self) -> int:
        return len(self._read().get("devices", []))

    def holds_recovery_code(self, code: str) -> bool:
        """Whether this is one of the unused recovery codes - WITHOUT spending it.

        ``verify`` below spends a code on success, which is right when one is
        being USED. Keeping a copy of them is not using one, so the download
        asks this instead; a download that consumed them would hand over ten
        codes that no longer work.
        """
        return _hash_recovery_code(code) in self._read().get("recovery_hashes", [])

    def verify(self, code: str, now: Optional[float] = None) -> bool:
        """A current TOTP code or an unused recovery code; either is spent on success."""
        now = time.time() if now is None else now
        with self._lock:
            data = self._read()
            if not data.get("enabled"):
                return False
            step = self._matching_step(data["secret"], code, now, data.get("last_step"))
            if step is not None:
                data["last_step"] = step
                self._write(data)
                return True
            hashed = _hash_recovery_code(code or "")
            remaining = data.get("recovery_hashes", [])
            for stored in remaining:
                if hmac.compare_digest(stored, hashed):
                    remaining.remove(stored)
                    data["recovery_hashes"] = remaining
                    self._write(data)
                    return True
            return False

    def disable(self, code: str, now: Optional[float] = None) -> bool:
        """Switch 2FA off - only with a valid code, so a stolen password alone cannot."""
        if not self.verify(code, now=now):
            return False
        with self._lock:
            data = self._read()
            # prompt_dismissed as well: switching 2FA off is a fresh start, and a
            # "Later" from before it was ever used must not silence the dialog
            # for the rest of the installation's life.
            # "devices" among them, and HERE rather than in the route that
            # calls this: switching 2FA off any other way - the break-glass
            # script, a future route - would otherwise leave browsers written
            # down that may walk past a second factor switched on again later.
            for key in ("enabled", "secret", "last_step", "recovery_hashes", "enabled_at",
                        "pending_secret", "prompt_dismissed", "devices"):
                data.pop(key, None)
            self._write(data)
        return True
