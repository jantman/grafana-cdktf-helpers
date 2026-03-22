"""Shared NUT UPS monitoring class for CDKTF Grafana projects."""
from typing import TYPE_CHECKING, Optional

from imports.grafana.dashboard import Dashboard
from imports.grafana.rule_group import RuleGroup
from grafana_cdktf_helpers.alert_rule_helpers import (
    MetricMeanThresholdRule, MetricMinThresholdRule, MetricMaxThresholdRule,
    InfoLabelValueRule
)
from grafana_cdktf_helpers.utils import load_dashboard, get_shared_dashboard_path

if TYPE_CHECKING:
    from grafana_cdktf_helpers.stack import BaseStack


class NutUps:
    """
    Creates a per-UPS dashboard and alert rules for NUT-monitored UPS devices.

    This is the shared base class. Consuming projects create a wrapper class
    (e.g. NUT or UPS) that creates a folder and instantiates NutUps for each
    UPS device.
    """

    def __init__(
        self, stack: 'BaseStack', upsname: str, folder_id: str, folder_uid: str,
        runtime_minutes: int, has_output_voltage: bool = True,
        battery_voltage: int = 24, load_threshold: int = 75,
        add_rules: bool = True,
        status_no_data_state: str = 'NoData',
        voltage_high_threshold: int = 125,
        org_id: Optional[str] = None,
        dashboard_path: Optional[str] = None,
    ):
        if dashboard_path is None:
            dashboard_path = get_shared_dashboard_path('nut-ups-dash.json')
        dash_json = load_dashboard(
            dashboard_path,
            replacements={
                '${prom_uid}': stack.prom.uid,
                '${upsname}': upsname,
            },
            annotation_tags=stack.annotation_tags,
        )
        dash: Dashboard = Dashboard(
            stack, f'{upsname}-dash', folder=folder_id, config_json=dash_json
        )
        if not add_rules:
            return
        rules = [
            InfoLabelValueRule(
                stack=stack,
                name=f'{upsname} Status [TF]',
                metric='nut_ups_status',
                metric_label='status', expected_label_value='OL',
                metric_selectors=f'ups="{upsname}"',
                item_name='UPS',
                summary_prefix=upsname,
                no_data_state=status_no_data_state
            ).rule,
            MetricMeanThresholdRule(
                stack=stack,
                name=f'{upsname} Battery Charge [TF]',
                expr='100 * avg_over_time(nut_battery_charge{ups="'
                     + upsname + '"}[1m])',
                threshold=99, threshold_type='lt',
                annotations={
                    "__dashboardUid__": dash.uid,
                    "__panelId__": "5",
                    'description': "The UPS battery charge is {{ printf \"%.2f\" $values.B.Value }}%",
                    'summary': upsname + " UPS battery charge is {{ printf \"%.2f\" $values.B.Value }}%"
                }
            ).rule,
            MetricMeanThresholdRule(
                stack=stack,
                name=f'{upsname} Runtime [TF]',
                expr='avg_over_time(nut_battery_runtime_seconds{ups="'
                     + upsname + '"}[1m]) / 60',
                threshold=runtime_minutes, threshold_type='lt',
                severity='critical',
                annotations={
                    "__dashboardUid__": dash.uid,
                    "__panelId__": "16",
                    'description': "The UPS runtime is {{ printf \"%.2f\" $values.B.Value }} minutes",
                    'summary': upsname + " UPS runtime is {{ printf \"%.2f\" $values.B.Value }} minutes"
                }
            ).rule,
            MetricMaxThresholdRule(
                stack=stack,
                name=f'{upsname} Load [TF]',
                expr='100 * max_over_time(nut_load{ups="' +
                     upsname + '"}[1m])',
                threshold=load_threshold,
                annotations={
                    "__dashboardUid__": dash.uid,
                    "__panelId__": "6",
                    'description': "The UPS load is {{ printf \"%.2f\" $values.B.Value }}%",
                    'summary': upsname + " UPS load is {{ printf \"%.2f\" $values.B.Value }}%"
                }
            ).rule,
            MetricMinThresholdRule(
                stack=stack,
                name=f'{upsname} Battery Voltage Low [TF]',
                expr='min_over_time(nut_battery_voltage_volts{ups=\"' +
                     upsname + '\"}[1m])',
                threshold=battery_voltage - 1,
                annotations={
                    "__dashboardUid__": dash.uid,
                    "__panelId__": "10",
                    'description': "The UPS battery voltage is {{ printf \"%.2f\" $values.B.Value }}V",
                    'summary': upsname + " UPS battery voltage is {{ printf \"%.2f\" $values.B.Value }}V"
                }
            ).rule,
            MetricMaxThresholdRule(
                stack=stack,
                name=f'{upsname} Battery Voltage High [TF]',
                expr='max_over_time(nut_battery_voltage_volts{ups=\"' +
                     upsname + '\"}[1m])',
                threshold=battery_voltage + 1,
                annotations={
                    "__dashboardUid__": dash.uid,
                    "__panelId__": "10",
                    'description': "The UPS battery voltage is {{ printf \"%.2f\" $values.B.Value }}V",
                    'summary': upsname + " UPS battery voltage is {{ printf \"%.2f\" $values.B.Value }}V"
                }
            ).rule,
            MetricMinThresholdRule(
                stack=stack,
                name=f'{upsname} Input Voltage Low [TF]',
                expr='min_over_time(nut_input_voltage_volts{ups=\"' +
                     upsname + '\"}[1m])',
                threshold=110,
                annotations={
                    "__dashboardUid__": dash.uid,
                    "__panelId__": "9",
                    'description': "The UPS input voltage is {{ printf \"%.2f\" $values.B.Value }}V",
                    'summary': upsname + " UPS input voltage is {{ printf \"%.2f\" $values.B.Value }}V"
                }
            ).rule,
            MetricMaxThresholdRule(
                stack=stack,
                name=f'{upsname} Input Voltage High [TF]',
                expr='max_over_time(nut_input_voltage_volts{ups=\"' +
                     upsname + '\"}[1m])',
                threshold=voltage_high_threshold,
                annotations={
                    "__dashboardUid__": dash.uid,
                    "__panelId__": "9",
                    'description': "The UPS input voltage is {{ printf \"%.2f\" $values.B.Value }}V",
                    'summary': upsname + " UPS input voltage is {{ printf \"%.2f\" $values.B.Value }}V"
                }
            ).rule,
        ]
        if has_output_voltage:
            rules.extend([
                MetricMinThresholdRule(
                    stack=stack,
                    name=f'{upsname} Output Voltage Low [TF]',
                    expr='min_over_time(nut_output_voltage_volts{ups=\"' +
                         upsname + '\"}[1m])',
                    threshold=110,
                    annotations={
                        "__dashboardUid__": dash.uid,
                        "__panelId__": "11",
                        'description': "The UPS output voltage is {{ printf \"%.2f\" $values.B.Value }}V",
                        'summary': upsname + " UPS output voltage is {{ printf \"%.2f\" $values.B.Value }}V"
                    }
                ).rule,
                MetricMaxThresholdRule(
                    stack=stack,
                    name=f'{upsname} Output Voltage High [TF]',
                    expr='max_over_time(nut_output_voltage_volts{ups=\"' +
                         upsname + '\"}[1m])',
                    threshold=voltage_high_threshold,
                    annotations={
                        "__dashboardUid__": dash.uid,
                        "__panelId__": "11",
                        'description': "The UPS output voltage is {{ printf \"%.2f\" $values.B.Value }}V",
                        'summary': upsname + " UPS output voltage is {{ printf \"%.2f\" $values.B.Value }}V"
                    }
                ).rule
            ])
        rg_kwargs = dict(
            folder_uid=folder_uid, name=f'{upsname}-tf',
            interval_seconds=60, rule=rules, disable_provenance=True
        )
        if org_id is not None:
            rg_kwargs['org_id'] = org_id
        RuleGroup(stack, upsname, **rg_kwargs)
