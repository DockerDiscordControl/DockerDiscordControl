# -*- coding: utf-8 -*-
"""
THE FINDING (review C52, section 27 F3): the "Pair name is required" rule is
enforced and then undone, two lines later.

    is_valid, error_msg, warnings = validate_pair_data(pair_data)   # name must be non-empty
    ...
    pair_data['name'] = sanitize_string(pair_data.get('name', ''), MAX_PAIR_NAME_LENGTH)

`sanitize_string` strips every '<' and '>'. A name made only of those - "<<>>"
- passes the validator, comes out of the sanitiser as the empty string, and is
saved as a pair with no name at all. `update_pair` has the same order and the
same result.

Checking a value and then changing it is only safe if the check still holds
afterwards. It is checked after the change now.

The counter-checks keep both other answers: a name that only LOOKS dangerous
keeps whatever is left of it, and a normal name is untouched.
"""

import threading

import pytest

from services.translation import translation_config_service as tcs_mod
from services.translation.translation_config_service import TranslationConfigService


@pytest.fixture
def service(tmp_path):
    instance = TranslationConfigService.__new__(TranslationConfigService)
    instance.base_dir = tmp_path
    instance.config_file = tmp_path / "channel_translations.json"
    instance.config_file.write_text(
        '{"channel_pairs": [], "settings": {}}', encoding="utf-8")
    instance._file_lock = threading.Lock()
    instance._key_lock = threading.Lock()
    instance._config_cache = None
    return instance


def _pair(name):
    return {
        "name": name,
        "source_channel_id": "111111111111111111",
        "target_channel_id": "222222222222222222",
        "target_language": "DE",
    }


def test_a_name_made_only_of_brackets_is_refused(service):
    """THE FINDING: nothing is left of it, so it is not a name."""
    result = service.add_pair(_pair("<<>>"))

    assert result.success is False
    assert "name" in (result.error or "").lower()


def test_such_a_pair_is_not_saved_nameless(service):
    """What the operator would find: a pair with no name in the list."""
    service.add_pair(_pair("<<>>"))

    assert [p.name for p in service.get_pairs()] == []


def test_an_update_refuses_it_too(service):
    """`update_pair` has the same order and needed the same check."""
    service.add_pair(_pair("Working Pair"))
    pair_id = service.get_pairs()[0].id

    result = service.update_pair(pair_id, _pair("<<>>"))

    assert result.success is False
    assert service.get_pairs()[0].name == "Working Pair"


def test_a_name_with_brackets_around_real_text_is_kept(service):
    """COUNTER-CHECK: sanitising still sanitises, and what is left is a name."""
    result = service.add_pair(_pair("<Server> Announcements"))

    assert result.success is True
    assert service.get_pairs()[0].name == "Server Announcements"


def test_an_ordinary_name_is_untouched(service):
    """COUNTER-CHECK: the normal path does not change."""
    assert service.add_pair(_pair("Announcements")).success is True
    assert service.get_pairs()[0].name == "Announcements"
