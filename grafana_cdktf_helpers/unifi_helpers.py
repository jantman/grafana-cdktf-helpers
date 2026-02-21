"""Shared UniFi alert rule helper classes for CDKTF Grafana projects."""
from typing import TYPE_CHECKING, Dict

from grafana_cdktf_helpers.alert_rule_helpers import (
    MetricThresholdRule, MetricMinThresholdRule
)

if TYPE_CHECKING:
    from typing import Any


class IntefaceErrorRateRule(MetricThresholdRule):

    def __init__(
        self, unifi: 'Any', name: str, metric: str, base_metric: str,
        threshold: float, panel_id: str,
    ):
        expr = f'(increase({metric}[1m]) / increase({base_metric}[1m])) * 100'
        annotations = {
            "__dashboardUid__": unifi.usg_dash.uid,
            "__panelId__": panel_id,
            "description": "{{ $values.B.Labels.name }} " + name + " percentage was {{ printf \"%.2f\" $values.B.Value }} in the last minute",
            "summary": "UniFi {{ $values.B.Labels.name }} high " + name,
        }
        super().__init__(
            stack=unifi.stack,
            name=f"UniFi UXG {name} Percentage [TF]",
            expr=expr, reducer='mean',
            threshold=threshold, threshold_type='gt', for_='5m',
            annotations=annotations, replace_nan_with=0
        )


class DeviceCountRule(MetricThresholdRule):

    def __init__(
            self, unifi: 'Any', name: str, expr: str,
            threshold: float, annotations: Dict[str, str],
            for_: str = '1m', severity: str = 'warning', from_: int = 600
    ):
        assert 'min_over_time(' in expr or 'count(' in expr
        reducer = 'min'
        threshold_type = 'lt'
        super().__init__(
            stack=unifi.stack, name=name, expr=expr, reducer=reducer,
            threshold=threshold, threshold_type=threshold_type,
            annotations=annotations, for_=for_, severity=severity, from_=from_
        )


class DeviceSubsystemRule(MetricMinThresholdRule):

    def __init__(
        self, unifi: 'Any', subsystem: str, suffix: str,
            threshold: float, severity: str = 'warning'
    ):
        name = f'UniFi Site {subsystem.upper()} {suffix} [TF]'
        expr = 'min_over_time(unpoller_site_' + suffix + '{subsystem="' + subsystem + '"}[1m])'
        annotations = {
            "__dashboardUid__": unifi.site_dash.uid,
            "__panelId__": "38",
            "description": "UniFi site is reporting {{ printf \"%.2f\" $values.B.Value }} " +
                           subsystem.upper() + ' ' + suffix + ", but expected "
                           + str(threshold),
            "summary": "UniFi Site reporting {{ printf \"%.2f\" $values.B.Value }} " +
                       subsystem.upper() + ' ' + suffix,
        }
        super().__init__(
            stack=unifi.stack, name=name, expr=expr, threshold=threshold,
            annotations=annotations, severity=severity
        )


class MissingClientRule(MetricThresholdRule):

    def __init__(self, unifi: 'Any', name: str, mac: str, from_: int = 3600):
        expr = f'sum(increase(unpoller_client_transmit_packets_total{{mac="{mac.lower()}"}}[5m]))'
        annotations = {
            "description": f"Unifi client '{name}' ({mac})" + " has transmitted {{ printf \"%.2f\" $values.B.Value }} packets in the last 10 minutes",
            "summary": f"UniFi Client Missing: {name}",
        }
        super().__init__(
            stack=unifi.stack,
            name=f"UniFi Client {name} Missing [TF]",
            expr=expr, reducer='sum', for_='20m', from_=from_,
            threshold=1, threshold_type='lt',
            annotations=annotations
        )
