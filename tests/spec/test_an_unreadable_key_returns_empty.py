# -*- coding: utf-8 -*-
"""
THE FINDING (review C14, section 35 F3): `decrypt_key` promises, in its own
comment, "If decryption fails, return empty string (invalid key)". It then
catches

    except (RuntimeError):

Nothing in the function raises RuntimeError. What it really raises is
`binascii.Error` (a ValueError) from `base64.b64decode` when the input is not
base64, and `UnicodeDecodeError` when the XOR result is not text. Both fly
straight out of the function, so the documented "return empty string" never
happens and the caller gets an exception instead of "invalid key".

What is true about the reach, stated plainly: the only production caller is
`get_valid_donation_keys()`, which feeds the built-in ENCRYPTED_DONATION_KEYS
constants - all valid base64. So nothing crashes today. This is the promise in
the code being false, not an outage: the function is one caller away from
breaking, and the comment says it cannot.

The counter-check (test_a_real_key_still_comes_back) keeps the fix from
becoming "always return empty".
"""

import base64

import pytest

from utils.key_crypto import decrypt_key, encrypt_key


def test_a_value_that_is_not_base64_returns_empty():
    """THE FINDING: b64decode raises binascii.Error, not RuntimeError."""
    assert decrypt_key("this is not base64 !!!") == ""


def test_a_value_that_does_not_decode_to_text_returns_empty():
    """Valid base64 whose XOR result is not UTF-8 raises UnicodeDecodeError."""
    not_text = base64.b64encode(bytes([0xFF, 0xFE, 0xFD])).decode()

    assert decrypt_key(not_text, crypto_key="\x00") == ""


def test_a_real_key_still_comes_back():
    """COUNTER-CHECK: the fix must not swallow the working case."""
    assert decrypt_key(encrypt_key("DDC-TEST-KEY-001")) == "DDC-TEST-KEY-001"
    assert decrypt_key("") == ""
