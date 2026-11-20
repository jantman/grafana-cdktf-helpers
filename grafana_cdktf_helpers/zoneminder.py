"""Shared ZoneMinder monitoring class for CDKTF Grafana projects."""
from typing import TYPE_CHECKING, Optional

from imports.grafana.rule_group import RuleGroup
from grafana_cdktf_helpers.alert_rule_helpers import (
    MetricLastThresholdRule, MetricMaxThresholdRule, MetricMeanThresholdRule,
    MetricMinThresholdRule, IsHealthySeriesRule, BooleanDisappearingSeriesRule,
    SystemdInactiveUnitRule,
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

    The opt-in ZMES websocket alert defaults to ``max`` over a 5-minute
    window, which makes a *single* slow response own the alert for the whole
    window and then clear -- a flapping shape, not a sustained-slowness one.
    The ``zmes_websocket_*`` parameters exist to retune that per site: set
    ``zmes_websocket_aggregation='mean'`` with a longer ``zmes_websocket_from``
    to alert on sustained latency instead of on isolated spikes. Defaults are
    unchanged from before those parameters existed.

    ``monitor_for`` and ``restart_for`` set the pending duration of the
    per-monitor health rules (connected, signal, active, capture FPS, image
    size, heartbeat, last read/write) and of the two restart rules (ZMC
    Uptime, Startup Time). A camera that reboots itself takes a couple of
    minutes to come back, but the restart rules stay true for ~12 minutes
    afterwards (uptime < 360s, reduced over a 5-minute range) and the
    last read/write rules for ~6.5 minutes. Raise these to stop alerting on
    a single short reboot while still catching a dead camera or a restart
    loop. Defaults are unchanged from before these parameters existed.

    zm-exporter reads each monitor's mmap segment by joining the zm
    container's IPC namespace. If the zm container is restarted and the
    exporter is not, the exporter stays attached to the dead namespace and
    reports frozen mmap values, while the API-derived metrics (connected,
    capture FPS) stay healthy. ``ZM Exporter mmap View Stale`` fires once per
    ZM host when any connected monitor reports capture FPS > 0 while its mmap
    heartbeat is older than ``exporter_stale_heartbeat_threshold`` seconds.
    While that holds, the Heartbeat Age, Last Read Time and Last Write Time
    rules for that host read 0 instead of their frozen ages, so one alert
    replaces one per monitor per rule. A single monitor that is genuinely
    stuck (capture FPS 0 or disconnected) does not meet the stale condition,
    so those rules still fire for it.
    """

    def __init__(
        self, stack: 'BaseStack', hostname: str,
        folder_id: str, folder_uid: str,
        dashboard_uid: str,
        ignore_monitor_names: Optional[list[str]] = None,
        enable_zmes_websocket_alerts: bool = False,
        zmes_websocket_threshold: float = 0.5,
        zmes_websocket_aggregation: str = 'max',
        zmes_websocket_from: int = 300,
        zmes_websocket_for: str = '1m',
        enable_audio_alerts: bool = False,
        exporter_query_time_threshold: int = 5,
        capture_fps_threshold: int = 8,
        image_size_threshold: int = 8294400,
        heartbeat_age_threshold: int = 5,
        last_read_time_threshold: int = 5,
        last_write_time_threshold: int = 5,
        systemd_services: Optional[list[str]] = None,
        org_id: Optional[str] = None,
        monitor_for: str = '1m',
        restart_for: str = '1m',
        exporter_stale_heartbeat_threshold: int = 60,
    ):
        if ignore_monitor_names is None:
            ignore_monitor_names = []
        ignore_mon = '|'.join(ignore_monitor_names) if ignore_monitor_names else ''
        mon_filter = '{name!~"' + ignore_mon + '"}' if ignore_mon else ''

        # Per ZM host, when zm-exporter's mmap view is stale: the number of
        # connected, capturing (DB/API) monitors, if every one of them has a
        # stale mmap heartbeat; otherwise 0. An exporter attached to a dead zm
        # IPC namespace freezes every monitor's mmap at once, while a single
        # hung zmc can leave its own DB row saying Connected with FPS > 0, so
        # one stale monitor out of N is a camera problem, not an exporter one,
        # and must not close the gate below. The `bool` comparisons keep every
        # monitor in both sums (as 0 or 1), so this is 0, not empty, when
        # healthy and the rule does not read as NoData. Arithmetic also drops
        # __name__, so $values.B carries only the instance label.
        hb_metric = 'zm_monitor_mmap_heartbeat_time_age_seconds' + mon_filter
        capturing = (
            '(zm_monitor_capture_fps' + mon_filter + ' > bool 0)'
            ' * on(instance, id) (zm_monitor_connected' + mon_filter
            + ' == bool 1)'
        )
        stale_count = (
            f'sum by (instance) (({hb_metric}'
            f' > bool {exporter_stale_heartbeat_threshold})'
            f' * on(instance, id) {capturing})'
        )
        capturing_count = (
            f'sum by (instance) (clamp({hb_metric}, 1, 1)'
            f' * on(instance, id) {capturing})'
        )
        exporter_stale = (
            f'({stale_count} * ({stale_count} == bool {capturing_count}))'
        )

        # How long the gate stays closed after the stale condition clears.
        # On recovery the per-monitor expressions' avg_over_time([1m]) still
        # holds frozen ages (~4e5 s after 5 days) for up to 1m, and their
        # MetricMean reducer averages them over from_=300s. The gate is
        # applied per point of that range query, so ~90s (the 1m window plus
        # the 30s subquery step) would strictly suffice; holding for the full
        # 1m + 300s also covers the reduced value, should the rule ever be
        # evaluated as an instant mean, at the cost of at most 6 extra minutes
        # of suppression after a stale period that already lasted hours.
        stale_hold = '6m'

        def gate_on_exporter_stale(expr: str) -> str:
            # While the exporter's mmap view is stale on a host, and for
            # stale_hold after it clears, read that host's monitors as 0
            # instead of dropping them: an empty result would put the whole
            # rule in NoData. `or` only adds the `* 0` series for label sets
            # the `unless` removed.
            return (
                f'(({expr} unless on(instance)'
                f' (max_over_time({exporter_stale}[{stale_hold}:30s]) > 0))'
                f' or ({expr} * 0))'
            )

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
                window='1m', for_=monitor_for,
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
                name='ZM Monitor Capture FPS', for_=monitor_for,
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
                name='ZM Monitor ZMC Uptime', for_=restart_for,
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
                name='ZM Monitor Startup Time', for_=restart_for,
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
                name='ZM Monitor Image Size', for_=monitor_for,
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
                window='1m', for_=monitor_for,
                metric='zm_monitor_mmap_active' + mon_filter,
                annotations={
                    "summary": "ZM monitor {{ $values.B.Labels.name }} is not active (MMAP)",
                },
            ).rule,
            # 11. ZM Monitor Signal
            IsHealthySeriesRule(
                stack, extra_labels={'dashboard': 'ZM'},
                name="ZM Monitor Signal",
                window='1m', for_=monitor_for,
                metric='zm_monitor_mmap_signal' + mon_filter,
                annotations={
                    "summary": "ZM monitor {{ $values.B.Labels.name }} has no signal (MMAP)",
                },
            ).rule,
            # 12. ZM Monitor Heartbeat Age
            MetricMeanThresholdRule(
                stack,
                name='ZM Monitor Heartbeat Age', for_=monitor_for,
                expr=gate_on_exporter_stale(
                    'avg_over_time(zm_monitor_mmap_heartbeat_time_age_seconds' + mon_filter + '[1m])'
                ),
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
                name='ZM Monitor Last Read Time', for_=monitor_for,
                expr=gate_on_exporter_stale(
                    'avg_over_time(zm_monitor_mmap_last_read_time_age_seconds' + mon_filter + '[1m])'
                ),
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
                name='ZM Monitor Last Write Time', for_=monitor_for,
                expr=gate_on_exporter_stale(
                    'avg_over_time(zm_monitor_mmap_last_write_time_age_seconds' + mon_filter + '[1m])'
                ),
                threshold=last_write_time_threshold,
                threshold_type='gt', from_=300,
                annotations={
                    "__dashboardUid__": dashboard_uid,
                    "__panelId__": "41",
                    "summary": "ZM Monitor Last Write Time is high",
                    "description": "ZM Monitor {{ $values.B.Labels.name }} average Last Write Time was {{ printf \"%.2f\" $values.B.Value }} seconds in the last 5 minutes",
                },
            ).rule,
            # 15. ZM Exporter mmap View Stale
            MetricLastThresholdRule(
                stack,
                name='ZM Exporter mmap View Stale', for_=monitor_for,
                expr=exporter_stale,
                threshold=0, threshold_type='gt', from_=300,
                annotations={
                    "__dashboardUid__": dashboard_uid,
                    "__panelId__": "39",
                    "summary": "ZM Exporter mmap view is stale on {{ $values.B.Labels.instance }}",
                    "description": (
                        "All {{ printf \"%.0f\" $values.B.Value }} capturing"
                        " ZM monitor(s) on {{ $values.B.Labels.instance }}"
                        " have an mmap heartbeat over"
                        f" {exporter_stale_heartbeat_threshold} seconds old."
                        " zm-exporter is likely attached to a stale zm IPC"
                        " namespace (zm container restarted without it)."
                        " Restart it on the ZM host:"
                        " systemctl restart docker-zm-exporter"
                    ),
                },
            ).rule,
        ]

        # === Opt-in rules ===
        if enable_zmes_websocket_alerts:
            if zmes_websocket_aggregation not in ('max', 'mean'):
                raise ValueError(
                    "zmes_websocket_aggregation must be 'max' or 'mean', not "
                    f"{zmes_websocket_aggregation!r}"
                )
            ws_mean = zmes_websocket_aggregation == 'mean'
            ws_over_time = 'avg_over_time' if ws_mean else 'max_over_time'
            # 'maximum', not 'max', so the default rule's annotation text is
            # byte-identical to what it was before this was parameterized --
            # otherwise every existing consumer gets a cosmetic Terraform diff.
            ws_word = 'mean' if ws_mean else 'maximum'
            ws_window_min = zmes_websocket_from // 60
            ws_kwargs = dict(
                name='ZMES Websocket Response Time',
                expr=(
                    f'{ws_over_time}('
                    'zm_zmes_websocket_response_time_seconds{status="Success"}'
                    '[1m])'
                ),
                threshold=zmes_websocket_threshold,
                from_=zmes_websocket_from, for_=zmes_websocket_for,
                annotations={
                    "__dashboardUid__": dashboard_uid,
                    "__panelId__": "2",
                    "summary": "ZMES Websocket response time is high",
                    "description":
                        f"ZMES websocket {ws_word} response"
                        ' time was {{ printf "%.2f" $values.B.Value }} seconds'
                        f' in the last {ws_window_min} minutes',
                },
            )
            if ws_mean:
                ws_rule = MetricMeanThresholdRule(
                    stack, threshold_type='gt', **ws_kwargs
                )
            else:
                ws_rule = MetricMaxThresholdRule(stack, **ws_kwargs)
            rules.append(ws_rule.rule)
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
