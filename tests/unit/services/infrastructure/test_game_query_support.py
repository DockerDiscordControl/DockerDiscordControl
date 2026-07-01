#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for the game-query SUPPORT verdict store (gates the web UI checkbox).

Lifecycle: unknown -> probing (up to a 15-min window) -> FINAL supported or FINAL unsupported.
Final verdicts persist across restart and are never re-probed. Going offline resets a
not-yet-final window.
"""
import time

from services.infrastructure.game_query_support_service import (
    GameQuerySupportService, read_support_verdicts,
    PROBE_RETRY_SECONDS, PROBE_WINDOW_SECONDS,
)


def _svc(tmp_path):
    return GameQuerySupportService(path=tmp_path / 'qs.json')


class TestLifecycle:
    def test_unknown_by_default(self, tmp_path):
        assert _svc(tmp_path).is_supported('a') is None

    def test_success_is_final_supported(self, tmp_path):
        s = _svc(tmp_path)
        s.record_result('a', True, 'source', 27015)
        assert s.is_supported('a') is True
        assert s.is_final('a') is True
        assert s.should_probe('a', time.monotonic()) is False   # confirmed -> never re-probe

    def test_supported_not_downgraded_by_later_failure(self, tmp_path):
        s = _svc(tmp_path)
        s.record_result('a', True, 'source', 27015)
        s.record_result('a', False)          # ignored: already final
        assert s.is_supported('a') is True

    def test_probing_within_window_stays_unlocked_target(self, tmp_path):
        s = _svc(tmp_path)
        s.record_result('a', False, now_wall=1000.0)                 # first failed probe
        assert s.is_supported('a') is False and s.is_final('a') is False
        s.record_result('a', False, now_wall=1000.0 + PROBE_WINDOW_SECONDS - 1)
        assert s.is_final('a') is False                             # still probing

    def test_gives_up_after_15min_window(self, tmp_path):
        s = _svc(tmp_path)
        s.record_result('a', False, now_wall=1000.0)                # window opens at t=1000
        s.record_result('a', False, now_wall=1000.0 + PROBE_WINDOW_SECONDS + 1)
        assert s.is_final('a') is True and s.is_supported('a') is False
        assert s.should_probe('a', time.monotonic()) is False        # gave up -> never re-probe


class TestProbeScheduling:
    def test_backoff_within_window(self, tmp_path):
        s = _svc(tmp_path)
        now = time.monotonic()
        s.record_result('a', False, now_wall=1000.0)   # probing (not final)
        assert s.should_probe('a', now) is True         # not yet marked probed
        s.mark_probed('a', now)
        assert s.should_probe('a', now + 1) is False
        assert s.should_probe('a', now + PROBE_RETRY_SECONDS + 1) is True


class TestOfflineReset:
    def test_offline_resets_probing_window(self, tmp_path):
        s = _svc(tmp_path)
        s.record_result('a', False, now_wall=1000.0)   # probing
        s.mark_probed('a', time.monotonic())
        s.note_offline('a')
        assert s.is_supported('a') is None              # forgotten -> fresh window next boot
        assert s.should_probe('a', time.monotonic()) is True

    def test_offline_keeps_final_supported(self, tmp_path):
        s = _svc(tmp_path)
        s.record_result('a', True, 'source', 27015)
        s.note_offline('a')
        assert s.is_supported('a') is True              # sticky across offline

    def test_offline_keeps_final_unsupported(self, tmp_path):
        s = _svc(tmp_path)
        s.record_result('b', False, now_wall=1000.0)
        s.record_result('b', False, now_wall=1000.0 + PROBE_WINDOW_SECONDS + 1)  # final unsupported
        s.note_offline('b')
        assert s.is_final('b') is True and s.is_supported('b') is False


class TestManualRetestHelpers:
    def test_atomic_update_does_not_clobber_other_verdicts(self, tmp_path, monkeypatch):
        monkeypatch.setenv('DDC_CONFIG_DIR', str(tmp_path))
        from services.infrastructure import game_query_support_service as m
        # the bot confirmed another container
        GameQuerySupportService().record_result('other', True, 'source', 27015)
        # the web flags 'x' as testing - must NOT touch 'other'
        m.set_testing('x', True)
        v = read_support_verdicts()
        assert v['x']['testing'] is True
        assert v['other']['supported'] is True

    def test_manual_success_marks_final_supported(self, tmp_path, monkeypatch):
        monkeypatch.setenv('DDC_CONFIG_DIR', str(tmp_path))
        from services.infrastructure import game_query_support_service as m
        m.set_testing('x', True)
        m.record_manual_success('x', 'source', 2457)
        v = read_support_verdicts()['x']
        assert v['supported'] is True and v['final'] is True and v['testing'] is False


class TestNoClobberAndReload:
    """B1 fix: the bot (per-key RMW + reload) must never revert web-written manual verdicts."""

    def test_bot_write_preserves_external_web_verdict(self, tmp_path, monkeypatch):
        monkeypatch.setenv('DDC_CONFIG_DIR', str(tmp_path))
        from services.infrastructure import game_query_support_service as m
        bot = GameQuerySupportService()
        bot.record_result('a', True, 'source', 27015)
        m.record_manual_success('b', 'source', 2457)       # web writes B (manual)
        bot.record_result('c', False, now_wall=1000.0)     # bot keeps writing others
        disk = read_support_verdicts()
        assert disk['a']['supported'] is True
        assert disk['b']['supported'] is True              # NOT clobbered by the bot
        assert disk['c']['supported'] is False

    def test_reload_picks_up_external_manual_success(self, tmp_path, monkeypatch):
        monkeypatch.setenv('DDC_CONFIG_DIR', str(tmp_path))
        from services.infrastructure import game_query_support_service as m
        bot = GameQuerySupportService()
        bot.record_result('x', False, now_wall=1000.0)     # bot: x still probing
        m.record_manual_success('x', 'minecraft', 25565)   # web: x confirmed
        assert bot.is_supported('x') is False              # stale before reload
        bot.reload()
        assert bot.is_supported('x') is True               # external verdict adopted
        assert bot.should_probe('x', time.monotonic()) is False

    def test_note_offline_preserves_external_verdict(self, tmp_path, monkeypatch):
        monkeypatch.setenv('DDC_CONFIG_DIR', str(tmp_path))
        from services.infrastructure import game_query_support_service as m
        bot = GameQuerySupportService()
        m.record_manual_success('keep', 'source', 2457)
        bot.record_result('gone', False, now_wall=1000.0)
        bot.note_offline('gone')
        disk = read_support_verdicts()
        assert 'gone' not in disk and disk['keep']['supported'] is True


class TestWindowGapReset:
    def test_window_resets_after_long_gap(self, tmp_path):
        s = GameQuerySupportService(path=tmp_path / 'qs.json')
        s.record_result('a', False)                        # probing (real-time updated)
        old = time.time() - 1200                           # pretend 20 min downtime
        s._state['a']['updated'] = old
        s._state['a']['probing_since'] = old
        s.record_result('a', False)                        # gap 1200s > 300 -> fresh window
        assert s.is_final('a') is False

    def test_window_elapses_without_gap(self, tmp_path):
        s = GameQuerySupportService(path=tmp_path / 'qs.json')
        s.record_result('a', False)
        now = time.time()
        s._state['a']['probing_since'] = now - 1200        # opened 20 min ago
        s._state['a']['updated'] = now - 60                # probed 60s ago (no gap)
        s.record_result('a', False)                        # window elapsed -> final unsupported
        assert s.is_final('a') is True and s.is_supported('a') is False


class TestPersistence:
    def test_persists_and_survives_restart(self, tmp_path, monkeypatch):
        monkeypatch.setenv('DDC_CONFIG_DIR', str(tmp_path))
        s = GameQuerySupportService()                   # default path -> tmp_path/query_support.json
        s.record_result('a', True, 'source', 27015)
        # web process reads the file fresh (no shared memory)
        assert read_support_verdicts().get('a', {}).get('supported') is True
        # a fresh instance (= after restart) loads the verdict and won't re-probe
        restarted = GameQuerySupportService()
        assert restarted.is_supported('a') is True
        assert restarted.should_probe('a', time.monotonic()) is False

    def test_migrates_legacy_entries_without_final_flag(self, tmp_path):
        import json
        p = tmp_path / 'qs.json'
        # legacy file format (no 'final' key)
        p.write_text(json.dumps({
            'sup': {'supported': True, 'protocol': 'source', 'port': None, 'updated': 1.0},
            'no': {'supported': False, 'protocol': None, 'port': None, 'updated': 1.0},
        }), encoding='utf-8')
        s = GameQuerySupportService(path=p)
        assert s.is_final('sup') is True and s.is_supported('sup') is True   # trusted, sticky
        assert s.is_final('no') is False                                     # keeps probing
        # a supported-but-offline legacy entry must NOT be dropped on offline
        s.note_offline('sup')
        assert s.is_supported('sup') is True

    def test_final_unsupported_survives_restart(self, tmp_path, monkeypatch):
        monkeypatch.setenv('DDC_CONFIG_DIR', str(tmp_path))
        s = GameQuerySupportService()
        s.record_result('db', False, now_wall=1000.0)
        s.record_result('db', False, now_wall=1000.0 + PROBE_WINDOW_SECONDS + 1)
        restarted = GameQuerySupportService()
        assert restarted.is_final('db') is True
        assert restarted.should_probe('db', time.monotonic()) is False   # never probed again
