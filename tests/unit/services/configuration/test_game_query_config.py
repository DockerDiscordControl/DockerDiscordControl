#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for the per-container game-query (opengsq) configuration:
- ConfigValidationService.sanitize_query_config (protocol/port/host hardening)
- ConfigFormParserService.parse_servers_from_form (parses + sanitizes query_* fields)
"""
import pytest
from unittest.mock import MagicMock, patch

from services.config.config_validation_service import ConfigValidationService
from services.config.config_form_parser_service import ConfigFormParserService


# ---------------------------------------------------------------------------
# Web save handler must PERSIST the per-container query fields (regression for the
# critical bug where save_container_configs_from_web dropped all query_* keys).
# ---------------------------------------------------------------------------

class TestWebSavePersistsQuery:
    def test_save_handler_persists_query_fields(self):
        from app.utils.container_info_web_handler import save_container_configs_from_web

        saved = {}
        css = MagicMock()
        css.save_container_config.side_effect = lambda name, cfg: (saved.__setitem__(name, cfg), True)[1]
        scs = MagicMock()
        scs.get_all_servers.return_value = []
        scs.get_server_by_docker_name.return_value = None

        servers = [{
            'docker_name': 'valheim', 'container_name': 'valheim', 'display_name': 'Valheim',
            'allowed_actions': ['status'],
            'query_enabled': True, 'query_protocol': 'source',
            'query_host': '10.0.0.5', 'query_port': 2457, 'query_token': 'TOK',
        }]

        with patch('services.config.container_config_save_service.get_container_config_save_service',
                   return_value=css), \
             patch('services.config.server_config_service.get_server_config_service',
                   return_value=scs):
            save_container_configs_from_web(servers)

        cfg = saved['valheim']
        assert cfg['query_enabled'] is True
        assert cfg['query_protocol'] == 'source'
        assert cfg['query_host'] == '10.0.0.5'
        assert cfg['query_port'] == 2457
        assert cfg['query_token'] == 'TOK'


class FakeForm(dict):
    """Minimal stand-in for a Flask MultiDict (supports getlist + get)."""
    def getlist(self, key):
        v = dict.get(self, key)
        if v is None:
            return []
        return v if isinstance(v, list) else [v]


# ---------------------------------------------------------------------------
# sanitize_query_config
# ---------------------------------------------------------------------------

class TestSanitizeQueryConfig:
    def test_defaults_pass_through(self):
        out = ConfigValidationService.sanitize_query_config(False, 'source', '', 0)
        assert out == {'query_enabled': False, 'query_protocol': 'source',
                       'query_host': '', 'query_port': 0, 'query_token': ''}

    def test_unsupported_protocol_falls_back_to_source(self):
        out = ConfigValidationService.sanitize_query_config(True, 'quake3', '', 0)
        assert out['query_protocol'] == 'source'

    def test_minecraft_and_satisfactory_protocols_allowed(self):
        assert ConfigValidationService.sanitize_query_config(True, 'minecraft', '', 0)['query_protocol'] == 'minecraft'
        assert ConfigValidationService.sanitize_query_config(True, 'satisfactory', '', 0)['query_protocol'] == 'satisfactory'
        assert ConfigValidationService.sanitize_query_config(True, 'palworld', '', 0)['query_protocol'] == 'palworld'

    def test_token_is_trimmed_and_capped(self):
        out = ConfigValidationService.sanitize_query_config(True, 'satisfactory', '', 7777, '  tok123  ')
        assert out['query_token'] == 'tok123'
        long = 'x' * 5000
        assert len(ConfigValidationService.sanitize_query_config(True, 'satisfactory', '', 0, long)['query_token']) == 1024

    def test_protocol_is_lowercased(self):
        assert ConfigValidationService.sanitize_query_config(True, 'SOURCE', '', 0)['query_protocol'] == 'source'

    def test_port_out_of_range_becomes_zero(self):
        assert ConfigValidationService.sanitize_query_config(True, 'source', '', 70000)['query_port'] == 0
        assert ConfigValidationService.sanitize_query_config(True, 'source', '', -5)['query_port'] == 0

    def test_invalid_port_becomes_zero(self):
        assert ConfigValidationService.sanitize_query_config(True, 'source', '', 'abc')['query_port'] == 0

    def test_valid_port_kept(self):
        assert ConfigValidationService.sanitize_query_config(True, 'source', '', '2457')['query_port'] == 2457

    def test_host_scheme_and_path_are_stripped(self):
        out = ConfigValidationService.sanitize_query_config(True, 'source', 'udp://1.2.3.4/foo', 0)
        assert out['query_host'] == '1.2.3.4'

    def test_host_is_trimmed(self):
        assert ConfigValidationService.sanitize_query_config(True, 'source', '  host  ', 0)['query_host'] == 'host'

    def test_enabled_coerced_to_bool(self):
        assert ConfigValidationService.sanitize_query_config('1', 'source', '', 0)['query_enabled'] is True
        assert ConfigValidationService.sanitize_query_config('', 'source', '', 0)['query_enabled'] is False


# ---------------------------------------------------------------------------
# parse_servers_from_form
# ---------------------------------------------------------------------------

class TestParseServersQueryFields:
    def test_query_fields_parsed_for_selected_container(self):
        form = FakeForm({
            'selected_servers': ['valheim'],
            'query_enabled_valheim': '1',
            'query_protocol_valheim': 'source',
            'query_host_valheim': '10.0.0.5',
            'query_port_valheim': '2457',
        })
        servers = ConfigFormParserService.parse_servers_from_form(form)
        s = next(x for x in servers if x['docker_name'] == 'valheim')
        assert s['query_enabled'] is True
        assert s['query_protocol'] == 'source'
        assert s['query_host'] == '10.0.0.5'
        assert s['query_port'] == 2457

    def test_defaults_when_query_fields_absent(self):
        form = FakeForm({'selected_servers': ['nginx']})
        s = ConfigFormParserService.parse_servers_from_form(form)[0]
        assert s['query_enabled'] is False
        assert s['query_protocol'] == 'source'
        assert s['query_host'] == ''
        assert s['query_port'] == 0
        assert s['query_token'] == ''

    def test_satisfactory_token_parsed(self):
        form = FakeForm({
            'selected_servers': ['sat'],
            'query_enabled_sat': '1',
            'query_protocol_sat': 'satisfactory',
            'query_port_sat': '7777',
            'query_token_sat': 'MY-APP-TOKEN',
        })
        s = next(x for x in ConfigFormParserService.parse_servers_from_form(form) if x['docker_name'] == 'sat')
        assert s['query_protocol'] == 'satisfactory'
        assert s['query_token'] == 'MY-APP-TOKEN'
        assert s['query_port'] == 7777

    def test_query_fields_are_sanitized(self):
        form = FakeForm({
            'selected_servers': ['srv'],
            'query_enabled_srv': '1',
            'query_protocol_srv': 'BADPROTO',
            'query_host_srv': 'udp://host/x',
            'query_port_srv': '99999',
        })
        s = ConfigFormParserService.parse_servers_from_form(form)[0]
        assert s['query_protocol'] == 'source'   # whitelisted
        assert s['query_host'] == 'host'         # scheme/path stripped
        assert s['query_port'] == 0              # out of range -> auto


# ---------------------------------------------------------------------------
# Advanced settings (env_*) round-trip into config['advanced_settings']
# ---------------------------------------------------------------------------

class TestAdvancedSettingsPersist:
    def _process(self, form):
        cfg_service = MagicMock()
        cfg_service.save_config.return_value = MagicMock(success=True, message="ok")
        updated, ok, msg = ConfigFormParserService.process_config_form(FakeForm(form), {}, cfg_service)
        return updated

    def test_opengsq_toggle_on_persists_to_advanced_settings(self):
        updated = self._process({'selected_servers': [], 'env_DDC_ENABLE_OPENGSQ': '1'})
        assert updated['advanced_settings']['DDC_ENABLE_OPENGSQ'] == '1'

    def test_opengsq_toggle_off_persists(self):
        updated = self._process({'selected_servers': [], 'env_DDC_ENABLE_OPENGSQ': '0'})
        assert updated['advanced_settings']['DDC_ENABLE_OPENGSQ'] == '0'

    def test_env_fields_not_left_as_toplevel_keys(self):
        updated = self._process({'selected_servers': [], 'env_DDC_ENABLE_OPENGSQ': '1'})
        assert 'env_DDC_ENABLE_OPENGSQ' not in updated  # folded into advanced_settings only

    def test_other_advanced_settings_round_trip(self):
        updated = self._process({'selected_servers': [], 'env_DDC_DOCKER_CACHE_DURATION': '45'})
        assert updated['advanced_settings']['DDC_DOCKER_CACHE_DURATION'] == '45'

    def test_bare_query_keys_never_leak_to_toplevel(self):
        # F6 defense-in-depth: if a modal field's bare name= ever leaks into the main form,
        # the secret token (and other bare query fields) must NOT land in top-level config.json.
        updated = self._process({
            'selected_servers': [],
            'query_token': 'SECRET', 'query_host': 'h', 'query_port': '1',
            'query_protocol': 'p', 'container_name': 'x',
        })
        for k in ('query_token', 'query_host', 'query_port', 'query_protocol', 'container_name'):
            assert k not in updated, f"bare '{k}' leaked into top-level config"
