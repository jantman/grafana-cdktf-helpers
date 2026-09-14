"""Tests for the panel_links module."""
import io
import json
import urllib.error

import pytest

from grafana_cdktf_helpers import panel_links
from grafana_cdktf_helpers.panel_links import (
    NONCE_KEY, DashboardResendNonce, check_live, check_synth, iter_panels, main,
)


def dashboard(uid='d1', title='Dash', panels=None, **extra):
    model = {'uid': uid, 'title': title, 'panels': panels or []}
    model.update(extra)
    return model


def tf_json(dashboards, rules):
    """Build a minimal cdk.tf.json: dashboards is {resource name: model}."""
    return {'resource': {
        'grafana_dashboard': {
            name: {'config_json': json.dumps(model)} for name, model in dashboards.items()
        },
        'grafana_rule_group': {'g': {'rule': rules}},
    }}


def rule(name, dashboard_ref, panel_id):
    return {'name': name, 'annotations': {
        '__dashboardUid__': dashboard_ref, '__panelId__': panel_id,
    }}


class TestIterPanels:

    def test_walks_collapsed_rows(self):
        d = dashboard(panels=[
            {'id': 1, 'type': 'timeseries'},
            {'id': 2, 'type': 'row', 'collapsed': True, 'panels': [{'id': 3}]},
        ])
        assert sorted(p['id'] for p in iter_panels(d)) == [1, 2, 3]

    def test_walks_legacy_rows_layout(self):
        d = {'rows': [{'panels': [{'id': 1}, {'id': 33}]}, {'panels': [{'id': 5}]}]}
        assert sorted(p['id'] for p in iter_panels(d)) == [1, 5, 33]

    def test_empty(self):
        assert list(iter_panels({})) == []


class TestCheckSynth:

    def test_resolves_dashboard_reference(self):
        doc = tf_json({'house': dashboard(panels=[{'id': 27, 'title': 'Humidity'}])},
                      [rule('Humidor Low Humidity', '${grafana_dashboard.house.uid}', '27')])
        assert check_synth(doc) == []

    def test_resolves_literal_uid(self):
        doc = tf_json({'ping': dashboard(uid='Yt5LqhyVz', panels=[{'id': 2}])},
                      [rule('WAN Ping Loss', 'Yt5LqhyVz', '2')])
        assert check_synth(doc) == []

    def test_panel_in_collapsed_row(self):
        doc = tf_json({'house': dashboard(panels=[
            {'id': 31, 'type': 'row', 'collapsed': True, 'panels': [{'id': 32}]},
        ])}, [rule('Water', '${grafana_dashboard.house.uid}', '32')])
        assert check_synth(doc) == []

    def test_missing_panel(self):
        doc = tf_json({'usg': dashboard(title='USG', panels=[{'id': 1}])},
                      [rule('UXG Uptime', '${grafana_dashboard.usg.uid}', '64')])
        assert check_synth(doc) == ["UXG Uptime: panel 64 not in dashboard 'USG'"]

    def test_missing_panel_notes_idless_panels(self):
        doc = tf_json({'usg': dashboard(title='USG', panels=[{'title': 'a'}, {'title': 'b'}])},
                      [rule('UXG Uptime', '${grafana_dashboard.usg.uid}', '64')])
        assert check_synth(doc) == [
            "UXG Uptime: panel 64 not in dashboard 'USG' (2 top-level panels have no id)"
        ]

    def test_duplicate_panel_id(self):
        doc = tf_json({'d': dashboard(title='D', panels=[{'id': 4}, {'id': 4}])},
                      [rule('R', '${grafana_dashboard.d.uid}', '4')])
        assert check_synth(doc) == ["R: panel id 4 is used 2 times in dashboard 'D'"]

    def test_unresolved_dashboard(self):
        doc = tf_json({}, [rule('R', '${grafana_dashboard.nope.uid}', '1')])
        assert check_synth(doc) == ["R: dashboard '${grafana_dashboard.nope.uid}' not found"]

    def test_non_numeric_panel_id(self):
        # str(builder.id_for_panel("typo")) renders as "None"
        doc = tf_json({'d': dashboard(panels=[{'id': 1}])},
                      [rule('R', '${grafana_dashboard.d.uid}', 'None')])
        assert check_synth(doc) == ["R: __panelId__ 'None' is not a panel id"]

    def test_ignores_rules_without_panel_link(self):
        doc = tf_json({}, [{'name': 'R', 'annotations': {'summary': 'x'}}, {'name': 'S'}])
        assert check_synth(doc) == []


class FakeResponse(io.BytesIO):
    pass


