"""Shared ZoneMinder monitoring class for CDKTF Grafana projects."""
from typing import TYPE_CHECKING, Optional

from imports.grafana.rule_group import RuleGroup
from grafana_cdktf_helpers.alert_rule_helpers import (
    MetricMaxThresholdRule, MetricMeanThresholdRule, MetricMinThresholdRule,
    IsHealthySeriesRule, BooleanDisappearingSeriesRule, SystemdInactiveUnitRule
)

if TYPE_CHECKING:
    from grafana_cdktf_helpers.stack import BaseStack


class ZoneMinder:
    """
    Creates ZoneMinder alert rules for monitoring ZM daemon health,
    per-monitor metrics, and associated systemd services.

    This is the shared base class. Consuming projects create a folder,
    dashboard, and then instantiate ZoneMinder with the dashboard UID
    for annotation links.
    """

    def __init__(
        self, stack: 'BaseStack', hostname: str,
        folder_id: str, folder_uid: str,
        dashboard_uid: str,
        ignore_monitor_names: Optional[list[str]] = None,
        enable_zmes_websocket_alerts: bool = False,
        enable_audio_alerts: bool = False,
        exporter_query_time_threshold: int = 5,
        capture_fps_threshold: int = 8,
        image_size_threshold: int = 8294400,
        heartbeat_age_threshold: int = 5,
        last_read_time_threshold: int = 5,
        last_write_time_threshold: int = 5,
        systemd_services: Optional[list[str]] = None,
        org_id: Optional[str] = None,
    ):
        if ignore_monitor_names is None:
            ignore_monitor_names = []
        ignore_mon = '|'.join(ignore_monitor_names) if ignore_monitor_names else ''
        mon_filter = '{name!~"' + ignore_mon + '"}' if ignore_mon else ''

        if systemd_services is None:
            systemd_services = [
                'docker-zm.service',
                'docker-zm-exporter.service',
                'docker-zoneminder-loki.service',
            ]

        # === Core alert rules (always present) ===
        rules = [
            # 1. ZM Daemon Check
            IsHealthySeriesRule(
                stack, extra_labels={'dashboard': 'ZM'},
                name="ZM Daemon Check", metric='zm_daemon_check',
                annotations={
                    "__dashboardUid__": dashboard_uid,
                    "__panelId__": "1",
                    "summary": "ZM daemon check is not running",
                    "description": "ZM daemon check reported {{ printf \"%.2f\" $values.B.Value }} in the last minute",
                },
            ).rule,
            # 2. ZM Exporter Query Time
            MetricMeanThresholdRule(
                stack,
                name='ZM Exporter Query Time',
                expr='avg_over_time(zm_query_time_seconds[5m])',
                threshold=exporter_query_time_threshold,
                threshold_type='gt', from_=3600,
                annotations={
                    "__dashboardUid__": dashboard_uid,
                    "__panelId__": "3",
                    "summary": "ZM Exporter query time is high",
                    "description": "ZM exporter mean query time was {{ printf \"%.2f\" $values.B.Value }} seconds for the last 5 minutes",
                },
            ).rule,
            # 3. ZM Monitor Enabled
            IsHealthySeriesRule(
                stack, extra_labels={'dashboard': 'ZM'},
                name="ZM Monitor Enabled",
                metric='zm_monitor_enabled' + mon_filter,
                annotations={
                    "__dashboardUid__": dashboard_uid,
                    "__panelId__": "4",
                    "summary": "ZM monitor {{ $values.B.Labels.name }} is not enabled",
                },
            ).rule,
            # 4. ZM Monitor Function not None
            BooleanDisappearingSeriesRule(
                stack, extra_labels={'dashboard': 'ZM'},
                name="ZM Monitor Function not None",
                metric='zm_monitor_function{zm_monitor_function="None"'
                       + (', name!~"' + ignore_mon + '"' if ignore_mon else '')
                       + '}',
                annotations={
                    "summary": "ZM monitor {{ $values.B.Labels.name }} has function set to None",
                },
            ).rule,
            # 5. ZM Monitor Connected
            IsHealthySeriesRule(
                stack, extra_labels={'dashboard': 'ZM'},
                name="ZM Monitor Connected",
                metric='zm_monitor_connected' + mon_filter,
                annotations={
                    "__dashboardUid__": dashboard_uid,
                    "__panelId__": "19",
                    "summary": "ZM monitor {{ $values.B.Labels.name }} is not connected",
                },
            ).rule,
            # 6. ZM Monitor Capture FPS
            MetricMeanThresholdRule(
                stack,
                name='ZM Monitor Capture FPS',
                expr='avg_over_time(zm_monitor_capture_fps' + mon_filter + '[1m])',
                threshold=capture_fps_threshold,
                threshold_type='lt', from_=300,
                annotations={
                    "__dashboardUid__": dashboard_uid,
                    "__panelId__": "33",
                    "summary": "ZM Monitor {{ $values.B.Labels.name }} low Capture FPS",
                    "description": "ZM Monitor {{ $values.B.Labels.name }} average capture FPS was {{ printf \"%.2f\" $values.B.Value }} FPS in the last 5 minutes",
                },
            ).rule,
            # 7. ZM Monitor ZMC Uptime
            MetricMinThresholdRule(
                stack,
                name='ZM Monitor ZMC Uptime',
                expr='min_over_time(zm_monitor_mmap_startup_time_age_seconds' + mon_filter + '[1m])',
                threshold=360, from_=300,
                annotations={
                    "summary": "ZM Monitor {{ $values.B.Labels.name }} restarted",
                    "description": "ZM Monitor {{ $values.B.Labels.name }} startup time age was {{ printf \"%.2f\" $values.B.Value }} seconds in the last 5 minutes",
                },
            ).rule,
            # 8. ZM Monitor Startup Time
            MetricMinThresholdRule(
                stack,
                name='ZM Monitor Startup Time',
                expr='min_over_time(zm_monitor_zmc_uptime_seconds' + mon_filter + '[1m])',
                threshold=360, from_=300,
                annotations={
                    "summary": "ZM Monitor {{ $values.B.Labels.name }} ZMC restarted",
                    "description": "ZM Monitor {{ $values.B.Labels.name }} ZMC uptime was {{ printf \"%.2f\" $values.B.Value }} seconds in the last 5 minutes",
                },
            ).rule,
            # 9. ZM Monitor Image Size
            MetricMinThresholdRule(
                stack,
                name='ZM Monitor Image Size',
                expr='min_over_time(zm_monitor_mmap_imagesize' + mon_filter + '[1m])',
                threshold=image_size_threshold, from_=300,
                annotations={
                    "summary": "ZM Monitor {{ $values.B.Labels.name }} low image size",
                    "description": "ZM Monitor {{ $values.B.Labels.name }} image size was {{ printf \"%.2f\" $values.B.Value }} in the last 5 minutes",
                },
            ).rule,
            # 10. ZM Monitor Active
            IsHealthySeriesRule(
                stack, extra_labels={'dashboard': 'ZM'},
                name="ZM Monitor Active",
                metric='zm_monitor_mmap_active' + mon_filter,
                annotations={
                    "summary": "ZM monitor {{ $values.B.Labels.name }} is not active (MMAP)",
                },
            ).rule,
            # 11. ZM Monitor Signal
            IsHealthySeriesRule(
                stack, extra_labels={'dashboard': 'ZM'},
                name="ZM Monitor Signal",
                metric='zm_monitor_mmap_signal' + mon_filter,
                annotations={
                    "summary": "ZM monitor {{ $values.B.Labels.name }} has no signal (MMAP)",
                },
            ).rule,
            # 12. ZM Monitor Heartbeat Age
            MetricMeanThresholdRule(
                stack,
                name='ZM Monitor Heartbeat Age',
                expr='avg_over_time(zm_monitor_mmap_heartbeat_time_age_seconds' + mon_filter + '[1m])',
                threshold=heartbeat_age_threshold,
                threshold_type='gt', from_=300,
                annotations={
                    "__dashboardUid__": dashboard_uid,
                    "__panelId__": "39",
                    "summary": "ZM Monitor Heartbeat Age is high",
                    "description": "ZM Monitor {{ $values.B.Labels.name }} average Heartbeat Age was {{ printf \"%.2f\" $values.B.Value }} seconds in the last 5 minutes",
                },
            ).rule,
            # 13. ZM Monitor Last Read Time
            MetricMeanThresholdRule(
                stack,
                name='ZM Monitor Last Read Time',
                expr='avg_over_time(zm_monitor_mmap_last_read_time_age_seconds' + mon_filter + '[1m])',
                threshold=last_read_time_threshold,
                threshold_type='gt', from_=300,
                annotations={
                    "__dashboardUid__": dashboard_uid,
                    "__panelId__": "40",
                    "summary": "ZM Monitor Last Read Time is high",
                    "description": "ZM Monitor {{ $values.B.Labels.name }} average Last Read Time was {{ printf \"%.2f\" $values.B.Value }} seconds in the last 5 minutes",
                },
            ).rule,
            # 14. ZM Monitor Last Write Time
            MetricMeanThresholdRule(
                stack,
                name='ZM Monitor Last Write Time',
                expr='avg_over_time(zm_monitor_mmap_last_write_time_age_seconds' + mon_filter + '[1m])',
                threshold=last_write_time_threshold,
                threshold_type='gt', from_=300,
                annotations={
                    "__dashboardUid__": dashboard_uid,
                    "__panelId__": "41",
                    "summary": "ZM Monitor Last Write Time is high",
                    "description": "ZM Monitor {{ $values.B.Labels.name }} average Last Write Time was {{ printf \"%.2f\" $values.B.Value }} seconds in the last 5 minutes",
                },
            ).rule,
        ]

        # === Opt-in rules ===
        if enable_zmes_websocket_alerts:
            rules.append(
                MetricMaxThresholdRule(
                    stack,
                    name='ZMES Websocket Response Time',
                    expr='max_over_time(zm_zmes_websocket_response_time_seconds{status="Success"}[1m])',
                    threshold=0.5, from_=300,
                    annotations={
                        "__dashboardUid__": dashboard_uid,
                        "__panelId__": "2",
                        "summary": "ZMES Websocket response time is high",
                        "description": "ZMES websocket maximum response time was {{ printf \"%.2f\" $values.B.Value }} seconds in the last 5 minutes",
                    },
                ).rule,
            )
        if enable_audio_alerts:
            rules.extend([
                MetricMinThresholdRule(
                    stack,
                    name='ZM Monitor Audio Channels',
                    expr='min_over_time(zm_monitor_mmap_audio_channels' + mon_filter + '[1m])',
                    threshold=1, from_=300,
                    annotations={
                        "summary": "ZM Monitor {{ $values.B.Labels.name }} no audio",
                        "description": "ZM Monitor {{ $values.B.Labels.name }} audio channels was {{ printf \"%.2f\" $values.B.Value }} in the last 5 minutes",
                    },
                ).rule,
                MetricMinThresholdRule(
                    stack,
                    name='ZM Monitor Audio Frequency',
                    expr='min_over_time(zm_monitor_mmap_audio_frequency' + mon_filter + '[1m])',
                    threshold=6000, from_=300,
                    annotations={
                        "summary": "ZM Monitor {{ $values.B.Labels.name }} no audio frequency",
                        "description": "ZM Monitor {{ $values.B.Labels.name }} audio frequency was {{ printf \"%.2f\" $values.B.Value }} in the last 5 minutes",
                    },
                ).rule,
            ])

        # ZM alert rule group
        rg_kwargs = dict(
            folder_uid=folder_uid, name='zm-tf',
            interval_seconds=60, rule=rules, disable_provenance=True
        )
        if org_id is not None:
            rg_kwargs['org_id'] = org_id
        RuleGroup(stack, 'zm', **rg_kwargs)

        # === Systemd service rules ===
        systemd_rules = [
            SystemdInactiveUnitRule(stack, svc, hostname).rule
            for svc in systemd_services
        ]
        rg_kwargs = dict(
            folder_uid=folder_uid, name='zm-systemd-tf',
            interval_seconds=60, rule=systemd_rules, disable_provenance=True
        )
        if org_id is not None:
            rg_kwargs['org_id'] = org_id
        RuleGroup(stack, 'zm-systemd', **rg_kwargs)
