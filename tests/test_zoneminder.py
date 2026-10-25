"""Tests for grafana_cdktf_helpers.zoneminder."""
import json
from unittest.mock import MagicMock

import pytest

from grafana_cdktf_helpers import alert_rule_helpers, zoneminder
from grafana_cdktf_helpers.zoneminder import ZoneMinder

WS_NAME = 'ZMES Websocket Response Time'


@pytest.fixture
def stack():
    s = MagicMock()
    s.prom.uid = 'prom-uid-abc'
    return s


@pytest.fixture(autouse=True)
def reset_rule_group_mocks():
    alert_rule_helpers.RuleGroupRule.reset_mock()
    alert_rule_helpers.RuleGroupRuleData.reset_mock()
    alert_rule_helpers.RuleGroupRuleDataRelativeTimeRange.reset_mock()
    zoneminder.RuleGroup.reset_mock()
    yield


def _zm(stack, **kwargs):
    ZoneMinder(
        stack, hostname='zmhost', folder_id='fid', folder_uid='fuid',
        dashboard_uid='duid', **kwargs
    )


def _websocket_rule_kwargs():
    """The RuleGroupRule kwargs for the ZMES websocket rule, or None."""
    for call in alert_rule_helpers.RuleGroupRule.call_args_list:
        if call.kwargs.get('name') == WS_NAME:
            return call.kwargs
    return None


def _websocket_query():
    """(expr, relative-time-range-from, reducer) for the websocket rule.

    The A (query) and B (reduce) models are emitted immediately before the
    rule's own RuleGroupRule call, so walk the data list off that call.
    """
    kw = _websocket_rule_kwargs()
    assert kw is not None, f'no {WS_NAME} rule was emitted'
    models = {}
    froms = {}
    for call in alert_rule_helpers.RuleGroupRuleData.call_args_list:
        model = json.loads(call.kwargs['model'])
        if model.get('expr', '').startswith(('max_over_time(zm_zmes',
                                             'avg_over_time(zm_zmes')):
            models['A'] = model
            froms['A'] = call.kwargs['relative_time_range']
        elif models.get('A') and call.kwargs['ref_id'] == 'B':
            models['B'] = model
            break
    return models['A'], froms['A'], models['B']


class TestZmesWebsocketAlert:

    def test_not_emitted_unless_enabled(self, stack):
        _zm(stack)
        assert _websocket_rule_kwargs() is None

    def test_defaults_are_max_over_five_minutes(self, stack):
        _zm(stack, enable_zmes_websocket_alerts=True)
        a, _rtr, b = _websocket_query()
        assert a['expr'] == (
            'max_over_time(zm_zmes_websocket_response_time_seconds'
            '{status="Success"}[1m])'
        )
        assert b['reducer'] == 'max'
        kw = _websocket_rule_kwargs()
        assert kw['for_'] == '1m'
        assert kw['annotations']['description'] == (
            'ZMES websocket maximum response time was '
            '{{ printf "%.2f" $values.B.Value }} seconds in the last 5 minutes'
        )

    def test_mean_aggregation_uses_avg_over_time_and_mean_reducer(self, stack):
        _zm(
            stack, enable_zmes_websocket_alerts=True,
            zmes_websocket_aggregation='mean', zmes_websocket_threshold=0.25,
            zmes_websocket_from=900, zmes_websocket_for='5m',
        )
        a, _rtr, b = _websocket_query()
        assert a['expr'] == (
            'avg_over_time(zm_zmes_websocket_response_time_seconds'
            '{status="Success"}[1m])'
        )
        assert b['reducer'] == 'mean'
        kw = _websocket_rule_kwargs()
        assert kw['for_'] == '5m'
        assert kw['annotations']['description'] == (
            'ZMES websocket mean response time was '
            '{{ printf "%.2f" $values.B.Value }} seconds in the last 15 minutes'
        )

    def test_rejects_unknown_aggregation(self, stack):
        with pytest.raises(ValueError, match='must be .max. or .mean.'):
            _zm(
                stack, enable_zmes_websocket_alerts=True,
                zmes_websocket_aggregation='p95',
            )


def _rule_kwargs_by_name():
    return {
        call.kwargs['name']: call.kwargs
        for call in alert_rule_helpers.RuleGroupRule.call_args_list
    }


HEALTH_RULES = [
    'ZM Monitor Connected', 'ZM Monitor Active', 'ZM Monitor Signal',
    'ZM Monitor Capture FPS', 'ZM Monitor Image Size',
    'ZM Monitor Heartbeat Age', 'ZM Monitor Last Read Time',
    'ZM Monitor Last Write Time',
]
RESTART_RULES = ['ZM Monitor ZMC Uptime', 'ZM Monitor Startup Time']


class TestMonitorPendingDurations:

    def test_defaults_are_one_minute(self, stack):
        _zm(stack)
        rules = _rule_kwargs_by_name()
        for name in HEALTH_RULES + RESTART_RULES:
            assert rules[name]['for_'] == '1m', name

    def test_monitor_and_restart_for(self, stack):
        _zm(stack, monitor_for='10m', restart_for='20m')
        rules = _rule_kwargs_by_name()
        for name in HEALTH_RULES:
            assert rules[name]['for_'] == '10m', name
        for name in RESTART_RULES:
            assert rules[name]['for_'] == '20m', name
        # Config-state rules are not reboot-sensitive and keep their default.
        assert rules['ZM Monitor Enabled']['for_'] == '1m'

    def test_health_series_keep_a_one_minute_window(self, stack):
        """A longer for_ must not widen the averaging window, or a 2-minute
        outage would hold the mean below 1 for the whole for_ and fire."""
        _zm(stack, monitor_for='10m')
        exprs = [
            json.loads(c.kwargs['model']).get('expr', '')
            for c in alert_rule_helpers.RuleGroupRuleData.call_args_list
        ]
        assert 'zm_monitor_connected[1m]' in exprs
        assert 'zm_monitor_mmap_signal[1m]' in exprs
        assert 'zm_monitor_mmap_active[1m]' in exprs
