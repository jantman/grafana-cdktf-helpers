"""Tests for the Hosts monitoring class."""
import json
from unittest.mock import MagicMock

import pytest

from grafana_cdktf_helpers import alert_rule_helpers as arh
from grafana_cdktf_helpers.hosts import Hosts


def _build(**kwargs):
    """Build a Hosts() and return the list of PromQL exprs it generated."""
    arh.RuleGroupRuleData.reset_mock()
    stack = MagicMock()
    stack.prom.uid = 'promuid'
    Hosts(stack, host_mem={'titan': 1}, **kwargs)
    exprs = []
    for call in arh.RuleGroupRuleData.call_args_list:
        model = call.kwargs.get('model')
        if not isinstance(model, str):
            continue
        parsed = json.loads(model)
        if 'expr' in parsed:
            exprs.append(parsed['expr'])
    return exprs


def _failed_unit_exprs(exprs):
    return [e for e in exprs if 'systemd_unit_state' in e]


def test_fleet_wide_rule_tests_the_level_not_the_edge():
    """
    The fleet-wide rule must not use increase().

    systemd_unit_state is a 0/1 gauge, so increase() over it is non-zero only
    during the minute after the 0->1 edge, and goes false again while the unit
    is still failed. Built that way with a 5m for_ -- which is how it shipped
    until 0.18.0 -- the rule could never reach Alerting at all: 36 state
    transitions in 30 days at one site, every one Normal -> Pending -> Normal,
    while eight units sat failed for a week. It notified about nothing and
    looked entirely correct doing it.
    """
    exprs = _failed_unit_exprs(_build())
    assert exprs == ['systemd_unit_state{state="failed"}']
    assert 'increase(' not in exprs[0]


def test_override_excludes_the_pair_from_the_fleet_wide_rule():
    exprs = _failed_unit_exprs(
        _build(host_unit_failed={'titan': {'route53_ddns.service': '1h'}})
    )
    fleet = [e for e in exprs if ' unless on ' in e]
    assert len(fleet) == 1
    # Exclusion is on the (instance, name) pair, so titan's *other* units
    # stay in the fleet-wide rule.
    assert (
        'unless on (instance, name) '
        '(systemd_unit_state{state="failed",instance="titan:9558",'
        'name="route53_ddns.service"})'
    ) in fleet[0]


def test_override_rule_tests_the_level_not_the_edge():
    """
    The override rule must not use increase().

    systemd_unit_state is a 0/1 gauge, so increase() over it is non-zero only
    during the minute after the 0->1 edge. A rule built that way with a for_
    longer than 1m can never reach Alerting -- it is a silent no-op, which is
    exactly the bug this override exists to avoid.
    """
    exprs = _failed_unit_exprs(
        _build(host_unit_failed={'titan': {'route53_ddns.service': '1h'}})
    )
    override = [e for e in exprs if ' unless on ' not in e]
    assert override == [
        'systemd_unit_state{state="failed",instance="titan:9558",'
        'name="route53_ddns.service"}'
    ]
    assert 'increase(' not in override[0]


def test_multiple_overrides_across_hosts():
    exprs = _failed_unit_exprs(_build(host_unit_failed={
        'titan': {'route53_ddns.service': '1h'},
        'phoenix': {'user@1000.service': '30m'},
    }))
    fleet = [e for e in exprs if ' unless on ' in e][0]
    assert fleet.count('systemd_unit_state{state="failed",instance=') == 2
    assert 'instance="titan:9558",name="route53_ddns.service"' in fleet
    assert 'instance="phoenix:9558",name="user@1000.service"' in fleet
    overrides = [e for e in exprs if ' unless on ' not in e]
    assert len(overrides) == 2
