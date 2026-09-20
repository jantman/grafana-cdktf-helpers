"""Shared Hosts monitoring class for CDKTF Grafana projects.

Creates dashboards and alert rules for host-level monitoring:
systemd services, filesystems, memory, swap, MySQL.
"""
from typing import TYPE_CHECKING, Optional, Dict, List, Tuple

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
        host_swap: Optional dict mapping hostname to swap percent threshold.
            Creates per-host swap alerts with custom thresholds and excludes
            those hosts from the default 50% swap alert.
        host_fs_space: Optional dict mapping hostname to a dict of
            {mountpoint: free space percent threshold}. Creates a per-mountpoint
            free space alert with that threshold and excludes exactly that
            (instance, mountpoint) pair from the default 10% free space alert.
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
        host_swap: Optional[Dict[str, int]] = None,
        host_fs_space: Optional[Dict[str, Dict[str, int]]] = None,
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
            return load_dashboard(path, replacements=replacements)

        folder: Folder = Folder(stack, 'hosts-folder', title='Hosts')
        self.folder: Folder = folder

        Dashboard(
            stack, 'hosts-docker-dash', folder=folder.uid,
            config_json=_load_dash('docker_and_system_monitoring.json')
        )
        node: Dashboard = Dashboard(
            stack, 'node-exporter-dash', folder=folder.uid,
            config_json=_load_dash('node_exporter.json')
        )
        systemd_dash: Dashboard = Dashboard(
            stack, 'systemd-service-dash', folder=folder.uid,
            config_json=_load_dash('systemd_service_dashboard.json')
        )
        Dashboard(
            stack, 'mysql-overview-dash', folder=folder.uid,
            config_json=_load_dash('mysql-overview.json')
        )
        Dashboard(
            stack, 'apache-status-dash', folder=folder.uid,
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
        #
        # A (host, mountpoint) pair in host_fs_space gets its own rule at its
        # own threshold and is removed from the fleet-wide rule below, so that
        # exactly one of the two can fire for it.
        fs_space_overrides: List[Tuple[str, str, int]] = [
            (hostname, mountpoint, threshold)
            for hostname, mounts in (host_fs_space or {}).items()
            for mountpoint, threshold in mounts.items()
        ]

        def _fs_space_annotations(threshold: int) -> Dict[str, str]:
            return {
                "__dashboardUid__": node.uid,
                "__panelId__": "43",
                "description": "{{ $values.B.Labels.instance }} device {{ $values.B.Labels.device }} mountpoint {{ $values.B.Labels.mountpoint }} free space is {{ printf \"%.2f\" $values.B.Value }}% which is below threshold of " + f"{threshold}%",
                "summary": "{{ $values.B.Labels.instance }} {{ $values.B.Labels.mountpoint }} free space is {{ printf \"%.2f\" $values.B.Value }}%",
            }

        # tmpfs excluded (2026-07): tmpfs is RAM-backed, so its "free
        # space" is memory pressure (already covered by the RAM/Swap
        # alerts), not disk. A kiosk's tmpfs /tmp briefly dipping under
        # the 10% threshold was the sole source of this alert's flapping.
        #
        # avail_bytes, not free_bytes (2026-09-16). free_bytes counts
        # ext4's root-reserved blocks, which nothing but root can
        # actually use, so on a default 5%-reserve filesystem this
        # rule read about 5 points higher than the space anyone has.
        # phoenix /home reported ~10% while 4.2% was genuinely
        # available. avail_bytes is what df shows and what a process
        # hitting ENOSPC cares about.
        #
        # nas1:9100 excluded, matching the inode rule below: it
        # exports exactly one non-tmpfs mount, / on /dev/md0, which is
        # the same storage that `NAS1 Volume Space Used [TF]` already
        # alerts on from the Synology API. Before this, volume1
        # crossing 90% raised both at identical timestamps.
        fs_space_expr = (
            '(node_filesystem_avail_bytes{fstype!~"nfs4|tmpfs", instance!="nas1:9100"} / '
            'node_filesystem_size_bytes{fstype!~"nfs4|tmpfs", instance!="nas1:9100"}) * 100'
        )
        if fs_space_overrides:
            # `unless on (instance, mountpoint)`, not an extra label matcher:
            # an override is one mountpoint on one host, and a matcher set
            # cannot express "this instance AND this mountpoint" as an
            # exclusion -- instance!="bigserver:9100" would drop that host's
            # other filesystems too. The division drops __name__ but keeps the
            # left operand's labels, so both labels are there to match on.
            selectors = ' or '.join(
                f'node_filesystem_avail_bytes{{instance="{hostname}:9100",'
                f'mountpoint="{mountpoint}"}}'
                for hostname, mountpoint, _ in fs_space_overrides
            )
            fs_space_expr += f' unless on (instance, mountpoint) ({selectors})'

        rules = [
            MetricMinThresholdRule(
                stack,
                name='Filesystem Free Space [TF]',
                expr=fs_space_expr,
                threshold=10, for_='5m', skip_expr_checks=True,
                annotations=_fs_space_annotations(10),
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
        for hostname, mountpoint, threshold in fs_space_overrides:
            rules.append(
                MetricMinThresholdRule(
                    stack,
                    name=f'{hostname} {mountpoint} Filesystem Free Space [TF]',
                    expr=(
                        f'(node_filesystem_avail_bytes{{instance="{hostname}:9100",'
                        f'mountpoint="{mountpoint}"}} / '
                        f'node_filesystem_size_bytes{{instance="{hostname}:9100",'
                        f'mountpoint="{mountpoint}"}}) * 100'
                    ),
                    threshold=threshold, for_='5m', skip_expr_checks=True,
                    annotations=_fs_space_annotations(threshold),
                ).rule
            )
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
        swap_annotations = {
            "__dashboardUid__": node.uid,
            "__panelId__": "24",
            "description": "{{ $values.B.Labels.instance }} swap used is {{ printf \"%.2f\" $values.B.Value }}%",
            "summary": "{{ $values.B.Labels.instance }} swap used is {{ printf \"%.2f\" $values.B.Value }}%",
        }
        if host_swap:
            exclude = ','.join(f'{h}:9100' for h in host_swap)
            instance_filter = f', instance!~"{exclude}"'
        else:
            instance_filter = ''
        rules.append(
            MetricMeanThresholdRule(
                stack,
                name='Swap Percent used',
                expr=f'(node_memory_SwapTotal_bytes{{job="node"{instance_filter}}} - '
                     f'node_memory_SwapFree_bytes{{job="node"{instance_filter}}}) / '
                     f'node_memory_SwapTotal_bytes{{job="node"{instance_filter}}} * 100',
                threshold=50, threshold_type='gt', for_='5m',
                skip_expr_checks=True,
                annotations=swap_annotations,
            ).rule
        )
        if host_swap:
            for hostname, threshold in host_swap.items():
                rules.append(
                    MetricMeanThresholdRule(
                        stack,
                        name=f'{hostname} Swap Percent used',
                        expr=f'(node_memory_SwapTotal_bytes{{job="node",instance="{hostname}:9100"}} - '
                             f'node_memory_SwapFree_bytes{{job="node",instance="{hostname}:9100"}}) / '
                             f'node_memory_SwapTotal_bytes{{job="node",instance="{hostname}:9100"}} * 100',
                        threshold=threshold, threshold_type='gt', for_='5m',
                        skip_expr_checks=True,
                        annotations=swap_annotations,
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
