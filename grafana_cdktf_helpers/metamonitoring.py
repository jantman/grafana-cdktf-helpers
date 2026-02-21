"""Shared MetaMonitoring class for CDKTF Grafana projects.

Monitors Prometheus, Alertmanager, and related systemd services.
"""
from typing import TYPE_CHECKING, Optional, List, Dict

from imports.grafana.folder import Folder
from imports.grafana.dashboard import Dashboard
from imports.grafana.rule_group import RuleGroup
from grafana_cdktf_helpers.alert_rule_helpers import (
    MetricMeanThresholdRule, MetricMinThresholdRule, MetricMaxThresholdRule,
    SystemdInactiveUnitRule
)
from grafana_cdktf_helpers.utils import load_dashboard, get_shared_dashboard_path

if TYPE_CHECKING:
    from grafana_cdktf_helpers.stack import BaseStack

DEFAULT_MONITORING_SERVICES = [
    'docker-alertmanager.service',
    'docker-grafana.service',
    'docker-grafanarender.service',
    'docker-loki.service',
    'docker-prometheus.service',
    'docker-promtail.service',
]


class MetaMonitoring:
    """
    Creates MetaMonitoring folder with dashboards and alert rules for
    Prometheus, Alertmanager, and monitoring-stack systemd services.

    Parameters:
        stack: The CDKTF stack.
        monitoring_hostname: Hostname running the monitoring stack
            (e.g. 'titan' or 'palantir').
        monitoring_services: List of systemd service names to monitor.
            Defaults to the 6 standard monitoring-stack Docker services.
        org_id: Optional org_id to pass to RuleGroup constructors.
        disable_provenance: Whether to set disable_provenance on RuleGroups.
        dashboard_dir: Directory containing dashboard JSON files.
            Defaults to the package's bundled dashboards.
        dashboard_replacements: Optional dict of {placeholder: value}
            replacements applied to all dashboard JSON files.
    """

    def __init__(
        self,
        stack: 'BaseStack',
        monitoring_hostname: str,
        monitoring_services: Optional[List[str]] = None,
        org_id: Optional[str] = None,
        disable_provenance: bool = True,
        dashboard_dir: Optional[str] = None,
        dashboard_replacements: Optional[Dict[str, str]] = None,
    ):
        if monitoring_services is None:
            monitoring_services = list(DEFAULT_MONITORING_SERVICES)

        self.folder: Folder = Folder(stack, 'meta-folder', title='MetaMonitoring')

        def _load_dash(name: str) -> str:
            if dashboard_dir:
                path = f'{dashboard_dir}/{name}'
            else:
                path = get_shared_dashboard_path(name)
            return load_dashboard(path, replacements=dashboard_replacements)

        am = _load_dash('alertmanager_dash.json')
        amdash: Dashboard = Dashboard(
            stack, 'alertmanager-dash', folder=self.folder.id, config_json=am
        )
        graf = _load_dash('grafana_metrics_dash.json')
        Dashboard(
            stack, 'grafana-metrics-dash', folder=self.folder.id, config_json=graf
        )
        prom_over = _load_dash('prometheus_overview_dash.json')
        overview: Dashboard = Dashboard(
            stack, 'prom-overview-dash', folder=self.folder.id,
            config_json=prom_over
        )
        prom_stats = _load_dash('prometheus_stats_dash.json')
        Dashboard(
            stack, 'prom-stats-dash', folder=self.folder.id,
            config_json=prom_stats
        )

        # Common RuleGroup kwargs
        rg_base = dict(interval_seconds=60)
        if org_id is not None:
            rg_base['org_id'] = org_id
        if disable_provenance:
            rg_base['disable_provenance'] = True

        # Prometheus rules
        rules = [
            MetricMeanThresholdRule(
                stack=stack,
                name='Prometheus Notification Queue [TF]',
                expr='avg_over_time(prometheus_notifications_queue_length[5m])',
                threshold=0, threshold_type='gt', severity='critical',
                annotations={
                    'description': "The Prometheus notification queue had an average length of {{ printf \"%.2f\" $values.B.Value }} for the past 5 minutes",
                    'summary': "Prometheus notification queue length is {{ printf \"%.2f\" $values.B.Value }}"
                }
            ).rule,
            MetricMinThresholdRule(
                stack=stack,
                name='Prometheus Is Down [TF]',
                expr='min_over_time(up{instance="localhost:9090", job="prometheus"}[1m])',
                threshold=1, severity='critical',
                annotations={
                    "__dashboardUid__": overview.uid,
                    "__panelId__": "1",
                    'description': "Prometheus has been down/offline in the last 5 minutes",
                    'summary': "Prometheus is down"
                }
            ).rule,
            MetricMaxThresholdRule(
                stack=stack,
                name='Prometheus Failed Reloads [TF]',
                expr='max_over_time(prometheus_tsdb_reloads_failures_total{job="prometheus"}[1m])',
                threshold=0, severity='critical',
                annotations={
                    "__dashboardUid__": overview.uid,
                    "__panelId__": "33",
                    'description': "Prometheus has failed to reload in the last minute",
                    'summary': "Prometheus failed to reload"
                }
            ).rule,
            MetricMaxThresholdRule(
                stack=stack,
                name='Prometheus WAL Corruptions [TF]',
                expr='max_over_time(prometheus_tsdb_wal_corruptions_total{job="prometheus"}[1m])',
                threshold=0, severity='critical',
                annotations={
                    'description': "Prometheus has had {{ printf \"%.2f\" $values.B.Value }} WAL corruptions in the last 5 minutes",
                    'summary': "Prometheus WAL corrupt"
                }
            ).rule,
        ]
        RuleGroup(
            stack, 'Prometheus', folder_uid=self.folder.uid,
            name='prometheus-tf', rule=rules, **rg_base
        )

        # Alertmanager rules
        rules = [
            MetricMaxThresholdRule(
                stack=stack,
                name='Alertmanager Failed Notifications [TF]',
                expr='sum(increase(alertmanager_notifications_failed_total{instance=~"alertmanager:9093"}[1m]))',
                threshold=0, severity='critical',
                annotations={
                    '__dashboardUid__': amdash.uid,
                    '__panelId__': "118",
                    'description': "Alertmanager has failed to send {{ printf \"%.2f\" $values.B.Value }} notifications in the last minute",
                    'summary': "Alertmanager failed notifications"
                }
            ).rule,
            MetricMaxThresholdRule(
                stack=stack,
                name='Alertmanager Invalid Alerts [TF]',
                expr='sum(increase(alertmanager_alerts_invalid_total{instance=~"alertmanager:9093"}[1m]))',
                threshold=0, severity='critical',
                annotations={
                    '__dashboardUid__': amdash.uid,
                    '__panelId__': "315",
                    'description': "Alertmanager has {{ printf \"%.2f\" $values.B.Value }} more invalid alerts in the last minute",
                    'summary': "Alertmanager invalid alerts"
                }
            ).rule,
            MetricMinThresholdRule(
                stack=stack,
                name='Alertmanager No Instances [TF]',
                expr='count(alertmanager_build_info)',
                threshold=0, severity='critical',
                annotations={
                    'description': "Alertmanager has stopped running in the last minute",
                    'summary': "Alertmanager not running"
                }
            ).rule,
        ]
        RuleGroup(
            stack, 'Alertmanager', folder_uid=self.folder.uid,
            name='alertmanager-tf', rule=rules, **rg_base
        )

        # Monitoring-stack systemd service rules
        rules = [
            SystemdInactiveUnitRule(stack, svc, monitoring_hostname).rule
            for svc in monitoring_services
        ]
        RuleGroup(
            stack, f'{monitoring_hostname}-systemd',
            folder_uid=self.folder.uid,
            name=f'{monitoring_hostname}-systemd-tf',
            rule=rules, **rg_base
        )
