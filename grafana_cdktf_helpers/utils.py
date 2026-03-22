"""Utility functions for CDKTF Grafana projects."""
import json
import os
from typing import Optional, Dict, List


ALL_ANNOTATIONS_QUERY = {
    "datasource": {
        "type": "grafana",
        "uid": "-- Grafana --"
    },
    "enable": True,
    "iconColor": "green",
    "name": "All Annotations",
    "target": {
        "limit": 100,
        "matchAny": False,
        "tags": [],
        "type": "tags"
    }
}


def ensure_all_annotations(dashboard_json: str) -> str:
    """
    Ensure a dashboard JSON string includes the all-annotations query.

    If the dashboard already has an annotation query with empty tags
    (matching all annotations), it is left unchanged. Otherwise, the
    query is appended to the annotations list.

    Args:
        dashboard_json: Dashboard JSON string.

    Returns:
        Dashboard JSON string with the all-annotations query present.
    """
    dashboard = json.loads(dashboard_json)
    annotations = dashboard.setdefault('annotations', {})
    ann_list: List = annotations.setdefault('list', [])
    # Check if an all-annotations query already exists
    for ann in ann_list:
        target = ann.get('target', {})
        if (
            target.get('type') == 'tags'
            and target.get('tags') == []
            and ann.get('enable', False)
        ):
            return dashboard_json
    ann_list.append(ALL_ANNOTATIONS_QUERY)
    return json.dumps(dashboard)


def load_dashboard(
    path: str,
    replacements: Optional[Dict[str, str]] = None,
    add_all_annotations: bool = True,
) -> str:
    """
    Load a dashboard JSON file and optionally apply string replacements.

    Args:
        path: Path to the JSON file (absolute or relative to cwd).
        replacements: Optional dict of {placeholder: value} replacements
            to apply to the raw JSON string before returning.
        add_all_annotations: If True (default), inject an annotation query
            that shows all annotations on this dashboard.

    Returns:
        The JSON string (with replacements applied if any).
    """
    with open(path) as f:
        content = f.read()
    if add_all_annotations:
        content = ensure_all_annotations(content)
    if replacements:
        for placeholder, value in replacements.items():
            content = content.replace(placeholder, value)
    return content


def get_shared_dashboard_path(name: str) -> str:
    """
    Get the absolute path to a shared dashboard JSON file bundled
    with this package.

    Args:
        name: Dashboard filename (e.g. 'apache.json').

    Returns:
        Absolute path to the dashboard JSON file.
    """
    return os.path.join(
        os.path.dirname(__file__), 'dashboards', name
    )


def load_zoneminder_dashboard(
    include_zm_detect: bool = False,
    replacements: Optional[Dict[str, str]] = None,
    add_all_annotations: bool = True,
) -> str:
    """
    Load the bundled ZoneMinder dashboard JSON, optionally including
    the zm_detect ML detection panels.

    The dashboard uses ``${prom_uid}`` as a placeholder for the
    Prometheus datasource UID. Pass replacements to substitute it.

    Args:
        include_zm_detect: If True, append the zm_detect panels
            (ML object detection metrics) to the dashboard.
        replacements: Optional dict of {placeholder: value} replacements
            to apply to the raw JSON string before returning.
        add_all_annotations: If True (default), inject an annotation query
            that shows all annotations on this dashboard.

    Returns:
        The dashboard JSON string ready for use with CDKTF Dashboard.
    """
    base_path = get_shared_dashboard_path('zoneminder.json')
    with open(base_path) as f:
        dashboard = json.load(f)
    if include_zm_detect:
        detect_path = get_shared_dashboard_path(
            'zoneminder_zm_detect.json'
        )
        with open(detect_path) as f:
            detect_panels = json.load(f)
        dashboard['panels'].extend(detect_panels)
    content = json.dumps(dashboard)
    if add_all_annotations:
        content = ensure_all_annotations(content)
    if replacements:
        for placeholder, value in replacements.items():
            content = content.replace(placeholder, value)
    return content
