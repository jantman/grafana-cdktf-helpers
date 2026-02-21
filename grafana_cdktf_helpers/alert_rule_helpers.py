from imports.grafana.rule_group import (
    RuleGroupRule, RuleGroupRuleData, RuleGroupRuleDataRelativeTimeRange
)
from typing import TYPE_CHECKING, Dict, Optional, Literal
import json

if TYPE_CHECKING:
    from grafana_cdktf_helpers.stack import BaseStack


class MetricThresholdRule:
    """
    One rule for a RuleGroup, that alerts when a given metric crosses a single
    static threshold.
    """

    def __init__(
        self, stack: 'BaseStack', name: str, expr: str, reducer: str,
        threshold: float, threshold_type: str, annotations: Dict[str, str],
        for_: str = '1m', severity: str = 'warning', from_: int = 600,
        replace_nan_with: Optional[float] = None, interval_ms: int = 5000,
        exemplar: Optional[bool] = True,
        instant_not_range: bool = False,
        extra_labels: Optional[Dict[str, str]] = None,
        no_data_state: str = 'NoData',
        additional_query_expr: Optional[str] = None,
        additional_query_reducer: str = 'last',
        additional_query_threshold: Optional[float] = None,
        additional_query_threshold_type: str = 'gt',
        additional_query_from: Optional[int] = None,
        condition_operator: str = 'and'
    ):
        self.stack: 'BaseStack' = stack
        self.name: str = name
        self.expr: str = expr
        self.reducer: str = reducer
        self.threshold: float = threshold
        self.threshold_type: str = threshold_type
        self.annotations: Dict[str, str] = annotations
        self.for_: str = for_
        self.severity: str = severity
        self.from_: int = from_
        self.replace_nan_with: Optional[float] = replace_nan_with
        self.exemplar: Optional[bool] = exemplar
        self.instant_not_range: bool = instant_not_range
        self.extra_labels: Dict[str, str] = {}
        self.labels: Dict[str, str] = {'Severity': self.severity}
        self.interval_ms: int = interval_ms
        self.no_data_state: str = no_data_state
        self.additional_query_expr: Optional[str] = additional_query_expr
        self.additional_query_reducer: str = additional_query_reducer
        self.additional_query_threshold: Optional[float] = additional_query_threshold
        self.additional_query_threshold_type: str = additional_query_threshold_type
        self.additional_query_from: Optional[int] = additional_query_from or from_
        self.condition_operator: str = condition_operator
        if extra_labels:
            self.extra_labels = extra_labels
            self.labels.update(extra_labels)
        self._rule: Optional[RuleGroupRule] = None

    @property
    def rule(self):
        if self._rule is not None:
            return self._rule

        # Determine if we should use classic conditions or modern alert format
        use_classic_conditions = (
            self.additional_query_expr is not None and
            self.additional_query_threshold is not None
        )

        if use_classic_conditions:
            return self._build_classic_conditions_rule()
        else:
            return self._build_modern_alert_rule()

    def _build_modern_alert_rule(self):
        """Build the traditional 3-stage alert rule (Query -> Reduce -> Threshold)"""
        modelA = {
            "datasource": {
                "type": "prometheus",
                "uid": self.stack.prom.uid
            },
            "editorMode": "code",
            "expr": self.expr,
            "interval": "",
            "intervalMs": self.interval_ms,
            "legendFormat": "__auto",
            "maxDataPoints": 43200,
            "range": True,
            "refId": "A"
        }
        if self.exemplar is not None:
            modelA['exemplar'] = self.exemplar
        if self.instant_not_range:
            modelA['range'] = False
            modelA['instant'] = True
        modelB = {
            "conditions": [
                {
                    "evaluator": {
                        "params": [],
                        "type": "gt"
                    },
                    "operator": {
                        "type": "and"
                    },
                    "query": {
                        "params": [
                            "B"
                        ]
                    },
                    "reducer": {
                        "params": [],
                        "type": "last"
                    },
                    "type": "query"
                }
            ],
            "datasource": {
                "type": "__expr__",
                "uid": "-100"
            },
            "expression": "A",
            "hide": False,
            "intervalMs": 1000,
            "maxDataPoints": 43200,
            "reducer": self.reducer,
            "refId": "B",
            "type": "reduce"
        }
        if self.replace_nan_with is not None:
            modelB['settings'] = {
                'mode': 'replaceNN',
                'replaceWithValue': self.replace_nan_with
            }
        self._rule = RuleGroupRule(
            name=self.name,
            annotations=self.annotations,
            for_=self.for_,
            condition='C',
            exec_err_state='Error',
            no_data_state=self.no_data_state,
            labels=self.labels,
            data=[
                RuleGroupRuleData(
                    datasource_uid=self.stack.prom.uid,
                    query_type='',
                    ref_id='A',
                    relative_time_range=RuleGroupRuleDataRelativeTimeRange(
                        from_=self.from_, to=0
                    ),
                    model=json.dumps(modelA, sort_keys=True, indent=4)
                ),
                RuleGroupRuleData(
                    datasource_uid='-100',
                    query_type='',
                    ref_id='B',
                    relative_time_range=RuleGroupRuleDataRelativeTimeRange(
                        from_=self.from_, to=0
                    ),
                    model=json.dumps(modelB, sort_keys=True, indent=4)
                ),
                RuleGroupRuleData(
                    datasource_uid='-100',
                    query_type='',
                    ref_id='C',
                    relative_time_range=RuleGroupRuleDataRelativeTimeRange(
                        from_=self.from_, to=0
                    ),
                    model=json.dumps({
                        "conditions": [
                            {
                                "evaluator": {
                                    "params": [
                                        self.threshold
                                    ],
                                    "type": self.threshold_type
                                },
                                "operator": {
                                    "type": "and"
                                },
                                "query": {
                                    "params": [
                                        "C"
                                    ]
                                },
                                "reducer": {
                                    "params": [],
                                    "type": "last"
                                },
                                "type": "query"
                            }
                        ],
                        "datasource": {
                            "type": "__expr__",
                            "uid": "-100"
                        },
                        "expression": "B",
                        "hide": False,
                        "intervalMs": 1000,
                        "maxDataPoints": 43200,
                        "refId": "C",
                        "type": "threshold"
                    }, sort_keys=True, indent=4)
                )
            ]
        )
        return self._rule

    def _build_classic_conditions_rule(self):
        """Build a classic conditions rule with two queries and combined evaluation"""
        # Valid aggregation functions for classic conditions
        # Reference: https://grafana.com/docs/grafana/latest/alerting/fundamentals/alert-rules/queries-conditions/
        VALID_CLASSIC_REDUCERS = {
            'avg', 'min', 'max', 'sum', 'count', 'last', 'median',
            'diff', 'diff_abs', 'percent_diff', 'percent_diff_abs', 'count_non_null'
        }

        # Map modern expression reducers to classic condition equivalents
        REDUCER_MAPPING = {
            'mean': 'avg',  # Modern expression uses 'mean', classic conditions use 'avg'
            'min': 'min',
            'max': 'max',
            'last': 'last',
            'sum': 'sum',
            'count': 'count'
        }

        # Map and validate the main reducer
        main_reducer = REDUCER_MAPPING.get(self.reducer, self.reducer)
        if main_reducer not in VALID_CLASSIC_REDUCERS:
            raise ValueError(
                f"Invalid reducer '{self.reducer}' (mapped to '{main_reducer}') for classic conditions. "
                f"Valid options: {sorted(VALID_CLASSIC_REDUCERS)}"
            )

        # Map and validate the additional reducer
        additional_reducer = REDUCER_MAPPING.get(self.additional_query_reducer, self.additional_query_reducer)
        if additional_reducer not in VALID_CLASSIC_REDUCERS:
            raise ValueError(
                f"Invalid additional_query_reducer '{self.additional_query_reducer}' (mapped to '{additional_reducer}') for classic conditions. "
                f"Valid options: {sorted(VALID_CLASSIC_REDUCERS)}"
            )

        # Query A - Original metric
        modelA = {
            "datasource": {
                "type": "prometheus",
                "uid": self.stack.prom.uid
            },
            "editorMode": "code",
            "expr": self.expr,
            "interval": "",
            "intervalMs": self.interval_ms,
            "legendFormat": "__auto",
            "maxDataPoints": 43200,
            "range": True,
            "refId": "A"
        }
        if self.exemplar is not None:
            modelA['exemplar'] = self.exemplar
        if self.instant_not_range:
            modelA['range'] = False
            modelA['instant'] = True

        # Query B - Additional metric
        modelB = {
            "datasource": {
                "type": "prometheus",
                "uid": self.stack.prom.uid
            },
            "editorMode": "code",
            "expr": self.additional_query_expr,
            "interval": "",
            "intervalMs": self.interval_ms,
            "legendFormat": "__auto",
            "maxDataPoints": 43200,
            "range": True,
            "refId": "B"
        }
        if self.exemplar is not None:
            modelB['exemplar'] = self.exemplar
        if self.instant_not_range:
            modelB['range'] = False
            modelB['instant'] = True

        # Classic Conditions - Combines both queries
        modelC = {
            "conditions": [
                {
                    "evaluator": {
                        "params": [self.threshold],
                        "type": self.threshold_type
                    },
                    "operator": {
                        "type": self.condition_operator
                    },
                    "query": {
                        "params": ["A"]
                    },
                    "reducer": {
                        "params": [],
                        "type": main_reducer
                    },
                    "type": "query"
                },
                {
                    "evaluator": {
                        "params": [self.additional_query_threshold],
                        "type": self.additional_query_threshold_type
                    },
                    "operator": {
                        "type": self.condition_operator
                    },
                    "query": {
                        "params": ["B"]
                    },
                    "reducer": {
                        "params": [],
                        "type": additional_reducer
                    },
                    "type": "query"
                }
            ],
            "datasource": {
                "type": "__expr__",
                "uid": "__expr__"
            },
            "expression": "",
            "intervalMs": 1000,
            "maxDataPoints": 43200,
            "refId": "C",
            "type": "classic_conditions"
        }

        self._rule = RuleGroupRule(
            name=self.name,
            annotations=self.annotations,
            for_=self.for_,
            condition='C',
            exec_err_state='Error',
            no_data_state=self.no_data_state,
            labels=self.labels,
            data=[
                RuleGroupRuleData(
                    datasource_uid=self.stack.prom.uid,
                    query_type='',
                    ref_id='A',
                    relative_time_range=RuleGroupRuleDataRelativeTimeRange(
                        from_=self.from_, to=0
                    ),
                    model=json.dumps(modelA, sort_keys=True, indent=4)
                ),
                RuleGroupRuleData(
                    datasource_uid=self.stack.prom.uid,
                    query_type='',
                    ref_id='B',
                    relative_time_range=RuleGroupRuleDataRelativeTimeRange(
                        from_=self.additional_query_from, to=0
                    ),
                    model=json.dumps(modelB, sort_keys=True, indent=4)
                ),
                RuleGroupRuleData(
                    datasource_uid='__expr__',
                    query_type='',
                    ref_id='C',
                    relative_time_range=RuleGroupRuleDataRelativeTimeRange(
                        from_=max(self.from_, self.additional_query_from), to=0
                    ),
                    model=json.dumps(modelC, sort_keys=True, indent=4)
                )
            ]
        )
        return self._rule


