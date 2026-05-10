"""Tests for grafana_cdktf_helpers.alert_rule_helpers."""
import json
from unittest.mock import MagicMock

import pytest

from grafana_cdktf_helpers import alert_rule_helpers
from grafana_cdktf_helpers.alert_rule_helpers import (
    BooleanDisappearingSeriesRule,
    InfoLabelValueRule,
    InformationalQuery,
    IsHealthySeriesRule,
    LokiCountAlertRule,
    MetricChangeRule,
    MetricLastThresholdRule,
    MetricMaxThresholdRule,
    MetricMeanThresholdRule,
    MetricMinThresholdRule,
    MetricThresholdRule,
    OpenPinAlertRule,
)


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


class TestInformationalQueries:

    def test_two_informational_queries_appended_to_data(self, stack):
        rule_obj = MetricThresholdRule(
            stack=stack, name='n',
            expr='avg_over_time(foo[5m])', reducer='mean',
            threshold=1.0, threshold_type='gt',
            annotations={'summary': 's'},
            informational_queries=[
                InformationalQuery(
                    ref_id='D', expr='node_load1', reducer='last',
                ),
                InformationalQuery(
                    ref_id='E', expr='node_memory_MemAvailable_bytes',
                    reducer='mean', from_=1200, instant_not_range=True,
                ),
            ],
        )
        rule_obj.rule

        # Firing condition is unchanged
        assert _rule_kwargs()['condition'] == 'C'

        data_kw = _data_kwargs_by_ref_id()
        # 3 firing-condition stages + 2*2 informational stages = 7 entries
        assert set(data_kw.keys()) == {'A', 'B', 'C', 'D_q', 'D', 'E_q', 'E'}

        models = _data_models_by_ref_id()

        # Informational query D — `* 1` is auto-appended to strip the
        # PromQL `__name__` label so Grafana's labels.Contains check
        # populates `$values.D` against the firing-condition frame.
        assert models['D_q']['expr'] == '(node_load1) * 1'
        assert models['D_q']['datasource'] == {
            'type': 'prometheus', 'uid': 'prom-uid-abc'
        }
        assert models['D_q']['range'] is True
        assert models['D']['type'] == 'reduce'
        assert models['D']['reducer'] == 'last'
        assert models['D']['expression'] == 'D_q'
        assert data_kw['D_q']['datasource_uid'] == 'prom-uid-abc'
        assert data_kw['D']['datasource_uid'] == '-100'

        # Informational query E (instant, custom from_)
        assert models['E_q']['expr'] == '(node_memory_MemAvailable_bytes) * 1'
        assert models['E_q'].get('instant') is True
        assert models['E_q']['range'] is False
        assert models['E']['reducer'] == 'mean'
        assert models['E']['expression'] == 'E_q'

        rtr_kwargs = [
            c.kwargs for c in
            alert_rule_helpers.RuleGroupRuleDataRelativeTimeRange.call_args_list
        ]
        # E_q and E both use from_=1200
        assert {'from_': 1200, 'to': 0} in rtr_kwargs

    def test_rejects_reserved_ref_id(self, stack):
        with pytest.raises(ValueError, match="must not be in"):
            MetricThresholdRule(
                stack=stack, name='n',
                expr='avg_over_time(foo[5m])', reducer='mean',
                threshold=1.0, threshold_type='gt', annotations={},
                informational_queries=[
                    InformationalQuery(ref_id='A', expr='x'),
                ],
            )

    def test_rejects_duplicate_ref_ids(self, stack):
        with pytest.raises(ValueError, match="Duplicate"):
            MetricThresholdRule(
                stack=stack, name='n',
                expr='avg_over_time(foo[5m])', reducer='mean',
                threshold=1.0, threshold_type='gt', annotations={},
                informational_queries=[
                    InformationalQuery(ref_id='D', expr='x'),
                    InformationalQuery(ref_id='D', expr='y'),
                ],
            )

    def test_rejects_ref_id_ending_with_q_suffix(self, stack):
        with pytest.raises(ValueError, match="must not end with '_q'"):
            MetricThresholdRule(
                stack=stack, name='n',
                expr='avg_over_time(foo[5m])', reducer='mean',
                threshold=1.0, threshold_type='gt', annotations={},
                informational_queries=[
                    InformationalQuery(ref_id='D_q', expr='x'),
                ],
            )

    def test_rejects_collision_with_derived_query_stage_ref_id(self, stack):
        # ref_id='D' generates a 'D_q' query-stage refId; a *separate*
        # entry whose own ref_id is 'D_q' would emit a second stage with
        # refId 'D_q'. The `_q`-suffix rule covers this case explicitly,
        # but exercise it as a regression test.
        with pytest.raises(ValueError, match="must not end with '_q'"):
            MetricThresholdRule(
                stack=stack, name='n',
                expr='avg_over_time(foo[5m])', reducer='mean',
                threshold=1.0, threshold_type='gt', annotations={},
                informational_queries=[
                    InformationalQuery(ref_id='D', expr='x'),
                    InformationalQuery(ref_id='D_q', expr='y'),
                ],
            )

    @pytest.mark.parametrize('rule_factory', [
        lambda stack: MetricMeanThresholdRule(
            stack=stack, name='n', expr='avg_over_time(foo[5m])',
            threshold=1.0, threshold_type='gt', annotations={},
            informational_queries=[InformationalQuery(ref_id='D', expr='x')],
        ),
        lambda stack: MetricMinThresholdRule(
            stack=stack, name='n', expr='min_over_time(foo[5m])',
            threshold=1.0, annotations={},
            informational_queries=[InformationalQuery(ref_id='D', expr='x')],
        ),
        lambda stack: MetricMaxThresholdRule(
            stack=stack, name='n', expr='max_over_time(foo[5m])',
            threshold=1.0, annotations={},
            informational_queries=[InformationalQuery(ref_id='D', expr='x')],
        ),
        lambda stack: MetricLastThresholdRule(
            stack=stack, name='n', expr='foo',
            threshold=1.0, threshold_type='gt', annotations={},
            informational_queries=[InformationalQuery(ref_id='D', expr='x')],
        ),
        lambda stack: BooleanDisappearingSeriesRule(
            stack=stack, name='n', metric='foo', annotations={},
            informational_queries=[InformationalQuery(ref_id='D', expr='x')],
        ),
        lambda stack: IsHealthySeriesRule(
            stack=stack, name='n', metric='foo', annotations={},
            informational_queries=[InformationalQuery(ref_id='D', expr='x')],
        ),
        lambda stack: InfoLabelValueRule(
            stack=stack, name='n', metric='foo', metric_label='state',
            expected_label_value='ok', metric_selectors='', item_name='thing',
            informational_queries=[InformationalQuery(ref_id='D', expr='x')],
        ),
        lambda stack: MetricChangeRule(
            stack=stack, name='n', metric='foo', annotations={},
            informational_queries=[InformationalQuery(ref_id='D', expr='x')],
        ),
    ])
    def test_subclasses_forward_informational_queries(
        self, stack, rule_factory
    ):
        rule_factory(stack).rule
        data_kw = _data_kwargs_by_ref_id()
        # Whatever the firing-condition stages are, D and D_q must be present.
        assert {'D', 'D_q'}.issubset(data_kw.keys())

    def test_appended_to_classic_conditions_rule(self, stack):
        # Setting both additional_query_expr and additional_query_threshold
        # forces the classic-conditions code path.
        MetricThresholdRule(
            stack=stack, name='n',
            expr='foo', reducer='mean',
            threshold=1.0, threshold_type='gt',
            annotations={},
            additional_query_expr='bar',
            additional_query_threshold=2.0,
            informational_queries=[
                InformationalQuery(ref_id='D', expr='node_load1'),
            ],
        ).rule
        data_kw = _data_kwargs_by_ref_id()
        # Classic conditions still emits A, B, C and adds D_q + D
        assert set(data_kw.keys()) == {'A', 'B', 'C', 'D_q', 'D'}
        # The classic-conditions stage is still the firing condition
        assert _rule_kwargs()['condition'] == 'C'
        models = _data_models_by_ref_id()
        assert models['C']['type'] == 'classic_conditions'
        # And the informational stages look correct (strip_name auto-wrap)
        assert models['D_q']['expr'] == '(node_load1) * 1'
        assert models['D']['type'] == 'reduce'
        assert models['D']['expression'] == 'D_q'
        assert data_kw['D_q']['datasource_uid'] == 'prom-uid-abc'
        assert data_kw['D']['datasource_uid'] == '-100'

    def test_strip_name_default_wraps_expr(self):
        iq = InformationalQuery(ref_id='D', expr='node_load1')
        assert iq.expr == '(node_load1) * 1'
        assert iq.strip_name is True

    def test_strip_name_false_preserves_expr_verbatim(self, stack):
        iq = InformationalQuery(
            ref_id='D',
            expr='label_replace(node_load1, "foo", "bar", "", "")',
            strip_name=False,
        )
        assert iq.expr == (
            'label_replace(node_load1, "foo", "bar", "", "")'
        )
        assert iq.strip_name is False

        # Round-trip through MetricThresholdRule to verify the verbatim
        # expression makes it into the emitted Prometheus query stage.
        MetricThresholdRule(
            stack=stack, name='n',
            expr='avg_over_time(foo[5m])', reducer='mean',
            threshold=1.0, threshold_type='gt', annotations={},
            informational_queries=[iq],
        ).rule
        models = _data_models_by_ref_id()
        assert models['D_q']['expr'] == (
            'label_replace(node_load1, "foo", "bar", "", "")'
        )


