"""Tests for grafana_cdktf_helpers.alert_rule_helpers."""
import json
from unittest.mock import MagicMock

import pytest

from grafana_cdktf_helpers import alert_rule_helpers
from grafana_cdktf_helpers.alert_rule_helpers import LokiCountAlertRule


@pytest.fixture
def stack():
    s = MagicMock()
    s.loki.uid = 'loki-uid-xyz'
    s.prom.uid = 'prom-uid-abc'
    return s


@pytest.fixture(autouse=True)
def reset_rule_group_mocks():
    """Reset RuleGroupRule / RuleGroupRuleData mocks between tests so
    .call_args inspection isn't polluted by other tests."""
    alert_rule_helpers.RuleGroupRule.reset_mock()
    alert_rule_helpers.RuleGroupRuleData.reset_mock()
    alert_rule_helpers.RuleGroupRuleDataRelativeTimeRange.reset_mock()
    yield


def _rule_kwargs():
    return alert_rule_helpers.RuleGroupRule.call_args.kwargs


def _data_models_by_ref_id():
    """Return {ref_id: parsed_model_dict} for every RuleGroupRuleData call."""
    out = {}
    for call in alert_rule_helpers.RuleGroupRuleData.call_args_list:
        kw = call.kwargs
        out[kw['ref_id']] = json.loads(kw['model'])
    return out


def _data_kwargs_by_ref_id():
    """Return {ref_id: kwargs} for every RuleGroupRuleData call."""
    return {
        call.kwargs['ref_id']: call.kwargs
        for call in alert_rule_helpers.RuleGroupRuleData.call_args_list
    }


class TestLokiCountAlertRule:

    def test_required_args_only(self, stack):
        rule_obj = LokiCountAlertRule(
            stack=stack, name='my-alert',
            logql='{job="systemd"} |= "I/O error"',
            annotations={'summary': 'kernel I/O error'},
        )
        # accessing .rule triggers construction
        result = rule_obj.rule
        assert result is alert_rule_helpers.RuleGroupRule.return_value

        kw = _rule_kwargs()
        assert kw['name'] == 'my-alert'
        assert kw['annotations'] == {'summary': 'kernel I/O error'}
        assert kw['for_'] == '1m'
        assert kw['condition'] == 'C'
        assert kw['exec_err_state'] == 'Error'
        assert kw['no_data_state'] == 'OK'
        assert kw['labels'] == {'Severity': 'warning'}

        # 3 data entries: A (loki), B & C (__expr__)
        data_kw = _data_kwargs_by_ref_id()
        assert set(data_kw.keys()) == {'A', 'B', 'C'}
        assert data_kw['A']['datasource_uid'] == 'loki-uid-xyz'
        assert data_kw['A']['query_type'] == 'range'
        assert data_kw['B']['datasource_uid'] == '-100'
        assert data_kw['B']['query_type'] == ''
        assert data_kw['C']['datasource_uid'] == '-100'
        assert data_kw['C']['query_type'] == ''

    def test_caches_rule(self, stack):
        rule_obj = LokiCountAlertRule(
            stack=stack, name='n', logql='{x="y"}',
            annotations={},
        )
        first = rule_obj.rule
        second = rule_obj.rule
        assert first is second
        # RuleGroupRule should only have been constructed once
        assert alert_rule_helpers.RuleGroupRule.call_count == 1

    def test_query_stage_expr_and_loki_datasource(self, stack):
        LokiCountAlertRule(
            stack=stack, name='n',
            logql='{job="kernel"} |= "EXT4-fs error"',
            annotations={}, range_='15m',
        ).rule
        models = _data_models_by_ref_id()
        a = models['A']
        assert a['expr'] == (
            'count_over_time({job="kernel"} |= "EXT4-fs error" [15m])'
        )
        assert a['queryType'] == 'range'
        assert a['datasource'] == {'type': 'loki', 'uid': 'loki-uid-xyz'}
        assert a['refId'] == 'A'
        # No prometheus-only fields
        assert 'exemplar' not in a
        assert 'legendFormat' not in a
        assert 'range' not in a
        assert 'instant' not in a

    def test_default_range_is_10m(self, stack):
        LokiCountAlertRule(
            stack=stack, name='n', logql='{x="y"}', annotations={},
        ).rule
        a = _data_models_by_ref_id()['A']
        assert a['expr'] == 'count_over_time({x="y"} [10m])'

    def test_reduce_stage_uses_max(self, stack):
        LokiCountAlertRule(
            stack=stack, name='n', logql='{x="y"}', annotations={},
        ).rule
        b = _data_models_by_ref_id()['B']
        assert b['reducer'] == 'max'
        assert b['type'] == 'reduce'
        assert b['datasource'] == {'type': '__expr__', 'uid': '-100'}
        assert b['expression'] == 'A'

    def test_threshold_defaults(self, stack):
        LokiCountAlertRule(
            stack=stack, name='n', logql='{x="y"}', annotations={},
        ).rule
        c = _data_models_by_ref_id()['C']
        assert c['type'] == 'threshold'
        assert c['expression'] == 'B'
        evaluator = c['conditions'][0]['evaluator']
        assert evaluator['params'] == [0]
        assert evaluator['type'] == 'gt'

    def test_custom_threshold_and_threshold_type(self, stack):
        LokiCountAlertRule(
            stack=stack, name='n', logql='{x="y"}', annotations={},
            threshold=5, threshold_type='lt',
        ).rule
        c = _data_models_by_ref_id()['C']
        evaluator = c['conditions'][0]['evaluator']
        assert evaluator['params'] == [5]
        assert evaluator['type'] == 'lt'

    def test_extra_labels_propagate(self, stack):
        LokiCountAlertRule(
            stack=stack, name='n', logql='{x="y"}', annotations={},
            extra_labels={'team': 'storage'},
        ).rule
        kw = _rule_kwargs()
        assert kw['labels'] == {'Severity': 'warning', 'team': 'storage'}

    def test_custom_severity(self, stack):
        LokiCountAlertRule(
            stack=stack, name='n', logql='{x="y"}', annotations={},
            severity='critical',
        ).rule
        kw = _rule_kwargs()
        assert kw['labels']['Severity'] == 'critical'

    def test_for_and_no_data_state_overrides(self, stack):
        LokiCountAlertRule(
            stack=stack, name='n', logql='{x="y"}', annotations={},
            for_='5m', no_data_state='NoData',
        ).rule
        kw = _rule_kwargs()
        assert kw['for_'] == '5m'
        assert kw['no_data_state'] == 'NoData'

    def test_default_interval_ms_is_1000(self, stack):
        LokiCountAlertRule(
            stack=stack, name='n', logql='{x="y"}', annotations={},
        ).rule
        a = _data_models_by_ref_id()['A']
        assert a['intervalMs'] == 1000

    def test_custom_interval_ms(self, stack):
        LokiCountAlertRule(
            stack=stack, name='n', logql='{x="y"}', annotations={},
            interval_ms=15000,
        ).rule
        a = _data_models_by_ref_id()['A']
        assert a['intervalMs'] == 15000

    def test_from_propagated_to_relative_time_range(self, stack):
        LokiCountAlertRule(
            stack=stack, name='n', logql='{x="y"}', annotations={},
            from_=900,
        ).rule
        rtr_calls = (
            alert_rule_helpers.RuleGroupRuleDataRelativeTimeRange.call_args_list
        )
        # Three RuleGroupRuleData entries -> three RelativeTimeRange calls
        assert len(rtr_calls) == 3
        for call in rtr_calls:
            assert call.kwargs == {'from_': 900, 'to': 0}