class MetricMeanThresholdRule(MetricThresholdRule):
    """
    One rule for a RuleGroup, that alerts when the mean (avg_over_time) of a
    given metric crosses a single static threshold.
    """

    def __init__(
        self, stack: 'BaseStack', name: str, expr: str, threshold: float,
        threshold_type: str, annotations: Dict[str, str], for_: str = '1m',
        severity: str = 'warning', from_: int = 600,
        skip_expr_checks: bool = False, extra_labels: Optional[Dict[str, str]] = None,
        additional_query_expr: Optional[str] = None,
        additional_query_reducer: str = 'last',
        additional_query_threshold: Optional[float] = None,
        additional_query_threshold_type: str = 'gt',
        additional_query_from: Optional[int] = None,
        condition_operator: str = 'and'
    ):
        if not skip_expr_checks:
            assert 'avg_over_time(' in expr or 'sum(' in expr,\
                f"Expression '{expr}' is expected to contain 'avg_over_time('" \
                f" or 'sum('"
        assert threshold_type in ['lt', 'gt']
        reducer = 'mean'
        super().__init__(
            stack=stack, name=name, expr=expr, reducer=reducer,
            threshold=threshold, threshold_type=threshold_type,
            annotations=annotations, for_=for_, severity=severity, from_=from_,
            extra_labels=extra_labels,
            additional_query_expr=additional_query_expr,
            additional_query_reducer=additional_query_reducer,
            additional_query_threshold=additional_query_threshold,
            additional_query_threshold_type=additional_query_threshold_type,
            additional_query_from=additional_query_from,
            condition_operator=condition_operator
        )


