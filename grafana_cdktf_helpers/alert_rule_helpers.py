from imports.grafana.rule_group import (
    RuleGroupRule, RuleGroupRuleData, RuleGroupRuleDataRelativeTimeRange
)
from typing import TYPE_CHECKING, Dict, List, Optional, Literal
import json

if TYPE_CHECKING:
    from grafana_cdktf_helpers.stack import BaseStack


class InformationalQuery:
    """
    A Prometheus query whose reduced value is exposed to annotation templates
    as ``{{ $values.<ref_id>.Value }}`` but is **not** part of the firing
    condition.

    Each instance contributes two stages to the rule's data list: a Prometheus
    query (refId ``<ref_id>_q``) and a reduce stage (refId ``<ref_id>``).
    """

    def __init__(
        self, ref_id: str, expr: str, reducer: str = 'last',
        from_: int = 600, instant_not_range: bool = False,
    ):
        self.ref_id: str = ref_id
        self.expr: str = expr
        self.reducer: str = reducer
        self.from_: int = from_
        self.instant_not_range: bool = instant_not_range


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
        condition_operator: str = 'and',
        informational_queries: Optional[List[InformationalQuery]] = None,
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
        self.informational_queries: List[InformationalQuery] = (
            self._validate_informational_queries(informational_queries)
        )
        if extra_labels:
            self.extra_labels = extra_labels
            self.labels.update(extra_labels)
        self._rule: Optional[RuleGroupRule] = None

    @staticmethod
    def _validate_informational_queries(
        queries: Optional[List[InformationalQuery]]
    ) -> List[InformationalQuery]:
        if not queries:
            return []
        # Track every refId that will appear in the rule's data list so a
        # caller cannot accidentally collide the reduce-stage refId of one
        # entry with the auto-derived `<ref_id>_q` query-stage refId of
        # another (e.g. ref_id='D' + ref_id='D_q' would both emit a 'D_q'
        # stage). Pre-seed with the firing-condition refIds.
        seen: set = {'A', 'B', 'C'}
        for iq in queries:
            if iq.ref_id.endswith('_q'):
                raise ValueError(
                    f"InformationalQuery ref_id '{iq.ref_id}' must not end "
                    f"with '_q'; that suffix is reserved for the auto-"
                    f"generated query-stage refId."
                )
            q_ref = f"{iq.ref_id}_q"
            if iq.ref_id in seen:
                if iq.ref_id in {'A', 'B', 'C'}:
                    raise ValueError(
                        f"InformationalQuery ref_id '{iq.ref_id}' must not "
                        f"be in {{'A', 'B', 'C'}}; pick a refId starting "
                        f"from 'D'."
                    )
                raise ValueError(
                    f"Duplicate InformationalQuery ref_id '{iq.ref_id}'."
                )
            if q_ref in seen:
                raise ValueError(
                    f"InformationalQuery ref_id '{iq.ref_id}' would derive "
                    f"query-stage refId '{q_ref}', which collides with "
                    f"another refId already in use."
                )
            seen.add(iq.ref_id)
            seen.add(q_ref)
        return list(queries)

    def _build_informational_data_entries(self) -> list:
        """
        Build the (Prometheus query, Reduce) ``RuleGroupRuleData`` pair for
        each ``InformationalQuery`` and return them as a flat list. These are
        appended to the rule's data list after the firing-condition stages,
        and do not influence whether the rule fires.
        """
        entries: list = []
        for iq in self.informational_queries:
            q_ref = f"{iq.ref_id}_q"
            modelQ = {
                "datasource": {
                    "type": "prometheus",
                    "uid": self.stack.prom.uid,
                },
                "editorMode": "code",
                "expr": iq.expr,
                "interval": "",
                "intervalMs": self.interval_ms,
                "legendFormat": "__auto",
                "maxDataPoints": 43200,
                "range": True,
                "refId": q_ref,
            }
            if iq.instant_not_range:
                modelQ['range'] = False
                modelQ['instant'] = True
            modelR = {
                "conditions": [
                    {
                        "evaluator": {"params": [], "type": "gt"},
                        "operator": {"type": "and"},
                        "query": {"params": [iq.ref_id]},
                        "reducer": {"params": [], "type": iq.reducer},
                        "type": "query",
                    }
                ],
                "datasource": {"type": "__expr__", "uid": "-100"},
                "expression": q_ref,
                "hide": False,
                "intervalMs": 1000,
                "maxDataPoints": 43200,
                "reducer": iq.reducer,
                "refId": iq.ref_id,
                "type": "reduce",
            }
            entries.append(
                RuleGroupRuleData(
                    datasource_uid=self.stack.prom.uid,
                    query_type='',
                    ref_id=q_ref,
                    relative_time_range=RuleGroupRuleDataRelativeTimeRange(
                        from_=iq.from_, to=0
                    ),
                    model=json.dumps(modelQ, sort_keys=True, indent=4)
                )
            )
            entries.append(
                RuleGroupRuleData(
                    datasource_uid='-100',
                    query_type='',
                    ref_id=iq.ref_id,
                    relative_time_range=RuleGroupRuleDataRelativeTimeRange(
                        from_=iq.from_, to=0
                    ),
                    model=json.dumps(modelR, sort_keys=True, indent=4)
                )
            )
        return entries

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
        data = [
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
        data.extend(self._build_informational_data_entries())
        self._rule = RuleGroupRule(
            name=self.name,
            annotations=self.annotations,
            for_=self.for_,
            condition='C',
            exec_err_state='Error',
            no_data_state=self.no_data_state,
            labels=self.labels,
            data=data,
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

        data = [
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
        data.extend(self._build_informational_data_entries())
        self._rule = RuleGroupRule(
            name=self.name,
            annotations=self.annotations,
            for_=self.for_,
            condition='C',
            exec_err_state='Error',
            no_data_state=self.no_data_state,
            labels=self.labels,
            data=data,
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
        no_data_state: str = 'NoData',
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
            no_data_state=no_data_state,
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
        no_data_state: str = 'NoData',
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
            no_data_state=no_data_state,
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
        no_data_state: str = 'NoData',
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
            no_data_state=no_data_state,
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
        no_data_state: str = 'NoData',
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
            no_data_state=no_data_state,
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


class LokiCountAlertRule:
    """
    A rule for a RuleGroup that fires when
    ``count_over_time(<logql> [<range_>]) <threshold_type> <threshold>``
    against a Loki datasource.

    Builds the same 3-stage modern alert rule pipeline (Query -> Reduce ->
    Threshold) as ``MetricThresholdRule``, but with a Loki query stage instead
    of a Prometheus one. The default threshold (``> 0``) and ``no_data_state``
    of ``OK`` match the most common log-alerting pattern, where "no log lines"
    is the safe state.

    The consumer must set ``stack.loki`` to a ``DataGrafanaDataSource`` before
    instantiating this class. Loki is not assumed to be present on every
    consuming stack, so it is not auto-created by ``BaseStack``.
    """

    def __init__(
        self, stack: 'BaseStack', name: str, logql: str,
        annotations: Dict[str, str], for_: str = '1m',
        severity: str = 'warning', range_: str = '10m',
        threshold: float = 0, threshold_type: str = 'gt',
        from_: int = 600, no_data_state: str = 'OK',
        extra_labels: Optional[Dict[str, str]] = None,
        interval_ms: int = 1000,
    ):
        self.stack: 'BaseStack' = stack
        self.name: str = name
        self.logql: str = logql
        self.annotations: Dict[str, str] = annotations
        self.for_: str = for_
        self.severity: str = severity
        self.range_: str = range_
        self.threshold: float = threshold
        self.threshold_type: str = threshold_type
        self.from_: int = from_
        self.no_data_state: str = no_data_state
        self.interval_ms: int = interval_ms
        self.extra_labels: Dict[str, str] = {}
        self.labels: Dict[str, str] = {'Severity': self.severity}
        if extra_labels:
            self.extra_labels = extra_labels
            self.labels.update(extra_labels)
        self._rule: Optional[RuleGroupRule] = None

    @property
    def rule(self) -> RuleGroupRule:
        if self._rule is not None:
            return self._rule
        loki_uid = self.stack.loki.uid
        expr = f'count_over_time({self.logql} [{self.range_}])'
        modelA = {
            "datasource": {"type": "loki", "uid": loki_uid},
            "editorMode": "code",
            "expr": expr,
            "hide": False,
            "intervalMs": self.interval_ms,
            "maxDataPoints": 43200,
            "queryType": "range",
            "refId": "A",
        }
        modelB = {
            "conditions": [
                {
                    "evaluator": {"params": [], "type": "gt"},
                    "operator": {"type": "and"},
                    "query": {"params": ["B"]},
                    "reducer": {"params": [], "type": "last"},
                    "type": "query",
                }
            ],
            "datasource": {"type": "__expr__", "uid": "-100"},
            "expression": "A",
            "hide": False,
            "intervalMs": 1000,
            "maxDataPoints": 43200,
            "reducer": "max",
            "refId": "B",
            "type": "reduce",
        }
        modelC = {
            "conditions": [
                {
                    "evaluator": {
                        "params": [self.threshold],
                        "type": self.threshold_type,
                    },
                    "operator": {"type": "and"},
                    "query": {"params": ["C"]},
                    "reducer": {"params": [], "type": "last"},
                    "type": "query",
                }
            ],
            "datasource": {"type": "__expr__", "uid": "-100"},
            "expression": "B",
            "hide": False,
            "intervalMs": 1000,
            "maxDataPoints": 43200,
            "refId": "C",
            "type": "threshold",
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
                    datasource_uid=loki_uid,
                    query_type='range',
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
                    model=json.dumps(modelC, sort_keys=True, indent=4)
                )
            ]
        )
        return self._rule


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


class OpenPinAlertRule(MetricLastThresholdRule):
    """
    Alert when an ESP32 GPIO pin (exported via ``gpio_pin_is_on``) holds at 0
    for ``for_`` (default 1 hour).

    Encodes the "door / window left open" pattern: a pin reading of 1 means
    closed, 0 means open. The rule fires when the last value is less than 1
    for the configured ``for_`` duration. ``no_data_state`` is ``OK`` so a
    momentarily missing series will not page.
    """

    def __init__(
        self, stack: 'BaseStack', instance: str, pin_name: str, title: str,
        trigger_verb: str = 'open', resolve_verb: str = 'closed',
        action_verb: str = 'close', for_: str = '1h',
        from_: int = 600, severity: str = 'warning',
        extra_labels: Optional[Dict[str, str]] = None,
    ):
        labels = {'alert_class': 'door', 'slack_template': 'summary'}
        if extra_labels:
            labels.update(extra_labels)
        annotations = {
            'summary': f'{title} has been {trigger_verb} for over {for_}',
            'description': (
                f'The {title} ({instance} pin {pin_name}) has been '
                f'{trigger_verb} for over {for_}. Please {action_verb} it!'
            ),
            'resolution': f'{title} is now {resolve_verb}. Thank you!',
        }
        super().__init__(
            stack=stack, name=f'{title} {trigger_verb} [TF]',
            expr=f'gpio_pin_is_on{{instance="{instance}",pin_name="{pin_name}"}}',
            threshold=1, threshold_type='lt',
            annotations=annotations, for_=for_, from_=from_,
            severity=severity, no_data_state='OK',
            extra_labels=labels,
        )