def fake_grafana(monkeypatch, rules, dashboards):
    """Serve alert rules and dashboards {uid: model} from a fake urlopen."""
    seen = []

    def urlopen(req, timeout=None):
        seen.append(req)
        path = req.full_url.split(':3000', 1)[1]
        if path == '/api/v1/provisioning/alert-rules':
            return FakeResponse(json.dumps(rules).encode())
        uid = path.rsplit('/', 1)[1]
        if uid not in dashboards:
            raise urllib.error.HTTPError(req.full_url, 404, 'Not Found', {}, None)
        return FakeResponse(json.dumps({'dashboard': dashboards[uid]}).encode())

    monkeypatch.setattr(panel_links.urllib.request, 'urlopen', urlopen)
    return seen


def live_rule(title, uid, panel_id):
    return {'title': title, 'annotations': {'__dashboardUid__': uid, '__panelId__': panel_id}}


class TestCheckLive:

    def test_ok(self, monkeypatch):
        fake_grafana(monkeypatch, [live_rule('R', 'd1', '2')],
                     {'d1': dashboard(panels=[{'id': 2}])})
        assert check_live('http://g:3000/') == []

    def test_ids_stripped_by_folder_only_update(self, monkeypatch):
        fake_grafana(monkeypatch, [live_rule('WAN Ping Loss', 'd1', '2')],
                     {'d1': dashboard(title='Ping', panels=[{'title': 'Loss'}, {'title': 'RTT'}])})
        assert check_live('http://g:3000/') == [
            "WAN Ping Loss: panel 2 not in dashboard 'Ping' (2 top-level panels have no id)"
        ]

    def test_missing_dashboard(self, monkeypatch):
        fake_grafana(monkeypatch, [live_rule('R', 'gone', '1')], {})
        assert check_live('http://g:3000/') == ["R: dashboard 'gone' not found"]

    def test_fetches_each_dashboard_once_with_auth(self, monkeypatch):
        seen = fake_grafana(monkeypatch, [live_rule('A', 'd1', '1'), live_rule('B', 'd1', '1'),
                                          {'title': 'C', 'annotations': {}}],
                            {'d1': dashboard(panels=[{'id': 1}])})
        assert check_live('http://g:3000', auth='tok') == []
        assert [r.full_url for r in seen] == [
            'http://g:3000/api/v1/provisioning/alert-rules', 'http://g:3000/api/dashboards/uid/d1',
        ]
        assert all(r.get_header('Authorization') == 'Bearer tok' for r in seen)


class FakeDashboardResource:
    terraform_resource_type = 'grafana_dashboard'

    def __init__(self, model):
        self.config_json_input = json.dumps(model)
        self.config_json = None


class TestDashboardResendNonce:

    def test_stamps_nonce(self):
        node = FakeDashboardResource(dashboard(panels=[{'id': 5}]))
        DashboardResendNonce('2026-09-14').visit(node)
        assert json.loads(node.config_json) == dashboard(panels=[{'id': 5}], **{NONCE_KEY: '2026-09-14'})

    def test_idempotent(self):
        node = FakeDashboardResource(dashboard(**{NONCE_KEY: 'n1'}))
        DashboardResendNonce('n1').visit(node)
        assert node.config_json is None

    def test_replaces_old_nonce(self):
        node = FakeDashboardResource(dashboard(**{NONCE_KEY: 'n1'}))
        DashboardResendNonce('n2').visit(node)
        assert json.loads(node.config_json)[NONCE_KEY] == 'n2'

    def test_ignores_other_constructs(self):
        class Folder:
            terraform_resource_type = 'grafana_folder'
        DashboardResendNonce('n').visit(Folder())
        DashboardResendNonce('n').visit(object())


class TestMain:

    def test_usage(self, capsys):
        assert main([]) == 2
        assert 'Usage' in capsys.readouterr().err

    def test_synth(self, tmp_path, capsys):
        path = tmp_path / 'cdk.tf.json'
        path.write_text(json.dumps(tf_json({'d': dashboard(panels=[{'id': 1}])},
                                           [rule('R', '${grafana_dashboard.d.uid}', '9')])))
        assert main(['synth', str(path)]) == 1
        out = capsys.readouterr()
        assert "R: panel 9 not in dashboard 'Dash'" in out.err
        assert 'alert panel links (synth): 1 broken' in out.out

    @pytest.mark.parametrize('panels, code, hint', [
        ([{'id': 1}], 0, False),
        ([{'title': 'x'}], 1, True),
    ])
    def test_live(self, monkeypatch, capsys, panels, code, hint):
        monkeypatch.setenv('GRAFANA_AUTH', 'tok')
        fake_grafana(monkeypatch, [live_rule('R', 'd1', '1')], {'d1': dashboard(panels=panels)})
        assert main(['live', 'http://g:3000/']) == code
        assert ('bump the DashboardResendNonce' in capsys.readouterr().err) is hint