class SystemdInactiveUnitRule(MetricMeanThresholdRule):
    """
    A rule that alerts when a systemd unit is not active for a given time.
    """

    def __init__(
        self, stack: 'BaseStack', unit_name: str, hostname: str, for_: str = '1m',
        severity: str = 'warning', from_: int = 600,
        extra_labels: Optional[Dict[str, str]] = None
    ):
        name = f'{unit_name} not active on {hostname} [TF]'
        expr = 'avg_over_time(systemd_unit_state{' \
               f'instance="{hostname}:9558",name="{unit_name}",state="active"' \
               '}' + f'[{for_}])'
        threshold_type = 'lt'
        annotations = {
            "description": f"The systemd unit {unit_name} was not active on {hostname} for at least some of the last {for_}.",
            "summary": f"Systemd unit {unit_name} not Active on {hostname} for {for_}",
        }
        super().__init__(
            stack=stack, name=name, expr=expr,
            threshold=0.9, threshold_type=threshold_type,
            annotations=annotations, for_=for_, severity=severity, from_=from_,
            extra_labels=extra_labels
        )


class MetricMinThresholdRule(MetricThresholdRule):
    """
    One rule for a RuleGroup, that alerts when the min (min_over_time) of a
    given metric crosses a single static threshold.
    """

    def __init__(
        self, stack: 'BaseStack', name: str, expr: str,
        threshold: float, annotations: Dict[str, str],
        for_: str = '1m', severity: str = 'warning', from_: int = 600,
        skip_expr_checks: bool = False, extra_labels: Optional[Dict[str, str]] = None,
        additional_query_expr: Optional[str] = None,
        additional_query_reducer: str = 'last',
        additional_query_threshold: Optional[float] = None,
        additional_query_threshold_type: str = 'gt',
        additional_query_from: Optional[int] = None,
        condition_operator: str = 'and'
    ):
        if not skip_expr_checks:
            assert 'min_over_time(' in expr or 'count(' in expr,\
                f"Expression '{expr}' is expected to contain " \
                f"'min_over_time(' or 'rate('"
        reducer = 'min'
        threshold_type = 'lt'
        super().__init__(
            stack=stack, name=name, expr=expr, reducer=reducer,
            threshold=threshold, threshold_type=threshold_type,
            annotations=annotations, for_=for_, severity=severity, from_=from_,
            extra_labels=extra_labels,
            additional_query_expr=additional_query_expr,
            additional_query_reducer=additional_query_reducer,
            additional_query_threshold=additional_query_threshold,
            additional_query_threshold_type=additional_query_threshold_type,
            additional_query_from=additional_query_from,
            condition_operator=condition_operator
        )


