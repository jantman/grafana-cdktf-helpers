"""Tests for utility functions."""
import json
import os
import tempfile

from grafana_cdktf_helpers.utils import (
    build_all_annotations_query,
    ensure_all_annotations,
    load_dashboard,
    get_shared_dashboard_path,
)


def test_load_dashboard_no_replacements():
    """Test loading a dashboard JSON without replacements."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump({"title": "Test Dashboard", "uid": "test-uid"}, f)
        path = f.name
    try:
        result = load_dashboard(path)
        data = json.loads(result)
        assert data['title'] == 'Test Dashboard'
        assert data['uid'] == 'test-uid'
    finally:
        os.unlink(path)


def test_load_dashboard_with_replacements():
    """Test loading a dashboard JSON with placeholder replacements."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump({
            "title": "Test",
            "datasource": {"uid": "${prom_uid}"},
            "tags": ["${upsname}"]
        }, f)
        path = f.name
    try:
        result = load_dashboard(path, replacements={
            '${prom_uid}': 'abc123',
            '${upsname}': 'cyberpower',
        })
        data = json.loads(result)
        assert data['datasource']['uid'] == 'abc123'
        assert data['tags'] == ['cyberpower']
    finally:
        os.unlink(path)


def test_get_shared_dashboard_path():
    """Test that shared dashboard paths resolve correctly."""
    path = get_shared_dashboard_path('apache.json')
    assert os.path.isfile(path)
    # Verify it's valid JSON
    with open(path) as f:
        data = json.load(f)
    assert 'title' in data or 'panels' in data or 'rows' in data


def test_all_shared_dashboards_exist():
    """Verify all expected shared dashboards are bundled."""
    expected = [
        'alertmanager_dash.json',
        'apache.json',
        'docker_and_system_monitoring.json',
        'grafana_metrics_dash.json',
        'mysql-overview.json',
        'node_exporter.json',
        'nut-ups-dash.json',
        'ping.json',
        'prometheus_overview_dash.json',
        'prometheus_stats_dash.json',
        'systemd_service_dashboard.json',
        'unifi_client_dpi_dash.json',
        'unifi_client_insights_dash.json',
        'unifi_network_sites_dash.json',
        'unifi_uap_dash.json',
        'unifi_usg_dash.json',
        'unifi_usw_dash.json',
    ]
    for name in expected:
        path = get_shared_dashboard_path(name)
        assert os.path.isfile(path), f'Missing dashboard: {name}'


def test_all_shared_dashboards_valid_json():
    """Verify all bundled dashboards are valid JSON."""
    dashboards_dir = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        'grafana_cdktf_helpers', 'dashboards'
    )
    for name in os.listdir(dashboards_dir):
        if not name.endswith('.json'):
            continue
        path = os.path.join(dashboards_dir, name)
        with open(path) as f:
            try:
                json.load(f)
            except json.JSONDecodeError as e:
                raise AssertionError(f'{name} is not valid JSON: {e}')


# --- build_all_annotations_query ---

def test_build_all_annotations_query_with_tags():
    q = build_all_annotations_query(['deploy', 'backup'])
    assert q['target']['tags'] == ['deploy', 'backup']
    assert q['target']['matchAny'] is True
    assert q['name'] == 'All Annotations'
    assert q['enable'] is True


def test_build_all_annotations_query_without_tags():
    q = build_all_annotations_query()
    assert q['target']['tags'] == []
    assert q['target']['matchAny'] is False


def test_build_all_annotations_query_empty_list():
    q = build_all_annotations_query([])
    assert q['target']['tags'] == []
    assert q['target']['matchAny'] is False


# --- ensure_all_annotations ---

def test_ensure_all_annotations_with_tags():
    dashboard = json.dumps({"title": "Test"})
    result = ensure_all_annotations(dashboard, annotation_tags=["deploy", "backup"])
    data = json.loads(result)
    ann = data['annotations']['list'][0]
    assert ann['name'] == 'All Annotations'
    assert ann['target']['tags'] == ['deploy', 'backup']
    assert ann['target']['matchAny'] is True


def test_ensure_all_annotations_without_tags():
    dashboard = json.dumps({"title": "Test"})
    result = ensure_all_annotations(dashboard)
    data = json.loads(result)
    ann = data['annotations']['list'][0]
    assert ann['target']['tags'] == []
    assert ann['target']['matchAny'] is False


def test_ensure_all_annotations_replaces_existing():
    dashboard = json.dumps({
        "title": "Test",
        "annotations": {"list": [
            {"name": "All Annotations", "target": {"tags": [], "matchAny": False}},
            {"name": "Other", "target": {"tags": ["foo"]}},
        ]}
    })
    result = ensure_all_annotations(dashboard, annotation_tags=["deploy"])
    data = json.loads(result)
    all_ann = [a for a in data['annotations']['list'] if a['name'] == 'All Annotations']
    assert len(all_ann) == 1
    assert all_ann[0]['target']['tags'] == ['deploy']
    assert all_ann[0]['target']['matchAny'] is True
    # Other annotations preserved
    other = [a for a in data['annotations']['list'] if a['name'] == 'Other']
    assert len(other) == 1


def test_ensure_all_annotations_preserves_other_annotations():
    dashboard = json.dumps({
        "title": "Test",
        "annotations": {"list": [
            {"name": "Custom", "enable": True, "target": {"tags": ["custom"]}},
        ]}
    })
    result = ensure_all_annotations(dashboard, annotation_tags=["deploy"])
    data = json.loads(result)
    assert len(data['annotations']['list']) == 2
    names = [a['name'] for a in data['annotations']['list']]
    assert 'Custom' in names
    assert 'All Annotations' in names


# --- load_dashboard with annotation_tags ---

def test_load_dashboard_passes_annotation_tags():
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump({"title": "Test"}, f)
        path = f.name
    try:
        result = load_dashboard(path, annotation_tags=["deploy", "test"])
        data = json.loads(result)
        ann = [a for a in data['annotations']['list'] if a['name'] == 'All Annotations']
        assert len(ann) == 1
        assert ann[0]['target']['tags'] == ['deploy', 'test']
        assert ann[0]['target']['matchAny'] is True
    finally:
        os.unlink(path)
