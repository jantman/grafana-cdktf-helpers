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


def test_ignore_excludes_the_pair_and_adds_no_rule():
    """
    host_unit_ignore removes the (instance, name) pair from the fleet-wide rule
    and, unlike host_unit_failed, creates no per-unit rule in its place.
    """
    exprs = _failed_unit_exprs(_build(host_unit_ignore={
        'basementtouchpi': ['NetworkManager-wait-online.service'],
    }))
    assert exprs == [
        'systemd_unit_state{state="failed"} unless on (instance, name) '
        '(systemd_unit_state{state="failed",instance="basementtouchpi:9558",'
        'name="NetworkManager-wait-online.service"})'
    ]


def test_ignore_and_override_combine_in_one_exclusion():
    exprs = _failed_unit_exprs(_build(
        host_unit_failed={'titan': {'route53_ddns.service': '1h'}},
        host_unit_ignore={'basementtouchpi': ['NetworkManager-wait-online.service']},
    ))
    fleet = [e for e in exprs if ' unless on ' in e]
    assert len(fleet) == 1
    assert 'instance="titan:9558",name="route53_ddns.service"' in fleet[0]
    assert (
        'instance="basementtouchpi:9558",'
        'name="NetworkManager-wait-online.service"'
    ) in fleet[0]
    # Only the override gets a rule of its own.
    assert [e for e in exprs if ' unless on ' not in e] == [
        'systemd_unit_state{state="failed",instance="titan:9558",'
        'name="route53_ddns.service"}'
    ]


def test_pair_in_both_ignore_and_override_is_rejected():
    with pytest.raises(ValueError, match='titan route53_ddns.service'):
        _build(
            host_unit_failed={'titan': {'route53_ddns.service': '1h'}},
            host_unit_ignore={'titan': ['route53_ddns.service']},
        )


def _swap_exprs(exprs):
    return [e for e in exprs if 'SwapTotal' in e]


def test_swap_rule_has_no_paging_filter_by_default():
    exprs = _swap_exprs(_build())
    assert len(exprs) == 1
    assert 'pswpin' not in exprs[0]


def test_swap_min_paging_rate_filters_every_swap_rule():
    exprs = _swap_exprs(_build(
        host_swap={'titan': 80}, swap_min_paging_rate=100,
    ))
    assert len(exprs) == 2
    for e in exprs:
        assert e.endswith(
            ' and on(instance) (rate(node_vmstat_pswpin{job="node"}[10m]) + '
            'rate(node_vmstat_pswpout{job="node"}[10m])) > 100'
        )


def test_swap_min_paging_rate_reads_no_data_as_ok():
    arh.RuleGroupRule.reset_mock()
    _build(swap_min_paging_rate=100)
    swap = [
        c.kwargs for c in arh.RuleGroupRule.call_args_list
        if c.kwargs.get('name') == 'Swap Percent used'
    ]
    assert swap[0]['no_data_state'] == 'OK'