class MetricMaxThresholdRule(MetricThresholdRule):
    """
    One rule for a RuleGroup, that alerts when the max (max_over_time) of a
    given metric crosses a single static threshold.
    """

    def __init__(
        self, stack: 'BaseStack', name: str, expr: str, threshold: float,
        annotations: Dict[str, str], for_: str = '1m',
        severity: str = 'warning', from_: int = 600,
        skip_expr_checks: bool = False, extra_labels: Optional[Dict[str, str]] = None,
        additional_query_expr: Optional[str] = None,
        additional_query_reducer: str = 'last',
        additional_query_threshold: Optional[float] = None,
        additional_query_threshold_type: str = 'gt',
        additional_query_from: Optional[int] = None,
        condition_operator: str = 'and'
    ):
        if not skip_expr_checks:
            assert 'max_over_time(' in expr or 'sum(increase(' in expr,\
                f"Expression '{expr}' is expected to contain 'max_over_time(' " \
                f"or 'sum(increase('"
        reducer = 'max'
        threshold_type = 'gt'
        super().__init__(
            stack=stack, name=name, expr=expr, reducer=reducer,
            threshold=threshold, threshold_type=threshold_type,
            annotations=annotations, for_=for_, severity=severity, from_=from_,
            extra_labels=extra_labels,
            additional_query_expr=additional_query_expr,
            additional_query_reducer=additional_query_reducer,
            additional_query_threshold=additional_query_threshold,
            additional_query_threshold_type=additional_query_threshold_type,
            additional_query_from=additional_query_from,
            condition_operator=condition_operator
        )


