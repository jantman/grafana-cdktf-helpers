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


STALE_NAME = 'ZM Exporter mmap View Stale'
MMAP_AGE_METRICS = {
    'ZM Monitor Heartbeat Age': 'zm_monitor_mmap_heartbeat_time_age_seconds',
    'ZM Monitor Last Read Time': 'zm_monitor_mmap_last_read_time_age_seconds',
    'ZM Monitor Last Write Time': 'zm_monitor_mmap_last_write_time_age_seconds',
}


def _query_exprs():
    return [
        json.loads(c.kwargs['model']).get('expr', '')
        for c in alert_rule_helpers.RuleGroupRuleData.call_args_list
    ]


def _stale_expr(threshold=60, mon_filter=''):
    hb = f'zm_monitor_mmap_heartbeat_time_age_seconds{mon_filter}'
    capturing = (
        f'(zm_monitor_capture_fps{mon_filter} > bool 0)'
        f' * on(instance, id) (zm_monitor_connected{mon_filter} == bool 1)'
    )
    stale = (
        f'sum by (instance) (({hb} > bool {threshold})'
        f' * on(instance, id) {capturing})'
    )
    total = (
        f'sum by (instance) (clamp({hb}, 1, 1)'
        f' * on(instance, id) {capturing})'
    )
    return f'({stale} * ({stale} == bool {total}))'


def _gated(base, stale):
    return (
        f'(({base} unless on(instance)'
        f' (max_over_time({stale}[6m:30s]) > 0))'
        f' or ({base} * 0))'
    )


class TestExporterMmapViewStale:

    def test_rule_emitted_with_monitor_for(self, stack):
        _zm(stack, monitor_for='10m')
        kw = _rule_kwargs_by_name()[STALE_NAME]
        assert kw['for_'] == '10m'
        assert kw['labels'] == {'Severity': 'warning'}
        assert 'systemctl restart docker-zm-exporter' in \
            kw['annotations']['description']
        assert 'stale zm IPC namespace' in kw['annotations']['description']
        assert '$values.B.Labels.instance' in kw['annotations']['summary']

    def test_expr_fires_only_when_every_capturing_monitor_is_stale(
        self, stack,
    ):
        # An exporter fault freezes every monitor's mmap at once; one hung
        # zmc whose DB row still says Connected/FPS>0 must not count. The
        # expression is the stale count times (stale count == count of
        # connected, capturing monitors), so it is 0 (not empty) when healthy
        # or when only some monitors are stale, and N when all N are.
        _zm(stack)
        exprs = _query_exprs()
        assert _stale_expr() in exprs
        stale = _stale_expr()
        assert stale.count('> bool 60') == 2
        assert stale.count('clamp(') == 1
        assert ' == bool sum by (instance) (clamp(' in stale

    def test_threshold_and_ignored_monitors(self, stack):
        _zm(
            stack, exporter_stale_heartbeat_threshold=120,
            ignore_monitor_names=['a', 'b'],
        )
        stale = _stale_expr(120, '{name!~"a|b"}')
        assert stale in _query_exprs()
        # The same filter applies to both sides of the comparison.
        for metric in (
            'zm_monitor_mmap_heartbeat_time_age_seconds',
            'zm_monitor_capture_fps', 'zm_monitor_connected',
        ):
            assert f'{metric}{{' in stale
            assert f'{metric} ' not in stale
            assert f'{metric})' not in stale
            assert f'{metric},' not in stale

    def test_mmap_age_rules_are_gated_on_stale_condition(self, stack):
        # The gate holds for 6m after the stale condition clears, covering
        # the 1m avg_over_time window plus the 300s mean reducer, so frozen
        # ages left in those windows cannot fire the rules on recovery.
        _zm(stack)
        exprs = _query_exprs()
        stale = _stale_expr()
        for name, metric in MMAP_AGE_METRICS.items():
            base = f'avg_over_time({metric}[1m])'
            assert _gated(base, stale) in exprs, name
            # The ungated form must no longer be emitted on its own.
            assert base not in exprs, name

    def test_gate_uses_ignored_monitor_filter(self, stack):
        _zm(stack, ignore_monitor_names=['a'])
        exprs = _query_exprs()
        stale = _stale_expr(60, '{name!~"a"}')
        for metric in MMAP_AGE_METRICS.values():
            base = f'avg_over_time({metric}{{name!~"a"}}[1m])'
            assert _gated(base, stale) in exprs, metric

    def test_other_monitor_rules_are_not_gated(self, stack):
        _zm(stack)
        exprs = _query_exprs()
        assert 'avg_over_time(zm_monitor_capture_fps[1m])' in exprs
        assert 'zm_monitor_connected[1m]' in exprs
