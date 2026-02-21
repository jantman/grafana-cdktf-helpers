"""Utility functions for CDKTF Grafana projects."""
import json
import os
from typing import Optional, Dict


def load_dashboard(
    path: str,
    replacements: Optional[Dict[str, str]] = None
) -> str:
    """
    Load a dashboard JSON file and optionally apply string replacements.

    Args:
        path: Path to the JSON file (absolute or relative to cwd).
        replacements: Optional dict of {placeholder: value} replacements
            to apply to the raw JSON string before returning.

    Returns:
        The JSON string (with replacements applied if any).
    """
    with open(path) as f:
        content = f.read()
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