class MetricLastThresholdRule(MetricThresholdRule):
    """
    One rule for a RuleGroup, that alerts when the last data point of a
    given metric crosses a single static threshold.
    """

    def __init__(
        self, stack: 'BaseStack', name: str, expr: str, threshold: float, threshold_type: str,
        annotations: Dict[str, str], for_: str = '1m',
        severity: str = 'warning', from_: int = 600,
        skip_expr_checks: bool = False, extra_labels: Optional[Dict[str, str]] = None,
        additional_query_expr: Optional[str] = None,
        additional_query_reducer: str = 'last',
        additional_query_threshold: Optional[float] = None,
        additional_query_threshold_type: str = 'gt',
        additional_query_from: Optional[int] = None,
        condition_operator: str = 'and'
    ):
        reducer = 'last'
        super().__init__(
            stack=stack, name=name, expr=expr, reducer=reducer,
            threshold=threshold, threshold_type=threshold_type,
            annotations=annotations, for_=for_, severity=severity, from_=from_,
            extra_labels=extra_labels,
            additional_query_expr=additional_query_expr,
            additional_query_reducer=additional_query_reducer,
            additional_query_threshold=additional_query_threshold,
            additional_query_threshold_type=additional_query_threshold_type,
            additional_query_from=additional_query_from,
            condition_operator=condition_operator
        )


class BooleanDisappearingSeriesRule(MetricThresholdRule):
    """
    A rule that alerts on a multi-series metric, where 0 is "good" and greater
    than 0 is "bad", and where series may disappear when no longer >0 (and that
    should be treated as a "good" condition).
    """

    def __init__(
        self, stack: 'BaseStack', name: str, metric: str,
        annotations: Dict[str, str], for_: str = '1m',
        severity: str = 'warning', from_: int = 600,
        extra_labels: Optional[Dict[str, str]] = None,
        additional_query_expr: Optional[str] = None,
        additional_query_reducer: str = 'last',
        additional_query_threshold: Optional[float] = None,
        additional_query_threshold_type: str = 'gt',
        additional_query_from: Optional[int] = None,
        condition_operator: str = 'and'
    ):
        expr = metric + '[' + for_ + ']'
        reducer = 'max'
        threshold_type = 'gt'
        threshold = 0
        super().__init__(
            stack=stack, name=name, expr=expr, reducer=reducer,
            threshold=threshold, threshold_type=threshold_type,
            annotations=annotations, for_=for_, severity=severity, from_=from_,
            exemplar=False, instant_not_range=True, extra_labels=extra_labels,
            additional_query_expr=additional_query_expr,
            additional_query_reducer=additional_query_reducer,
            additional_query_threshold=additional_query_threshold,
            additional_query_threshold_type=additional_query_threshold_type,
            additional_query_from=additional_query_from,
            condition_operator=condition_operator
        )


class IsHealthySeriesRule(MetricThresholdRule):
    """
    A rule that alerts on a multi-series metric, where 1 is "good" and less
    than 1 is "bad".
    """

    def __init__(
        self, stack: 'BaseStack', name: str, metric: str,
        annotations: Dict[str, str], for_: str = '1m',
        severity: str = 'warning', from_: int = 600,
        threshold: float = 1,
        extra_labels: Optional[Dict[str, str]] = None,
        additional_query_expr: Optional[str] = None,
        additional_query_reducer: str = 'last',
        additional_query_threshold: Optional[float] = None,
        additional_query_threshold_type: str = 'gt',
        additional_query_from: Optional[int] = None,
        condition_operator: str = 'and'
    ):
        expr = metric + '[' + for_ + ']'
        reducer = 'mean'
        threshold_type = 'lt'
        super().__init__(
            stack=stack, name=name, expr=expr, reducer=reducer,
            threshold=threshold, threshold_type=threshold_type,
            annotations=annotations, for_=for_, severity=severity, from_=from_,
            exemplar=False, instant_not_range=True, extra_labels=extra_labels,
            additional_query_expr=additional_query_expr,
            additional_query_reducer=additional_query_reducer,
            additional_query_threshold=additional_query_threshold,
            additional_query_threshold_type=additional_query_threshold_type,
            additional_query_from=additional_query_from,
            condition_operator=condition_operator
        )


