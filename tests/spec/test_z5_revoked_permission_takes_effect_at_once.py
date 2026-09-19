# -*- coding: utf-8 -*-
# @covers Z5
"""Z5 - a channel's permission counts as it is NOW, not as it was a while ago.

THE FINDING (stage 4 review pass 1, section 02 F1, re-checked 2026-09-19):
``_get_cached_channel_permission`` (cogs/control_ui.py) - the decision behind
start/stop/restart and task deletion - cached its answer under a key built
from ``config['_cache_timestamp']``. Nothing ever sets that field, so the key
never changed, and the hot-reload after a panel save did not clear the cache.
A control right revoked in the panel stayed effective until the periodic
cache clear, up to 5 minutes. The reviewer said "forever" and missed that
loop; the operator's decision of 2026-09-16 says "ineffective immediately".
"""

import cogs.control_ui as cui

# Channel ids no other test uses: the cache is module-global, and a first version
# of this file used 300 - another spec test had cached "no control" for it, so the
# FIRST assertion failed for a neighbour's answer (the bug itself, but order-dependent).
CHANNEL = 918_273_645


def _config(control):
    return {"channel_permissions": {str(CHANNEL): {"commands": {"control": control}}}}


def test_a_revoked_right_is_gone_at_once():
    assert cui._get_cached_channel_permission(CHANNEL, "control", _config(True)) is True
    assert cui._get_cached_channel_permission(CHANNEL, "control", _config(False)) is False, (
        "the right was revoked in the configuration, but the cached 'yes' still counts"
    )


def test_a_granted_right_counts_at_once():
    assert cui._get_cached_channel_permission(CHANNEL + 1, "control", {
        "channel_permissions": {str(CHANNEL + 1): {"commands": {"control": False}}}}) is False
    assert cui._get_cached_channel_permission(CHANNEL + 1, "control", {
        "channel_permissions": {str(CHANNEL + 1): {"commands": {"control": True}}}}) is True