class TestOpenPinAlertRule:

    def test_builds_expected_metric_last_threshold_rule(self, stack):
        rule_obj = OpenPinAlertRule(
            stack=stack, instance='esp32-1', pin_name='gpio4',
            title='Garage Door',
        )
        # Stored attributes that flow into the rule construction
        assert rule_obj.expr == (
            'gpio_pin_is_on{instance="esp32-1",pin_name="gpio4"}'
        )
        assert rule_obj.threshold == 1
        assert rule_obj.threshold_type == 'lt'
        assert rule_obj.for_ == '1h'
        assert rule_obj.no_data_state == 'OK'
        assert rule_obj.reducer == 'last'
        assert rule_obj.name == 'Garage Door open [TF]'

        # Default annotation set, including the resolution annotation
        assert rule_obj.annotations['resolution'] == (
            'Garage Door is now closed. Thank you!'
        )
        assert rule_obj.annotations['summary'] == (
            'Garage Door has been open for over 1h'
        )
        assert 'Please close it!' in rule_obj.annotations['description']

        # Default labels include alert_class=door + slack_template=summary
        assert rule_obj.labels['alert_class'] == 'door'
        assert rule_obj.labels['slack_template'] == 'summary'
        assert rule_obj.labels['Severity'] == 'warning'

        # And the rule actually builds.
        rule_obj.rule
        kw = _rule_kwargs()
        assert kw['no_data_state'] == 'OK'
        assert kw['for_'] == '1h'

    def test_extra_labels_merge_with_defaults(self, stack):
        rule_obj = OpenPinAlertRule(
            stack=stack, instance='esp32-1', pin_name='gpio4',
            title='Garage Door',
            extra_labels={'team': 'home'},
        )
        assert rule_obj.labels['alert_class'] == 'door'
        assert rule_obj.labels['team'] == 'home'

    def test_custom_verbs_and_for(self, stack):
        rule_obj = OpenPinAlertRule(
            stack=stack, instance='esp32-1', pin_name='gpio4',
            title='Mailbox', trigger_verb='ajar',
            resolve_verb='shut', action_verb='shut', for_='30m',
        )
        assert rule_obj.name == 'Mailbox ajar [TF]'
        assert rule_obj.for_ == '30m'
        assert rule_obj.annotations['summary'] == (
            'Mailbox has been ajar for over 30m'
        )
        assert rule_obj.annotations['resolution'] == (
            'Mailbox is now shut. Thank you!'
        )
        assert 'Please shut it!' in rule_obj.annotations['description']