class InfoLabelValueRule(MetricThresholdRule):
    """
    A rule that alerts if the value of a specific label is not an expected one,
    used on "info" type metrics (i.e. metrics that are 0 or 1 for varying
    combinations of labels).
    """

    def __init__(
        self, stack: 'BaseStack', name: str, metric: str, metric_label: str,
        expected_label_value: str, metric_selectors: str, item_name: str,
        annotations: Optional[Dict[str, str]] = None,
        summary_prefix: str = '', description_prefix: str = 'The ',
        for_: str = '1s', no_data_state: str = 'OK',
        severity: str = 'warning', from_: int = 600,
        extra_labels: Optional[Dict[str, str]] = None,
        additional_query_expr: Optional[str] = None,
        additional_query_reducer: str = 'last',
        additional_query_threshold: Optional[float] = None,
        additional_query_threshold_type: str = 'gt',
        additional_query_from: Optional[int] = None,
        condition_operator: str = 'and'
    ):
        if annotations is None:
            annotations = {}
        threshold_type = 'gt'
        threshold = 0
        expr = metric + '{'
        if metric_selectors:
            expr += metric_selectors + ','
        expr += f'{metric_label}!="{expected_label_value}"'
        expr += '}'
        if 'description' not in annotations:
            annotations['description'] = (
                f'{description_prefix}{item_name} {metric_label} is not'
                f' {expected_label_value},'
                ' it is {{ $labels.' + metric_label + ' }}'
            )
        if 'summary' not in annotations:
            annotations['summary'] = (
                summary_prefix + ' ' + item_name + ' ' +
                metric_label + ' is {{ $labels.' + metric_label + ' }}'
            )
        super().__init__(
            stack=stack, name=name, expr=expr, reducer='last',
            threshold=threshold, threshold_type=threshold_type,
            annotations=annotations, for_=for_, severity=severity, from_=from_,
            extra_labels=extra_labels, exemplar=None, interval_ms=1000,
            no_data_state=no_data_state,
            additional_query_expr=additional_query_expr,
            additional_query_reducer=additional_query_reducer,
            additional_query_threshold=additional_query_threshold,
            additional_query_threshold_type=additional_query_threshold_type,
            additional_query_from=additional_query_from,
            condition_operator=condition_operator
        )


class MetricChangeRule(MetricThresholdRule):
    """
    One rule for a RuleGroup, that alerts when a metric changes value.
    """

    def __init__(
        self, stack: 'BaseStack', name: str, metric: str,
        annotations: Dict[str, str], for_: str = '1m',
        severity: str = 'warning', from_: int = 600,
        extra_labels: Optional[Dict[str, str]] = None,
        additional_query_expr: Optional[str] = None,
        additional_query_reducer: str = 'last',
        additional_query_threshold: Optional[float] = None,
        additional_query_threshold_type: str = 'gt',
        additional_query_from: Optional[int] = None,
        condition_operator: str = 'and'
    ):
        reducer = 'sum'
        expr = f"increase({metric}[{for_}])"
        threshold = 0
        threshold_type = 'gt'
        super().__init__(
            stack=stack, name=name, expr=expr, reducer=reducer,
            threshold=threshold, threshold_type=threshold_type,
            annotations=annotations, for_=for_, severity=severity, from_=from_,
            extra_labels=extra_labels,
            additional_query_expr=additional_query_expr,
            additional_query_reducer=additional_query_reducer,
            additional_query_threshold=additional_query_threshold,
            additional_query_threshold_type=additional_query_threshold_type,
            additional_query_from=additional_query_from,
            condition_operator=condition_operator
        )
