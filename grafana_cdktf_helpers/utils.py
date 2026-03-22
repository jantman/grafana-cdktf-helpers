"""Utility functions for CDKTF Grafana projects."""
import json
import os
from typing import Optional, Dict, List


def build_all_annotations_query(
    tags: Optional[List[str]] = None,
) -> dict:
    """Build an annotation query dict that matches annotations by tags.

    Args:
        tags: List of annotation tags. If non-empty, ``matchAny`` is set
            to ``True`` so the query matches annotations with ANY of the
            given tags. If empty or ``None``, falls back to empty tags
            (legacy behaviour).

    Returns:
        Annotation query dict suitable for a dashboard annotations list.
    """
    return {
        "datasource": {
            "type": "grafana",
            "uid": "-- Grafana --"
        },
        "enable": True,
        "iconColor": "green",
        "name": "All Annotations",
        "target": {
            "limit": 100,
            "matchAny": bool(tags),
            "tags": tags or [],
            "type": "tags"
        }
    }


# Backward-compatible alias
ALL_ANNOTATIONS_QUERY = build_all_annotations_query()


def ensure_all_annotations(
    dashboard_json: str,
    annotation_tags: Optional[List[str]] = None,
) -> str:
    """
    Ensure a dashboard JSON string includes the all-annotations query.

    Any existing "All Annotations" entry is replaced so that re-running
    synth updates the tag list.

    Args:
        dashboard_json: Dashboard JSON string.
        annotation_tags: Optional list of annotation tags to match.
            When provided, uses ``matchAny: true``.

    Returns:
        Dashboard JSON string with the all-annotations query present.
    """
    dashboard = json.loads(dashboard_json)
    annotations = dashboard.setdefault('annotations', {})
    ann_list: List = annotations.setdefault('list', [])
    # Remove any existing "All Annotations" entry
    ann_list[:] = [
        a for a in ann_list
        if a.get('name') != 'All Annotations'
    ]
    ann_list.append(build_all_annotations_query(annotation_tags))
    return json.dumps(dashboard)


def load_dashboard(
    path: str,
    replacements: Optional[Dict[str, str]] = None,
    add_all_annotations: bool = True,
    annotation_tags: Optional[List[str]] = None,
) -> str:
    """
    Load a dashboard JSON file and optionally apply string replacements.

    Args:
        path: Path to the JSON file (absolute or relative to cwd).
        replacements: Optional dict of {placeholder: value} replacements
            to apply to the raw JSON string before returning.
        add_all_annotations: If True (default), inject an annotation query
            that shows all annotations on this dashboard.
        annotation_tags: Optional list of annotation tags to include in the
            all-annotations query. When provided, uses ``matchAny: true``.

    Returns:
        The JSON string (with replacements applied if any).
    """
    with open(path) as f:
        content = f.read()
    if add_all_annotations:
        content = ensure_all_annotations(content, annotation_tags=annotation_tags)
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
    annotation_tags: Optional[List[str]] = None,
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
        annotation_tags: Optional list of annotation tags to include in the
            all-annotations query. When provided, uses ``matchAny: true``.

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
        content = ensure_all_annotations(content, annotation_tags=annotation_tags)
    if replacements:
        for placeholder, value in replacements.items():
            content = content.replace(placeholder, value)
    return content
