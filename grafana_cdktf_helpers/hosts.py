"""Shared Hosts monitoring class for CDKTF Grafana projects.

Creates dashboards and alert rules for host-level monitoring:
systemd services, filesystems, memory, swap, MySQL.
"""
from typing import TYPE_CHECKING, Optional, Dict, List

from imports.grafana.folder import Folder
from imports.grafana.dashboard import Dashboard
from imports.grafana.rule_group import RuleGroup
from grafana_cdktf_helpers.alert_rule_helpers import (
    MetricThresholdRule, MetricMeanThresholdRule, MetricMinThresholdRule,
    MetricMaxThresholdRule
)
from grafana_cdktf_helpers.utils import load_dashboard, get_shared_dashboard_path

if TYPE_CHECKING:
    from grafana_cdktf_helpers.stack import BaseStack


class Hosts:
    """
    Creates Hosts folder with dashboards and alert rules for host-level
    monitoring.

    Parameters:
        stack: The CDKTF stack.
        host_mem: Dict mapping hostname to memory threshold in bytes.
            RAM used alerts are created for each entry.
        org_id: Optional org_id to pass to RuleGroup constructors.
        disable_provenance: Whether to set disable_provenance on RuleGroups.
        daily_timers: Optional dict mapping hostname to list of timer names.
            If provided, creates timer staleness alert rules.
        dashboard_dir: Directory containing dashboard JSON files.
            Defaults to the package's bundled dashboards.
        dashboard_replacements: Optional dict of {placeholder: value}
            replacements applied to all dashboard JSON files.
    """

    def __init__(
        self,
        stack: 'BaseStack',
        host_mem: Dict[str, int],
        org_id: Optional[str] = None,
        disable_provenance: bool = True,
        daily_timers: Optional[Dict[str, List[str]]] = None,
        dashboard_dir: Optional[str] = None,
        dashboard_replacements: Optional[Dict[str, str]] = None,
    ):
        replacements = {'${prom_uid}': stack.prom.uid}
        if dashboard_replacements:
            replacements.update(dashboard_replacements)

        def _load_dash(name: str) -> str:
            if dashboard_dir:
                path = f'{dashboard_dir}/{name}'
            else:
                path = get_shared_dashboard_path(name)
            return load_dashboard(
                path, replacements=replacements,
                annotation_tags=stack.annotation_tags,
            )

        folder: Folder = Folder(stack, 'hosts-folder', title='Hosts')
        self.folder: Folder = folder

        Dashboard(
            stack, 'hosts-docker-dash', folder=folder.id,
            config_json=_load_dash('docker_and_system_monitoring.json')
        )
        node: Dashboard = Dashboard(
            stack, 'node-exporter-dash', folder=folder.id,
            config_json=_load_dash('node_exporter.json')
        )
        systemd_dash: Dashboard = Dashboard(
            stack, 'systemd-service-dash', folder=folder.id,
            config_json=_load_dash('systemd_service_dashboard.json')
        )
        Dashboard(
            stack, 'mysql-overview-dash', folder=folder.id,
            config_json=_load_dash('mysql-overview.json')
        )
        Dashboard(
            stack, 'apache-status-dash', folder=folder.id,
            config_json=_load_dash('apache.json')
        )

        # Common RuleGroup kwargs
        rg_base = dict(interval_seconds=60, disable_provenance=disable_provenance)
        if org_id is not None:
            rg_base['org_id'] = org_id

        # Systemd rules
        rules = [
            MetricThresholdRule(
                stack,
                name="Systemd Service Restart Count [TF]",
                expr='sum(rate(systemd_service_restart_total[1m])) by (instance, name)',
                threshold=0, threshold_type='gt', reducer='last', for_='2m',
                severity='warning',
                annotations={
                    "__dashboardUid__": systemd_dash.uid,
                    "__panelId__": "13",
                },
            ).rule,
            MetricThresholdRule(
                stack,
                name="Failed Systemd Units [TF]",
                expr='increase(systemd_unit_state{state="failed"}[1m])',
                threshold=0, threshold_type='gt', reducer='last', for_='5m',
                severity='warning',
                annotations={
                    "__dashboardUid__": systemd_dash.uid,
                    "__panelId__": "2",
                },
            ).rule,
        ]
        RuleGroup(
            stack, 'systemd-tf', folder_uid=folder.uid, name='systemd-tf',
            rule=rules, **rg_base
        )

        # Node/filesystem rules
        rules = [
            MetricMinThresholdRule(
                stack,
                name='Filesystem Free Space [TF]',
                expr='(node_filesystem_free_bytes{fstype!="nfs4"} / '
                     'node_filesystem_size_bytes{fstype!="nfs4"}) * 100',
                threshold=10, for_='5m', skip_expr_checks=True,
                annotations={
                    "__dashboardUid__": node.uid,
                    "__panelId__": "43",
                    "description": "{{ $values.B.Labels.instance }} device {{ $values.B.Labels.device }} mountpoint {{ $values.B.Labels.mountpoint }} free space is {{ printf \"%.2f\" $values.B.Value }}% which is below threshold of 10%",
                    "summary": "{{ $values.B.Labels.instance }} {{ $values.B.Labels.mountpoint }} free space is {{ printf \"%.2f\" $values.B.Value }}%",
                }
            ).rule,
            MetricMinThresholdRule(
                stack,
                name='Filesystem Free Inodes [TF]',
                expr='(node_filesystem_files_free{fstype!~"nfs4|vfat", instance!="nas1:9100"}'
                     ' / node_filesystem_files{fstype!~"nfs4|vfat", instance!="nas1:9100"}) * 100',
                threshold=10, for_='5m', skip_expr_checks=True,
                annotations={
                    "__dashboardUid__": node.uid,
                    "__panelId__": "41",
                    "description": "{{ $values.B.Labels.instance }} device {{ $values.B.Labels.device }} mountpoint {{ $values.B.Labels.mountpoint }} free inodes is {{ printf \"%.2f\" $values.B.Value }}% which is below threshold of 10%",
                    "summary": "{{ $values.B.Labels.instance }} {{ $values.B.Labels.mountpoint }} free inodes is {{ printf \"%.2f\" $values.B.Value }}%",
                }
            ).rule,
        ]
        for hostname, mem in host_mem.items():
            rules.append(
                MetricMeanThresholdRule(
                    stack,
                    name=f'{hostname} RAM used',
                    expr=f'node_memory_MemTotal_bytes{{instance="{hostname}:9100",job="node"}} - '
                         f'node_memory_MemFree_bytes{{instance="{hostname}:9100",job="node"}} - '
                         f'(node_memory_Cached_bytes{{instance="{hostname}:9100",job="node"}} + '
                         f'node_memory_Buffers_bytes{{instance="{hostname}:9100",job="node"}} + '
                         f'node_memory_SReclaimable_bytes{{instance="{hostname}:9100",job="node"}})',
                    threshold=mem, threshold_type='gt', for_='5m',
                    skip_expr_checks=True,
                    annotations={
                        "__dashboardUid__": node.uid,
                        "__panelId__": "78",
                        "description": "{{ $values.B.Labels.instance }} memory used is {{ printf \"%.2f\" $values.B.Value }}",
                        "summary": "{{ $values.B.Labels.instance }} memory used is {{ printf \"%.2f\" $values.B.Value }}",
                    }
                ).rule
            )
        rules.append(
            MetricMeanThresholdRule(
                stack,
                name='Swap Percent used',
                expr='(node_memory_SwapTotal_bytes{job="node"} - '
                     'node_memory_SwapFree_bytes{job="node"}) / '
                     'node_memory_SwapTotal_bytes{job="node"} * 100',
                threshold=50, threshold_type='gt', for_='5m',
                skip_expr_checks=True,
                annotations={
                    "__dashboardUid__": node.uid,
                    "__panelId__": "24",
                    "description": "{{ $values.B.Labels.instance }} swap used is {{ printf \"%.2f\" $values.B.Value }}%",
                    "summary": "{{ $values.B.Labels.instance }} swap used is {{ printf \"%.2f\" $values.B.Value }}%",
                }
            ).rule
        )
        RuleGroup(
            stack, 'node-tf', folder_uid=folder.uid, name='node-tf',
            rule=rules, **rg_base
        )

        # MySQL rules
        rules = [
            MetricMaxThresholdRule(
                stack,
                name="MySQL InnoDB Row Lock Current Waits [TF]",
                expr='max_over_time(mysql_global_status_innodb_row_lock_current_waits [5m])',
                threshold=1, for_='5m', severity='warning', annotations={
                    "description": "{{ $values.B.Labels.instance }} has {{ printf \"%.0f\" $values.B.Value }} current InnoDB row lock waits which is above threshold of 1",
                    "summary": "{{ $values.B.Labels.instance }} has {{ printf \"%.0f\" $values.B.Value }} current InnoDB row lock waits",
                },
            ).rule,
            MetricMaxThresholdRule(
                stack,
                name="MySQL InnoDB Row Lock Time [TF]",
                expr='increase(mysql_global_status_innodb_row_lock_time [15m])',
                threshold=1000000, for_='5m', severity='warning',
                annotations={
                    "description": "{{ $values.B.Labels.instance }} has {{ printf \"%.0f\" $values.B.Value }}ms increase in InnoDB row lock time which is above threshold of 1000000ms",
                    "summary": "{{ $values.B.Labels.instance }} has {{ printf \"%.0f\" $values.B.Value }}ms increase in InnoDB row lock time",
                }, skip_expr_checks=True
            ).rule,
        ]
        RuleGroup(
            stack, 'mysql-tf', folder_uid=folder.uid, name='mysql-tf',
            rule=rules, **rg_base
        )

        # Optional timer staleness rules
        if daily_timers:
            timer_rules = []
            for hostname, timers in daily_timers.items():
                for timer in timers:
                    timer_rules.append(
                        MetricMaxThresholdRule(
                            stack,
                            name=f'{hostname} {timer} stale',
                            expr=f'time() - systemd_timer_last_trigger_seconds{{instance="{hostname}:9558",name="{timer}"}}',
                            threshold=172800,
                            severity='warning', for_='5m',
                            skip_expr_checks=True,
                            annotations={
                                "description": f"{hostname} timer {timer} has not fired in over 48 hours",
                                "summary": f"{hostname} {timer} is stale",
                            },
                        ).rule
                    )
            RuleGroup(
                stack, 'timer-staleness', folder_uid=folder.uid,
                name='timer-staleness-tf', rule=timer_rules, **rg_base
            )
