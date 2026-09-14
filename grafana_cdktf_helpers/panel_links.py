"""Keep alert-rule panel links pointing at the panel they name.

A Grafana alert rule links to a panel with two annotations, ``__dashboardUid__``
and ``__panelId__``. Notifications render that panel as their screenshot and
use it for the "View panel" link. Nothing validates the pair, and it breaks in
two silent ways:

* **The panel id isn't in the dashboard source.** The alert names an id no
  panel has, or the dashboard JSON has had its panel ids removed.
* **The Terraform grafana provider drops them on some updates.** Its
  ``config_json`` state function removes top-level ``panels[].id``. Creates and
  content changes send the configured JSON with ids intact, but an update that
  changes only another attribute (``folder``, ``message``) re-sends the stored
  copy, and the ids are gone. Grafana then numbers the id-less panels from the
  highest remaining id + 1, so the link draws the wrong panel or "Panel not
  found". No plan shows it: the state never has panel ids to compare.

:func:`check_synth` catches the first before a deploy, :func:`check_live`
catches both after one, and :class:`DashboardResendNonce` repairs the second.

    python -m grafana_cdktf_helpers.panel_links synth cdktf.out/stacks/<stack>/cdk.tf.json
    python -m grafana_cdktf_helpers.panel_links live http://grafana:3000/
"""
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Iterator, List, Optional

import jsii
from cdktf import IAspect

#: Top-level dashboard key :class:`DashboardResendNonce` writes.
NONCE_KEY = 'cdktfResendNonce'

_DASHBOARD_UID_REF = re.compile(r'^\$\{grafana_dashboard\.([^.}]+)\.uid\}$')


def iter_panels(dashboard: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    """Yield every panel in a dashboard model.

    Includes panels nested in collapsed rows, and the pre-schemaVersion-16
    ``rows[].panels`` layout, which Grafana still accepts and migrates on load.
    """
    pending = list(dashboard.get('panels') or [])
    for row in dashboard.get('rows') or []:
        pending.extend(row.get('panels') or [])
    while pending:
        panel = pending.pop()
        yield panel
        pending.extend(panel.get('panels') or [])


def _panel_problem(rule: str, dashboard: Optional[Dict[str, Any]],
                   dashboard_ref: str, panel_id: Any) -> Optional[str]:
    """Describe what is wrong with one alert's panel link, or None if nothing."""
    if dashboard is None:
        return f'{rule}: dashboard {dashboard_ref!r} not found'
    try:
        wanted = int(panel_id)
    except (TypeError, ValueError):
        return f'{rule}: __panelId__ {panel_id!r} is not a panel id'
    title = dashboard.get('title')
    matches = [p for p in iter_panels(dashboard) if p.get('id') == wanted]
    if not matches:
        idless = sum(1 for p in dashboard.get('panels') or [] if p.get('id') is None)
        hint = f' ({idless} top-level panels have no id)' if idless else ''
        return f'{rule}: panel {wanted} not in dashboard {title!r}{hint}'
    if len(matches) > 1:
        return f'{rule}: panel id {wanted} is used {len(matches)} times in dashboard {title!r}'
    return None


def check_synth(tf_json: Dict[str, Any]) -> List[str]:
    """Check every alert panel link in a synthesized ``cdk.tf.json``.

    ``__dashboardUid__`` may be a ``${grafana_dashboard.<name>.uid}`` reference
    or a literal uid set in a dashboard's own JSON.
    """
    resources = tf_json.get('resource', {})
    by_name: Dict[str, Dict[str, Any]] = {}
    by_uid: Dict[str, Dict[str, Any]] = {}
    for name, resource in resources.get('grafana_dashboard', {}).items():
        model = json.loads(resource['config_json'])
        by_name[name] = model
        if isinstance(model.get('uid'), str):
            by_uid[model['uid']] = model
    problems = []
    for group in resources.get('grafana_rule_group', {}).values():
        for rule in group.get('rule', []):
            annotations = rule.get('annotations') or {}
            ref = annotations.get('__dashboardUid__')
            if ref is None:
                continue
            match = _DASHBOARD_UID_REF.match(ref)
            dashboard = by_name.get(match.group(1)) if match else by_uid.get(ref)
            problem = _panel_problem(rule['name'], dashboard, ref, annotations.get('__panelId__'))
            if problem:
                problems.append(problem)
    return problems


def check_live(grafana_url: str, auth: Optional[str] = None) -> List[str]:
    """Check every alert panel link against what Grafana has stored.

    ``auth`` is a bearer token; anonymous access works where the Grafana
    instance allows viewers to read alert rules and dashboards.
    """
    base = grafana_url.rstrip('/')

    def get(path: str) -> Any:
        req = urllib.request.Request(base + path)
        if auth:
            req.add_header('Authorization', f'Bearer {auth}')
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.load(resp)

    dashboards: Dict[str, Optional[Dict[str, Any]]] = {}
    problems = []
    for rule in get('/api/v1/provisioning/alert-rules'):
        annotations = rule.get('annotations') or {}
        uid = annotations.get('__dashboardUid__')
        if not uid:
            continue
        if uid not in dashboards:
            try:
                dashboards[uid] = get(f'/api/dashboards/uid/{urllib.parse.quote(uid)}')['dashboard']
            except urllib.error.HTTPError as err:
                if err.code != 404:
                    raise
                dashboards[uid] = None
        problem = _panel_problem(rule['title'], dashboards[uid], uid, annotations.get('__panelId__'))
        if problem:
            problems.append(problem)
    return problems


@jsii.implements(IAspect)
class DashboardResendNonce:
    """Stamp a value into every ``grafana_dashboard``'s ``config_json``.

    Changing the value changes every dashboard's configured JSON, so the next
    deploy re-sends each one in full, panel ids included. That is the repair
    when :func:`check_live` finds panels without ids after an update that
    changed only a dashboard's folder or message. Grafana keeps the key as-is,
    so an unchanged value plans clean::

        Aspects.of(stack).add(DashboardResendNonce('2026-09-14'))
    """

    def __init__(self, nonce: str):
        self.nonce = nonce

    def visit(self, node: Any) -> None:
        if getattr(node, 'terraform_resource_type', None) != 'grafana_dashboard':
            return
        model = json.loads(node.config_json_input)
        if model.get(NONCE_KEY) == self.nonce:
            return
        model[NONCE_KEY] = self.nonce
        node.config_json = json.dumps(model)


def main(argv: Optional[List[str]] = None) -> int:
    """Usage: panel_links synth <cdk.tf.json> | panel_links live <grafana_url>

    ``live`` authenticates with ``GRAFANA_AUTH`` when it is set. Exits 1 if any
    alert's panel link is broken.
    """
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2 or args[0] not in ('synth', 'live'):
        print(main.__doc__, file=sys.stderr)
        return 2
    mode, target = args
    if mode == 'synth':
        with open(target) as fh:
            problems = check_synth(json.load(fh))
    else:
        problems = check_live(target, os.environ.get('GRAFANA_AUTH'))
    for problem in problems:
        print(problem, file=sys.stderr)
    if mode == 'live' and any('have no id' in p for p in problems):
        print('Dashboard panels have lost their ids: bump the DashboardResendNonce '
              'value and deploy again.', file=sys.stderr)
    print(f'alert panel links ({mode}): {len(problems)} broken')
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
