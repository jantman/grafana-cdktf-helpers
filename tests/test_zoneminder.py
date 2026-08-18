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
